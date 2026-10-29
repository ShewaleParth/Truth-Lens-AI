"""TruthLens AI - Evidence Retriever.

Orchestrates multi-provider evidence gathering for extracted claims and assertions.

Provider Architecture
---------------------
Evidence retrieval is abstracted behind the EvidenceProvider (BaseSearchProvider) interface.
The system supports multiple search backends with automatic priority ordering and controlled fallback:

1. SerperProvider: Primary search API (Google Serper; requires SERPER_API_KEY).
2. DuckDuckGoProvider: Fallback HTML scraper (requires no API key).
3. TavilyProvider: Optional search API (requires TAVILY_API_KEY; skipped completely if key is absent).
4. NoOpProvider: Deterministic no-op searcher used for offline testing or disabled search.

Default priority: Serper -> DuckDuckGo

Configuration
-------------
- Provider order is configurable via SEARCH_PROVIDER_ORDER (e.g. 'serper,duckduckgo').
- Providers requiring API keys (Serper, Tavily) are automatically disabled/skipped when their keys are missing.
- SEARCH_CORROBORATE_PROVIDERS: When False (default), continues to the next provider when
  evidence from the current provider does not directly resolve every material assertion.
  When True, queries multiple providers to assemble corroborating sources.
- Controlled fallback handles timeouts, rate limits (HTTP 429), authentication failures (HTTP 401/403),
  and network disruptions by gracefully cascading from Serper to DuckDuckGo.
- Successful searches with 0 results are explicitly distinguished from provider failures.
- All evidence items record source URLs, excerpts, source quality tiers, and provider attribution.
"""

from __future__ import annotations

import logging
import re
import time
import urllib.parse
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import httpx
from pydantic import BaseModel

try:
    from backend.core.models import (
        EvidenceBundle,
        EvidenceItem,
        ExtractedClaim,
        SourceQuality,
    )
    from backend.services.source_fetcher import classify_source_quality, fetch_source
    from backend.config import get_settings
except ModuleNotFoundError:
    from core.models import (  # type: ignore
        EvidenceBundle,
        EvidenceItem,
        ExtractedClaim,
        SourceQuality,
    )
    from services.source_fetcher import classify_source_quality, fetch_source  # type: ignore
    from config import get_settings  # type: ignore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration Constants
# ---------------------------------------------------------------------------

MAX_RESULTS_PER_QUERY = 5
MAX_TOTAL_ITEMS = 20
MAX_SEARCH_QUERIES = 8
MAX_SOURCE_FETCHES = 3
SEARCH_TIMEOUT_SECONDS = 8.0
MAX_EXCERPT_LENGTH = 800

_PREFERRED_SITE_OPERATORS = [
    "site:rbi.org.in",
    "site:sebi.gov.in",
    "site:npci.org.in",
    "site:india.gov.in",
    "site:pib.gov.in",
]


# ---------------------------------------------------------------------------
# Base Provider Interface
# ---------------------------------------------------------------------------


class BaseSearchProvider(ABC):
    """Abstract interface for evidence search providers.

    Concrete providers implement `search` and return a list of EvidenceItems.
    They must never fabricate URLs, titles, or excerpts.
    """

    @abstractmethod
    def search(
        self,
        query: str,
        max_results: int = MAX_RESULTS_PER_QUERY,
        timeout: Optional[float] = None,
    ) -> list[EvidenceItem]:
        """Perform a search and return a list of EvidenceItems.

        Implementations must:
        - Return an empty list rather than raising if no results are found.
        - Set retrieval_success=False on items when encountering network or provider errors.
        - Never invent results.
        """

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """Short identifier used in EvidenceBundle.search_provider_used."""

    @property
    def is_available(self) -> bool:
        """Return True if this provider is configured and ready for search."""
        return True


# Alias for compatibility with external references
EvidenceProvider = BaseSearchProvider


# ---------------------------------------------------------------------------
# 1. Tavily Search Provider
# ---------------------------------------------------------------------------


