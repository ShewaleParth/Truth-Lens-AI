"""TruthLens AI - Source Fetcher.

Retrieves web pages over HTTP and extracts readable text and metadata.

Security and safety requirements implemented
--------------------------------------------
1. Only https:// and http:// schemes are permitted.
2. Private, loopback, link-local, and cloud metadata addresses are blocked
   both before DNS resolution and after (to stop redirect-based bypasses).
3. Redirects are followed manually; every destination is validated and its
   resolved addresses are checked before the next request is made.
4. Content-type must indicate HTML or plain text; binary files are rejected.
5. Downloaded body size is limited to MAX_BODY_BYTES.
6. Extracted plain text is truncated to MAX_TEXT_CHARS.
7. No scripts or downloaded code are executed.
8. Requests time out after FETCH_TIMEOUT_SECONDS.

Known limitations
-----------------
- JavaScript-rendered pages will not yield useful content.
- Pages that require authentication or cookies will fail gracefully.
- Some legitimate pages may return HTTP 403/429 and will be recorded as
  retrieval failures without substituting fabricated content.
- This implementation does not guarantee complete SSRF protection against
  all possible server-side behaviours; it provides best-effort defence
  using available network-level information.
"""

from __future__ import annotations

import ipaddress
import socket
import time
import urllib.parse
from typing import Optional

import httpcore
import httpx
from bs4 import BeautifulSoup

try:
    from backend.core.models import EvidenceItem, SourceQuality
except ModuleNotFoundError:
    from core.models import EvidenceItem, SourceQuality  # type: ignore


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

FETCH_TIMEOUT_SECONDS: float = 10.0
MAX_BODY_BYTES: int = 512 * 1024        # 512 KB
MAX_TEXT_CHARS: int = 8_000             # characters of extracted plain text

_ALLOWED_SCHEMES = frozenset({"http", "https"})

_CLOUD_METADATA_HOSTS = frozenset(
    {
        "169.254.169.254",   # AWS / GCP / Azure IMDS
        "metadata.google.internal",
        "instance-data",
    }
)