class TavilyProvider(BaseSearchProvider):
    """Evidence provider using the official Tavily Search API.

    Requires TAVILY_API_KEY. If absent, provider is automatically disabled.
    Endpoint: https://api.tavily.com/search
    """

    _API_URL = "https://api.tavily.com/search"

    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout: Optional[float] = None,
    ):
        if api_key is not None:
            self._api_key = api_key
        else:
            try:
                self._api_key = get_settings().TAVILY_API_KEY
            except Exception:
                self._api_key = None

        if timeout is not None:
            self._timeout = timeout
        else:
            try:
                self._timeout = get_settings().REQUEST_TIMEOUT_SECONDS
            except Exception:
                self._timeout = SEARCH_TIMEOUT_SECONDS

    @property
    def provider_id(self) -> str:
        return "tavily"

    @property
    def is_available(self) -> bool:
        return bool(self._api_key and self._api_key.strip())

    def search(
        self,
        query: str,
        max_results: int = MAX_RESULTS_PER_QUERY,
        timeout: Optional[float] = None,
    ) -> list[EvidenceItem]:
        if not self.is_available:
            return [_search_failure_item("Tavily API key is not configured.", provider=self.provider_id)]

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        payload = {
            "api_key": self._api_key,
            "query": query,
            "search_depth": "basic",
            "max_results": max_results,
            "include_answer": False,
            "include_raw_content": False,
        }

        try:
            response = httpx.post(
                self._API_URL,
                json=payload,
                headers=headers,
                timeout=min(self._timeout, timeout) if timeout is not None else self._timeout,
            )
        except httpx.TimeoutException:
            logger.warning("Tavily search request timed out.")
            return [_search_failure_item("Tavily search request timed out.", provider=self.provider_id)]
        except httpx.RequestError as exc:
            logger.warning("Tavily search network error: %s", type(exc).__name__)
            return [_search_failure_item(f"Tavily search network error: {exc}", provider=self.provider_id)]

        if response.status_code in (401, 403):
            logger.warning("Tavily authentication failed or quota exhausted (HTTP %d).", response.status_code)
            return [
                _search_failure_item(
                    f"Tavily authentication failed or quota exhausted (HTTP {response.status_code}).",
                    provider=self.provider_id,
                )
            ]
        if response.status_code == 429:
            logger.warning("Tavily rate limit exceeded (HTTP 429).")
            return [_search_failure_item("Tavily rate limit exceeded (HTTP 429).", provider=self.provider_id)]
        if response.status_code != 200:
            logger.warning("Tavily search failed with HTTP %d.", response.status_code)
            return [
                _search_failure_item(
                    f"Tavily search failed with HTTP {response.status_code}.",
                    provider=self.provider_id,
                )
            ]

        try:
            data = response.json()
        except Exception as exc:
            logger.warning("Tavily returned invalid JSON: %s", type(exc).__name__)
            return [_search_failure_item(f"Tavily returned invalid JSON: {exc}", provider=self.provider_id)]

        items: list[EvidenceItem] = []
        raw_results = data.get("results", [])
        logger.info("Tavily search succeeded; retrieved %d results.", len(raw_results))
        for r in raw_results[:max_results]:
            url = (r.get("url") or "").strip()
            if not url or not url.startswith("http"):
                continue

            title = (r.get("title") or "").strip()[:512]
            excerpt = (r.get("content") or "").strip()[:MAX_EXCERPT_LENGTH]
            published_date = r.get("published_date")
            quality = classify_source_quality(url)

            items.append(
                EvidenceItem(
                    url=url,
                    title=title,
                    excerpt=excerpt,
                    published_date=published_date,
                    source_quality=quality,
                    retrieval_success=True,
                    provider=self.provider_id,
                )
            )

        return items


# ---------------------------------------------------------------------------
# 2. Serper Google Search Provider
# ---------------------------------------------------------------------------


class SerperProvider(BaseSearchProvider):
    """Evidence provider using the official Serper Google Search API.

    Requires SERPER_API_KEY. If absent, provider is automatically disabled.
    Endpoint: https://google.serper.dev/search
    """

    _API_URL = "https://google.serper.dev/search"

    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout: Optional[float] = None,
    ):
        if api_key is not None:
            self._api_key = api_key
        else:
            try:
                self._api_key = get_settings().SERPER_API_KEY
            except Exception:
                self._api_key = None

        if timeout is not None:
            self._timeout = timeout
        else:
            try:
                self._timeout = get_settings().REQUEST_TIMEOUT_SECONDS
            except Exception:
                self._timeout = SEARCH_TIMEOUT_SECONDS

    @property
    def provider_id(self) -> str:
        return "serper"

    @property
    def is_available(self) -> bool:
        return bool(self._api_key and self._api_key.strip())

    def search(
        self,
        query: str,
        max_results: int = MAX_RESULTS_PER_QUERY,
        timeout: Optional[float] = None,
    ) -> list[EvidenceItem]:
        if not self.is_available:
            return [_search_failure_item("Serper API key is not configured.", provider=self.provider_id)]

        headers = {
            "X-API-KEY": self._api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        payload = {
            "q": query,
            "num": max_results,
            "gl": "in",
            "hl": "en",
        }

        try:
            response = httpx.post(
                self._API_URL,
                json=payload,
                headers=headers,
                timeout=min(self._timeout, timeout) if timeout is not None else self._timeout,
            )
        except httpx.TimeoutException:
            logger.warning("Serper search request timed out.")
            return [_search_failure_item("Serper search request timed out.", provider=self.provider_id)]
        except httpx.RequestError as exc:
            logger.warning("Serper search network error: %s", type(exc).__name__)
            return [_search_failure_item(f"Serper search network error: {exc}", provider=self.provider_id)]

        if response.status_code in (401, 403):
            logger.warning("Serper authentication failed or quota exhausted (HTTP %d).", response.status_code)
            return [
                _search_failure_item(
                    f"Serper authentication failed or quota exhausted (HTTP {response.status_code}).",
                    provider=self.provider_id,
                )
            ]
        if response.status_code == 429:
            logger.warning("Serper rate limit exceeded (HTTP 429).")
            return [_search_failure_item("Serper rate limit exceeded (HTTP 429).", provider=self.provider_id)]
        if response.status_code != 200:
            logger.warning("Serper search failed with HTTP %d.", response.status_code)
            return [
                _search_failure_item(
                    f"Serper search failed with HTTP {response.status_code}.",
                    provider=self.provider_id,
                )
            ]

        try:
            data = response.json()
        except Exception as exc:
            logger.warning("Serper returned invalid JSON: %s", type(exc).__name__)
            return [_search_failure_item(f"Serper returned invalid JSON: {exc}", provider=self.provider_id)]

        items: list[EvidenceItem] = []
        organic_results = data.get("organic", [])
        logger.info("Serper search succeeded; retrieved %d organic results.", len(organic_results))
        for r in organic_results[:max_results]:
            url = (r.get("link") or "").strip()
            if not url or not url.startswith("http"):
                continue

            title = (r.get("title") or "").strip()[:512]
            excerpt = (r.get("snippet") or "").strip()[:MAX_EXCERPT_LENGTH]
            published_date = r.get("date")
            quality = classify_source_quality(url)

            items.append(
                EvidenceItem(
                    url=url,
                    title=title,
                    excerpt=excerpt,
                    published_date=published_date,
                    source_quality=quality,
                    retrieval_success=True,
                    provider=self.provider_id,
                )
            )

        return items


# ---------------------------------------------------------------------------
# 3. DuckDuckGo HTML Provider (Fallback, no API key required)
# ---------------------------------------------------------------------------


class DuckDuckGoProvider(BaseSearchProvider):
    """Scrapes DuckDuckGo HTML search results without an API key.

    Limitations:
    - Subject to rate-limiting and anti-scraping blocks.
    - Treats empty results or anti-bot challenge pages as provider failures.
    - Used as a free local development and emergency fallback provider.
    """

    _SEARCH_URL = "https://html.duckduckgo.com/html/"

    def __init__(self, timeout: Optional[float] = None):
        if timeout is not None:
            self._timeout = timeout
        else:
            try:
                self._timeout = get_settings().REQUEST_TIMEOUT_SECONDS
            except Exception:
                self._timeout = SEARCH_TIMEOUT_SECONDS

    @property
    def provider_id(self) -> str:
        return "duckduckgo"

    @property
    def is_available(self) -> bool:
        return True

    def search(
        self,
        query: str,
        max_results: int = MAX_RESULTS_PER_QUERY,
        timeout: Optional[float] = None,
    ) -> list[EvidenceItem]:
        try:
            response = httpx.post(
                self._SEARCH_URL,
                data={"q": query, "kl": "in-en"},
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (compatible; TruthLensAI/0.2; "
                        "+https://github.com/truthlensai)"
                    ),
                    "Accept": "text/html",
                },
                timeout=min(self._timeout, timeout) if timeout is not None else self._timeout,
                follow_redirects=True,
            )
        except httpx.TimeoutException:
            logger.warning("DuckDuckGo search request timed out.")
            return [_search_failure_item("DuckDuckGo search timed out.", provider=self.provider_id)]
        except httpx.RequestError as exc:
            logger.warning("DuckDuckGo search network error: %s", type(exc).__name__)
            return [_search_failure_item(f"DuckDuckGo network error: {exc}", provider=self.provider_id)]

        if response.status_code == 429:
            logger.warning("DuckDuckGo rate limit exceeded (HTTP 429).")
            return [_search_failure_item("DuckDuckGo rate limit exceeded (HTTP 429).", provider=self.provider_id)]
        if response.status_code in (403, 401):
            logger.warning("DuckDuckGo blocked request (HTTP %d).", response.status_code)
            return [_search_failure_item(f"DuckDuckGo blocked request (HTTP {response.status_code}).", provider=self.provider_id)]
        if response.status_code != 200:
            logger.warning("DuckDuckGo search returned HTTP %d.", response.status_code)
            return [_search_failure_item(f"DuckDuckGo HTTP {response.status_code}.", provider=self.provider_id)]

        # Check for bot challenge or block markers in the HTML
        text_lower = response.text.lower()
        if "anomaly-modal" in text_lower or "bot detection" in text_lower or ("captcha" in text_lower and "results" not in text_lower):
            logger.warning("DuckDuckGo returned anti-bot challenge or block page.")
            return [_search_failure_item("DuckDuckGo returned anti-bot challenge or block page.", provider=self.provider_id)]

        return self._parse_results(response.text, max_results)

    def _parse_results(self, html: str, max_results: int) -> list[EvidenceItem]:
        from bs4 import BeautifulSoup

        items: list[EvidenceItem] = []
        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception:
            soup = BeautifulSoup(html, "html.parser")

        for result in soup.select(".result")[:max_results]:
            title_tag = result.select_one(".result__a")
            url_tag = result.select_one(".result__url")
            snip_tag = result.select_one(".result__snippet")

            title = title_tag.get_text(strip=True) if title_tag else ""
            raw_url = url_tag.get_text(strip=True) if url_tag else ""
            excerpt = snip_tag.get_text(strip=True) if snip_tag else ""

            if raw_url and not raw_url.startswith("http"):
                raw_url = "https://" + raw_url.lstrip("/")

            if not raw_url:
                continue

            quality = classify_source_quality(raw_url)
            items.append(
                EvidenceItem(
                    url=raw_url,
                    title=title[:512],
                    excerpt=excerpt[:MAX_EXCERPT_LENGTH],
                    source_quality=quality,
                    retrieval_success=True,
                    provider=self.provider_id,
                )
            )

        return items