_TRUSTED_DOMAINS = frozenset(
    {
        "rbi.org.in",
        "dicgc.org.in",
        "sebi.gov.in",
        "npci.org.in",
        "india.gov.in",
        "mygov.in",
        "incometax.gov.in",
        "finmin.nic.in",
        "mospi.gov.in",
        "pib.gov.in",         # Press Information Bureau – official fact-checker
        "federalreserve.gov", # US Central Bank
        "bankofengland.co.uk",
        "ecb.europa.eu",
        "bis.org",
        "imf.org",
        "worldbank.org",
        "wikipedia.org",
        "britannica.com",
        "reuters.com",
        "bloomberg.com",
        "bbc.com",
        "apnews.com",
        "sbi.co.in",
        "hdfcbank.com",
        "icicibank.com",
        "axisbank.com",
        "bankofbaroda.in",
        "pnbindia.in",
        "kotakbank.com",
        "timesofindia.com",
        "thehindu.com",
        "livemint.com",
        "businessstandard.com",
        "economictimes.indiatimes.com",
        "ndtv.com",
        "moneycontrol.com",
    }
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_source(url: str, timeout: Optional[float] = None) -> EvidenceItem:
    """Fetch a URL and return an EvidenceItem with extracted text.

    Args:
        url: The URL to retrieve (must be https or http, must resolve to a
             publicly routable address).

    Returns:
        EvidenceItem — with retrieval_success=True and populated fields on
        success, or retrieval_success=False and an error message on failure.

    This function never fabricates content.  All failure modes return a
    clearly-marked EvidenceItem with retrieval_success=False.
    """
    validation_error = _validate_url(url)
    if validation_error:
        return _failed_item(url, f"URL validation failed: {validation_error}")

    try:
        return _do_fetch(url, timeout=timeout)
    except httpx.TimeoutException:
        return _failed_item(url, "Request timed out.")
    except httpx.TooManyRedirects:
        return _failed_item(url, "Too many redirects.")
    except httpx.RequestError as exc:
        return _failed_item(url, f"Network error: {exc}")
    except _SSRFBlockedError as exc:
        return _failed_item(url, f"Blocked (SSRF protection): {exc}")
    except Exception as exc:  # noqa: BLE001
        return _failed_item(url, f"Unexpected fetch error: {type(exc).__name__}: {exc}")


def classify_source_quality(url: str) -> SourceQuality:
    """Return a SourceQuality rating for a URL based on its registered domain.

    Uses ``str.removeprefix`` (Python 3.9+) to strip the ``www.`` subdomain
    correctly.  The previous ``lstrip("www.")`` stripped individual characters
    rather than the literal prefix, which could silently mangle hostnames
    (e.g. ``www.website.com`` → ``ebsite.com``).
    """
    try:
        hostname = urllib.parse.urlparse(url).hostname or ""
        hostname = hostname.removeprefix("www.")
    except Exception:
        return SourceQuality.UNKNOWN

    _AUTHORITATIVE_SUFFIXES = (".gov.in", ".org.in", ".nic.in", ".gov", ".fed.us")
    _AUTHORITATIVE_EXACT = {
        "india.gov.in",
        "mygov.in",
        "pib.gov.in",
        "federalreserve.gov",
        "bankofengland.co.uk",
        "ecb.europa.eu",
        "bis.org",
        "imf.org",
        "worldbank.org",
    }

    def _is_authoritative(domain: str) -> bool:
        return any(domain.endswith(s) for s in _AUTHORITATIVE_SUFFIXES) or domain in _AUTHORITATIVE_EXACT

    # Direct match
    if hostname in _TRUSTED_DOMAINS:
        return SourceQuality.AUTHORITATIVE if _is_authoritative(hostname) else SourceQuality.REPUTABLE

    # Suffix match (e.g. sub.rbi.org.in)
    for domain in _TRUSTED_DOMAINS:
        if hostname.endswith("." + domain) or hostname == domain:
            return SourceQuality.AUTHORITATIVE if _is_authoritative(domain) else SourceQuality.REPUTABLE

    return SourceQuality.UNKNOWN


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


class _SSRFBlockedError(Exception):
    """Raised when a URL or resolved address is blocked for SSRF protection."""


def _validate_url(url: str) -> Optional[str]:
    """Return an error string if the URL is unsafe, else None."""
    if not url or not isinstance(url, str):
        return "URL is empty or not a string."

    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return "URL could not be parsed."

    if parsed.scheme not in _ALLOWED_SCHEMES:
        return f"Scheme '{parsed.scheme}' is not permitted (only http/https)."

    if parsed.username is not None or parsed.password is not None:
        return "URLs containing embedded credentials are not permitted."

    try:
        port = parsed.port
    except ValueError:
        return "URL contains an invalid port."
    if port is not None and not 1 <= port <= 65535:
        return "URL contains an invalid port."

    hostname = parsed.hostname
    if not hostname:
        return "URL has no hostname."

    if hostname in _CLOUD_METADATA_HOSTS:
        return f"Hostname '{hostname}' is a blocked cloud metadata endpoint."

    return None


def _resolve_and_check(hostname: str) -> tuple[str, ...]:
    """Resolve once, reject every non-global address, and return pinned IPs."""
    try:
        results = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise _SSRFBlockedError(f"DNS resolution failed: {exc}") from exc

    addresses: list[str] = []
    for _family, _type, _proto, _canonname, sockaddr in results:
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            raise _SSRFBlockedError("DNS returned an invalid IP address.")
        # `is_global` also excludes special-use ranges such as shared address
        # space that is neither RFC1918-private nor globally routable.
        if (
            not ip.is_global
            or ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise _SSRFBlockedError(
                f"Resolved address {ip_str} is in a non-public range."
            )
        addresses.append(ip.compressed)

    if not addresses:
        raise _SSRFBlockedError("DNS resolution returned no addresses.")
    # Deduplicate while preserving resolver order and keep resource use bounded.
    return tuple(dict.fromkeys(addresses))[:16]


class _DeadlineNetworkStream:
    """Apply one absolute deadline to every socket operation in a request."""

    def __init__(self, stream, deadline: float) -> None:
        self._stream = stream
        self._deadline = deadline

    def _remaining(self, requested: Optional[float]) -> float:
        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise httpcore.ReadTimeout("Total source-fetch deadline exceeded.")
        return min(remaining, requested) if requested is not None else remaining

    def read(self, max_bytes: int, timeout: Optional[float] = None) -> bytes:
        return self._stream.read(max_bytes, timeout=self._remaining(timeout))

    def write(self, buffer: bytes, timeout: Optional[float] = None) -> None:
        self._stream.write(buffer, timeout=self._remaining(timeout))

    def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        stream = self._stream.start_tls(
            ssl_context,
            server_hostname=server_hostname,
            timeout=self._remaining(timeout),
        )
        return _DeadlineNetworkStream(stream, self._deadline)

    def get_extra_info(self, info: str):
        return self._stream.get_extra_info(info)

    def close(self) -> None:
        self._stream.close()


def _normalise_dns_hostname(hostname: str) -> str:
    normalized = hostname.rstrip(".").lower()
    try:
        return normalized.encode("idna").decode("ascii")
    except UnicodeError:
        return normalized


class _PinnedNetworkBackend(httpcore.SyncBackend):
    """Connect only to the public IPs validated for the current URL host.

    HTTP core still receives the original hostname for the HTTP Host header and
    TLS SNI/certificate validation; only the TCP peer is replaced with a pinned
    numeric IP, closing the DNS-rebinding gap between preflight and connect.
    """

    def __init__(self, hostname: str, addresses: tuple[str, ...], deadline: float) -> None:
        self._hostname = _normalise_dns_hostname(hostname)
        self._addresses = addresses
        self._deadline = deadline

    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        normalized_host = host.decode("ascii") if isinstance(host, bytes) else str(host)
        if _normalise_dns_hostname(normalized_host) != self._hostname:
            raise httpcore.ConnectError("Connection host differs from DNS-validated host.")

        last_error = None
        for address in self._addresses:
            try:
                remaining = self._deadline - time.monotonic()
                if remaining <= 0:
                    raise httpcore.ConnectTimeout("Total source-fetch deadline exceeded.")
                stream = super().connect_tcp(
                    address,
                    port,
                    timeout=min(remaining, timeout) if timeout is not None else remaining,
                    local_address=local_address,
                    socket_options=socket_options,
                )
                return _DeadlineNetworkStream(stream, self._deadline)
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last_error = exc
        raise httpcore.ConnectError("Could not connect to any DNS-validated address.") from last_error


class _CoreResponseStream(httpx.SyncByteStream):
    def __init__(self, response: httpcore.Response) -> None:
        self._response = response

    def __iter__(self):
        yield from self._response.iter_stream()

    def close(self) -> None:
        self._response.close()


class _PinnedHTTPTransport(httpx.BaseTransport):
    """Minimal HTTPX adapter using HTTP Core with a pinned DNS backend."""

    def __init__(self, hostname: str, addresses: tuple[str, ...], deadline: float) -> None:
        self._pool = httpcore.ConnectionPool(
            network_backend=_PinnedNetworkBackend(hostname, addresses, deadline),
            max_connections=1,
            max_keepalive_connections=0,
        )

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        core_request = httpcore.Request(
            request.method,
            str(request.url),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
        try:
            core_response = self._pool.handle_request(core_request)
        except httpcore.TimeoutException as exc:
            raise httpx.TimeoutException(str(exc), request=request) from exc
        except httpcore.NetworkError as exc:
            raise httpx.NetworkError(str(exc), request=request) from exc
        return httpx.Response(
            status_code=core_response.status,
            headers=core_response.headers,
            stream=_CoreResponseStream(core_response),
            extensions=core_response.extensions,
            request=request,
        )

    def close(self) -> None:
        self._pool.close()


def _do_fetch(url: str, timeout: Optional[float] = None) -> EvidenceItem:
    """Fetch a page while validating every redirect before following it."""

    headers = {
        "User-Agent": (
            "TruthLensAI-Fetcher/0.2 (financial-misinformation-checker; "
            "contact: see project documentation)"
        ),
        "Accept": "text/html,text/plain;q=0.8,*/*;q=0.5",
        "Accept-Language": "en-IN,en;q=0.8,hi;q=0.5",
    }

    total_timeout = max(0.1, timeout or FETCH_TIMEOUT_SECONDS)
    deadline = time.monotonic() + total_timeout
    current_url = url
    body = b""
    final_url = url
    content_type = ""
    for redirect_count in range(6):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return _failed_item(url, "Total source-fetch deadline exceeded.")
        validation_error = _validate_url(current_url)
        if validation_error:
            return _failed_item(url, f"Redirect target validation failed: {validation_error}")
        parsed = urllib.parse.urlparse(current_url)
        hostname = parsed.hostname or ""
        addresses = _resolve_and_check(hostname)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return _failed_item(url, "Total source-fetch deadline exceeded.")
        transport = _PinnedHTTPTransport(hostname, addresses, deadline)
        request_timeout = httpx.Timeout(
            timeout=remaining,
            connect=min(5.0, remaining),
            read=min(5.0, remaining),
            write=min(5.0, remaining),
            pool=min(5.0, remaining),
        )
        with httpx.Client(
            transport=transport,
            follow_redirects=False,
            timeout=request_timeout,
            headers=headers,
            trust_env=False,
        ) as client:
            with client.stream("GET", current_url) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("location")
                    if not location:
                        return _failed_item(url, "Redirect response did not include a Location header.")
                    if redirect_count == 5:
                        return _failed_item(url, "Too many redirects.")
                    current_url = urllib.parse.urljoin(str(response.url), location)
                    continue
                final_url = str(response.url)
                content_type = response.headers.get("content-type", "").lower()
                if not _is_text_content(content_type):
                    return _failed_item(
                        url,
                        f"Content-type '{content_type}' is not supported (HTML or plain text only).",
                    )

                if response.status_code >= 400:
                    return _failed_item(
                        url,
                        f"HTTP {response.status_code}: {response.reason_phrase}.",
                    )

                for chunk in response.iter_bytes(chunk_size=8192):
                    if time.monotonic() >= deadline:
                        return _failed_item(url, "Total source-fetch deadline exceeded.")
                    remaining_bytes = MAX_BODY_BYTES - len(body)
                    if remaining_bytes <= 0:
                        break
                    body += chunk[:remaining_bytes]
                    if len(chunk) > remaining_bytes:
                        break
                break
        if time.monotonic() >= deadline:
            return _failed_item(url, "Total source-fetch deadline exceeded.")

    title, text = _parse_html(body, content_type)
    quality = classify_source_quality(final_url)

    return EvidenceItem(
        url=final_url,
        title=title[:512],
        excerpt=text[:MAX_TEXT_CHARS],
        source_quality=quality,
        retrieval_success=True,
        evidence_origin="fetched_page",
    )


def _is_text_content(content_type: str) -> bool:
    return "text/html" in content_type or "text/plain" in content_type


def _parse_html(body: bytes, content_type: str) -> tuple[str, str]:
    """Extract title and readable body text from HTML or plain text bytes."""
    if "text/plain" in content_type:
        text = body.decode("utf-8", errors="replace")
        return "", text.strip()

    try:
        soup = BeautifulSoup(body, "lxml")
    except Exception:
        soup = BeautifulSoup(body, "html.parser")

    # Remove noise elements
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
        tag.decompose()

    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else ""

    # Prefer main article content; fall back to body
    main = soup.find("article") or soup.find("main") or soup.find("body")
    if main:
        paragraphs = main.find_all(["p", "h1", "h2", "h3", "h4", "li"])
        text = " ".join(
            p.get_text(separator=" ", strip=True)
            for p in paragraphs
            if p.get_text(strip=True)
        )
    else:
        text = soup.get_text(separator=" ", strip=True)

    # Collapse whitespace
    import re
    text = re.sub(r"\s{2,}", " ", text).strip()

    return title, text


def _failed_item(url: str, error: str) -> EvidenceItem:
    return EvidenceItem(
        url=url,
        retrieval_success=False,
        retrieval_error=error,
        source_quality=SourceQuality.REJECTED,
        evidence_origin="fetched_page",
    )