# ---------------------------------------------------------------------------
# 4. NoOp Provider (Used when search is disabled or in offline tests)
# ---------------------------------------------------------------------------


class NoOpProvider(BaseSearchProvider):
    """Returns empty results. Used when no search provider is configured or available."""

    @property
    def provider_id(self) -> str:
        return "none"

    @property
    def is_available(self) -> bool:
        return True

    def search(
        self,
        query: str,
        max_results: int = MAX_RESULTS_PER_QUERY,
        timeout: Optional[float] = None,
    ) -> list[EvidenceItem]:
        return []


# ---------------------------------------------------------------------------
# Provider Factory and Priority Resolution
# ---------------------------------------------------------------------------


def _get_providers() -> list[BaseSearchProvider]:
    """Return ordered list of available search providers according to configuration.

    SEARCH_PROVIDER_ORDER is authoritative. An empty order or any explicit
    `none`/`noop` entry disables external search. Configuration failures are
    allowed to propagate so they cannot silently enable a default live provider.
    API-key providers are skipped when their keys are absent; if no usable
    providers remain, the no-op provider is returned.
    """
    settings = get_settings()
    order = settings.search_provider_order_list
    normalized_order = [name.strip().lower() for name in order if name.strip()]
    if not normalized_order or any(name in {"none", "noop"} for name in normalized_order):
        logger.info("External search disabled by SEARCH_PROVIDER_ORDER.")
        return [NoOpProvider()]

    provider_map = {
        "tavily": TavilyProvider,
        "serper": SerperProvider,
        "duckduckgo": DuckDuckGoProvider,
        "duckduckgo_html": DuckDuckGoProvider,
    }

    providers: list[BaseSearchProvider] = []
    for name in order:
        name_clean = name.strip().lower()
        provider_cls = provider_map.get(name_clean)
        if not provider_cls:
            logger.warning("Unrecognised search provider '%s' in SEARCH_PROVIDER_ORDER; skipping.", name_clean)
            continue
        instance = provider_cls()
        # API-key providers must be automatically disabled when unconfigured
        if instance.is_available:
            providers.append(instance)
        else:
            logger.info("Search provider '%s' skipped (API key not configured).", name_clean)

    if not providers:
        logger.info("No search providers available; defaulting to NoOpProvider.")
        providers.append(NoOpProvider())

    return providers


def _get_provider() -> BaseSearchProvider:
    """Return the primary search provider (for backwards compatibility)."""
    providers = _get_providers()
    return providers[0] if providers else NoOpProvider()


# ---------------------------------------------------------------------------
# Query Generation
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Query Generation
# ---------------------------------------------------------------------------


class TargetedQuery(BaseModel):
    """A search query mapped to the specific assertion it was generated to verify."""

    query: str
    assertion_text: str


def _build_targeted_queries(claim: ExtractedClaim) -> list[TargetedQuery]:
    """Build focused, assertion-targeted search queries within a bounded request budget."""
    targeted_queries: list[TargetedQuery] = []
    seen: set[str] = set()

    def _add_query(q: str, assertion_text: str) -> None:
        clean = " ".join(q.split()).strip()
        if clean and clean.lower() not in seen and len(clean) >= 5:
            seen.add(clean.lower())
            targeted_queries.append(TargetedQuery(query=clean, assertion_text=assertion_text))

    is_rbi_context = any(
        re.search(r"\b(?:rbi|reserve bank of india)\b", a.text, re.IGNORECASE)
        for a in claim.assertions
    ) or bool(re.search(r"\b(?:rbi|reserve bank of india)\b", claim.normalised_text, re.IGNORECASE))

    for assertion in claim.assertions:
        text = assertion.text.strip().rstrip(".!?")
        lower = text.lower()
        focused_query_added = False

        if re.search(r"\bdicgc\b", lower):
            category = re.search(r"\b(commercial|co[\s-]?operative)\s+banks?\b", lower)
            if category:
                category_name = (
                    "commercial" if category.group(1).lower() == "commercial" else "cooperative"
                )
                domain = "site:dicgc.org.in OR site:rbi.org.in"
                _add_query(
                    f"{domain} DICGC {category_name} banks coverage insured",
                    assertion.text,
                )
                focused_query_added = True
            else:
                domain = "site:dicgc.org.in"
                _add_query(
                    f"{domain} DICGC deposit insurance maximum ₹5 lakh per depositor",
                    assertion.text,
                )
                focused_query_added = True
        elif is_rbi_context:
            if (
                re.search(r"\bcentral\s+bank\b", lower)
                and re.search(r"\b(?:united states|usa|u\.s\.)\b", lower)
            ):
                _add_query(
                    "site:federalreserve.gov Federal Reserve central bank United States",
                    assertion.text,
                )
                focused_query_added = True
            elif (
                re.search(r"\bcentral\s+bank\b", lower)
                and re.search(r"\bindia(?:'s)?\b", lower)
            ):
                _add_query(
                    "site:rbi.org.in Reserve Bank of India central bank India",
                    assertion.text,
                )
                focused_query_added = True
            elif assertion.assertion_type in ("announcement", "regulatory") and re.search(
                r"\b(?:announc\w*|circular|notice|order)\b", lower
            ):
                _add_query(
                    "(site:rbi.org.in OR site:pib.gov.in) RBI announcement bank accounts blocked",
                    assertion.text,
                )
                _add_query(
                    '(site:rbi.org.in OR site:pib.gov.in) RBI "no such circular"',
                    assertion.text,
                )
                focused_query_added = True
            elif assertion.assertion_type == "account_action" or re.search(
                r"\b(?:block\w*|freez\w*|suspend\w*)\b", lower
            ):
                _add_query(
                    "(site:rbi.org.in OR site:pib.gov.in) bank accounts will be blocked",
                    assertion.text,
                )
                _add_query(
                    'site:pib.gov.in fact check RBI bank accounts blocked',
                    assertion.text,
                )
                focused_query_added = True
            elif assertion.assertion_type == "deadline" or re.search(
                r"\b(?:tonight|today|immediately)\b", lower
            ):
                _add_query(
                    "(site:rbi.org.in OR site:pib.gov.in) bank accounts blocked tonight",
                    assertion.text,
                )
                _add_query(
                    '(site:rbi.org.in OR site:pib.gov.in) RBI "no such notice"',
                    assertion.text,
                )
                focused_query_added = True
            elif assertion.assertion_type == "payment_demand" or re.search(
                r"(?:₹|rs\.?|inr|fee|pay|charge)", lower
            ):
                _add_query(
                    "(site:rbi.org.in OR site:pib.gov.in) RBI 500 fee mandatory verification",
                    assertion.text,
                )
                _add_query(
                    "site:pib.gov.in fact check RBI 500 verification fee",
                    assertion.text,
                )
                focused_query_added = True
            else:
                domain = "site:rbi.org.in OR site:pib.gov.in"
                _add_query(f"{domain} {text}".strip(), assertion.text)
                focused_query_added = True
        elif re.search(r"\b(?:sbi|state bank of india|sbi netbanking|net\s*banking)\b", lower):
            # Bank-alert claims need both an official-source query and a
            # message/rumour query. Searching only the words in a phishing SMS
            # tends to retrieve generic KYC material that can look related but
            # cannot establish that the bank sent the message.
            official_domain = "site:sbi.co.in"
            is_suspension_or_kyc_claim = bool(
                re.search(r"\b(?:suspend\w*|block\w*|freeze\w*|kyc|verification|update)\b", lower)
            )
            if is_suspension_or_kyc_claim:
                _add_query(
                    f'{official_domain} SBI NetBanking KYC suspension notice',
                    assertion.text,
                )
                _add_query(
                    "SBI NetBanking KYC suspension message phishing fake link",
                    assertion.text,
                )
                focused_query_added = True
            else:
                _add_query(f'{official_domain} {text}', assertion.text)
                focused_query_added = True
        elif re.search(r"\bsebi\b", lower):
            domain = "site:sebi.gov.in"
        elif re.search(r"\bnpci\b", lower):
            domain = "site:npci.org.in"
        elif re.search(r"\b(?:india|indian)\b", lower):
            domain = "site:india.gov.in OR site:pib.gov.in"
        else:
            domain = ""

        if not focused_query_added:
            _add_query(f"{domain} {text}".strip(), assertion.text)

        if len(targeted_queries) >= MAX_SEARCH_QUERIES:
            return targeted_queries[:MAX_SEARCH_QUERIES]

    if not targeted_queries:
        _add_query(claim.normalised_text[:200], claim.normalised_text)

    return targeted_queries[:MAX_SEARCH_QUERIES]


def _build_queries(claim: ExtractedClaim) -> list[str]:
    """Build focused queries per assertion within a bounded request budget."""
    return [tq.query for tq in _build_targeted_queries(claim)]


# ---------------------------------------------------------------------------
# Multi-Provider Retrieval with Controlled Fallback
# ---------------------------------------------------------------------------


def retrieve_evidence(
    claim: ExtractedClaim,
    providers: Optional[list[BaseSearchProvider]] = None,
    corroborate: Optional[bool] = None,
    fetch_pages: Optional[bool] = None,
) -> EvidenceBundle:
    """Retrieve evidence for the given claim across configured search providers.

    Features:
    - Controlled fallback across providers (Tavily -> Serper -> DuckDuckGo).
    - Continues to the next provider on provider errors or when current evidence
      does not directly resolve every material assertion.
    - Distinguishes successful searches with 0 results from provider failures.
    - Avoids duplicate results via URL normalisation.
    - Records which provider supplied each evidence item.
    - Preserves search snippets and records whether bounded source-page fetching
      succeeded or failed.
    - Never fabricates evidence.

    Args:
        claim: ExtractedClaim with assertions and normalised text.
        providers: Optional explicit list of providers to use (defaults to configured order).
        corroborate: Optional flag to query multiple providers rather than stopping at the first success.

    Returns:
        EvidenceBundle containing evidence items, provider attribution, and error notes.
    """
    use_live_page_fetch = providers is None if fetch_pages is None else fetch_pages
    providers_skipped: list[str] = []
    if providers is None:
        try:
            settings = get_settings()
            configured_order = settings.search_provider_order_list
            if "serper" in configured_order and not settings.SERPER_API_KEY:
                providers_skipped.append("serper (API key not configured)")
            if "tavily" in configured_order and not settings.TAVILY_API_KEY:
                providers_skipped.append("tavily (API key not configured)")
        except Exception:
            pass

        providers = _get_providers()

    if corroborate is None:
        try:
            corroborate = getattr(get_settings(), "SEARCH_CORROBORATE_PROVIDERS", False)
        except Exception:
            corroborate = False

    targeted_queries = _build_targeted_queries(claim)
    try:
        request_timeout = max(0.1, float(get_settings().REQUEST_TIMEOUT_SECONDS))
    except Exception:
        request_timeout = 15.0
    deadline = time.monotonic() + request_timeout
    all_items: list[EvidenceItem] = []
    providers_attempted: list[str] = []
    provider_errors: list[tuple[str, str]] = []
    successful_providers: list[str] = []
    fetched_urls: set[str] = set()
    fetch_budget = MAX_SOURCE_FETCHES

    for provider in providers:
        p_id = provider.provider_id
        providers_attempted.append(p_id)
        logger.info("Attempting evidence search with provider: %s", p_id)

        if not provider.is_available:
            logger.info("Provider '%s' unavailable (API key not configured); skipping.", p_id)
            provider_errors.append((p_id, f"{p_id} API key not configured"))
            continue

        provider_failed = False
        provider_items: list[EvidenceItem] = []
        err_msg: Optional[str] = None

        for tq in targeted_queries:
            query = tq.query
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                err_msg = "Request evidence-retrieval time budget exhausted."
                provider_failed = True
                break
            try:
                results = provider.search(
                    query,
                    max_results=MAX_RESULTS_PER_QUERY,
                    timeout=remaining,
                )
            except Exception as exc:  # noqa: BLE001
                provider_failed = True
                err_msg = f"Search exception: {type(exc).__name__}: {exc}"
                break

            for item in results:
                if not item.retrieval_success:
                    provider_failed = True
                    err_msg = item.retrieval_error or "Search request failed"
                    break
                # Ensure provider tag and target assertion are recorded
                if not item.provider:
                    item.provider = p_id
                if not item.target_assertion:
                    item.target_assertion = tq.assertion_text
                provider_items.append(item)

            if provider_failed:
                break

        all_items.extend(provider_items)

        if provider_failed:
            logger.warning("Provider '%s' failed: %s; falling back to next provider if available.", p_id, err_msg)
            provider_errors.append((p_id, err_msg or "Search failed"))
        else:
            logger.info("Provider '%s' search succeeded; retrieved %d items.", p_id, len(provider_items))
            successful_providers.append(p_id)

        if use_live_page_fetch and fetch_budget:
            for item in provider_items:
                if fetch_budget <= 0 or time.monotonic() >= deadline:
                    break
                parsed = urllib.parse.urlparse(item.url)
                normalized_url = _normalise_url(item.url)
                if (
                    not normalized_url
                    or normalized_url in fetched_urls
                    or parsed.scheme not in ("http", "https")
                    or item.source_quality not in (SourceQuality.AUTHORITATIVE, SourceQuality.REPUTABLE)
                ):
                    continue
                fetched_urls.add(normalized_url)
                fetch_budget -= 1
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                _apply_fetched_page(item, timeout=min(remaining, 10.0))

        if not corroborate and _has_decisive_coverage(claim, all_items):
            break

        if time.monotonic() >= deadline:
            provider_errors.append(("retrieval", "Request evidence-retrieval time budget exhausted; results may be partial."))
            break

    deduplicated = _deduplicate(all_items)
    deduplicated = deduplicated[:MAX_TOTAL_ITEMS]

    total_retrieved = len(all_items)
    total_dedup = len(deduplicated)

    # Determine provider_error and search_provider_used
    if successful_providers:
        search_provider_used = ", ".join(successful_providers)
        provider_error = None
    elif provider_errors:
        search_provider_used = "none"
        provider_error = "; ".join(f"{p}: {e}" for p, e in provider_errors)
    else:
        search_provider_used = providers[0].provider_id if providers else "none"
        provider_error = None

    fallback_notes = [f"{p}: {e}" for p, e in provider_errors]

    return EvidenceBundle(
        items=deduplicated,
        search_provider_used=search_provider_used,
        provider_error=provider_error,
        total_retrieved=total_retrieved,
        total_deduplicated=total_dedup,
        providers_attempted=providers_attempted,
        provider_errors=fallback_notes,
        providers_skipped=providers_skipped,
        targeted_queries=[{"query": tq.query, "assertion_text": tq.assertion_text} for tq in targeted_queries],
    )


def _apply_fetched_page(item: EvidenceItem, timeout: float) -> None:
    """Replace a snippet with validated page text while retaining provenance."""
    if not item.search_snippet:
        item.search_snippet = item.excerpt
    page = fetch_source(item.url, timeout=timeout)
    if not page.retrieval_success or not page.excerpt.strip():
        item.page_fetch_error = page.retrieval_error or "Fetched page contained no readable text."
        return

    item.url = page.url
    item.title = page.title or item.title
    item.excerpt = page.excerpt
    item.source_quality = page.source_quality
    item.evidence_origin = "fetched_page"
    item.page_fetch_error = None


def _has_decisive_coverage(claim: ExtractedClaim, items: list[EvidenceItem]) -> bool:
    if not claim.assertions or not items:
        return False
    try:
        from backend.core.verdict_engine import verify_claims
    except ModuleNotFoundError:
        from core.verdict_engine import verify_claims  # type: ignore
    bundle = EvidenceBundle(items=items, search_provider_used="retrieval-check")
    verification = verify_claims(claim, bundle)
    return bool(verification.assertion_results) and all(
        result.verdict.value in {"TRUE", "FALSE"}
        for result in verification.assertion_results
    )


# ---------------------------------------------------------------------------
# Deduplication and URL Normalisation
# ---------------------------------------------------------------------------


def _deduplicate(items: list[EvidenceItem]) -> list[EvidenceItem]:
    """Remove items with duplicate URLs, preserving insertion order and source attribution."""
    seen_urls: set[str] = set()
    unique: list[EvidenceItem] = []
    for item in items:
        url_key = _normalise_url(item.url)
        if url_key and url_key not in seen_urls:
            seen_urls.add(url_key)
            unique.append(item)
    return unique


def _normalise_url(url: str) -> str:
    """Return a canonical representation of a URL for deduplication."""
    try:
        parsed = urllib.parse.urlparse(url.rstrip("/"))
        return urllib.parse.urlunparse(
            (
                parsed.scheme.lower(),
                (parsed.netloc or "").lower(),
                parsed.path,
                parsed.params,
                parsed.query,
                "",  # strip fragment
            )
        )
    except Exception:
        return url


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _search_failure_item(error: str, provider: Optional[str] = None) -> EvidenceItem:
    return EvidenceItem(
        url="about:error",
        retrieval_success=False,
        retrieval_error=error,
        source_quality=SourceQuality.REJECTED,
        provider=provider,
    )
