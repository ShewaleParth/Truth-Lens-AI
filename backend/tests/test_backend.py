"""TruthLens AI - Comprehensive Backend Test Suite (Phase 2).

Covers:
- Input validation (empty, whitespace, too long, malformed)
- Claim processing (simple, compound, Indian terminology, currency, negation)
- Evidence deduplication, URL normalisation, and provider failure handling
- Verdict engine (supporting, contradicting, mixed, insufficient evidence)
- Scam detector (urgent payment demand, OTP, suspicious link, harmless, multi-indicator)
- API integration (valid request, invalid request, provider failure, separation of concerns,
  health endpoint)

All tests are fully deterministic and use no live external requests.
Mocking is done via monkey-patching or in-process test doubles.

All tests are pytest-compatible AND unittest-compatible.
Run with:
    python -m unittest backend/tests/test_backend.py -v
or, once pytest is installed:
    pytest backend/tests/test_backend.py -v
"""

from __future__ import annotations

import os
import socket
import sys
import time
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import httpcore
import httpx

# ── Path setup ──────────────────────────────────────────────────────────────
_backend_dir = Path(__file__).resolve().parent.parent
_root_dir = _backend_dir.parent
for p in (_root_dir, _backend_dir):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

# Force no live search provider for every test in this module.
os.environ["SEARCH_PROVIDER_ORDER"] = "none"

# ── Imports after path + env setup ─────────────────────────────────────────
from backend.tests.asgi_test_client import InProcessTestClient

from backend.app import app
from backend.api.routes import require_analysis_access
from backend.config import get_settings
from backend.core.claim_processor import ClaimProcessingError, process_claim
from backend.core.models import (
    Assertion,
    AssertionVerification,
    EvidenceBundle,
    EvidenceItem,
    ExtractedClaim,
    RiskCategory,
    SourceQuality,
    Verdict,
)
from backend.core.scam_detector import (
    HIGH_RISK_THRESHOLD,
    MEDIUM_RISK_THRESHOLD,
    _score_to_category,
    assess_scam_risk,
)
from backend.core.verdict_engine import _aggregate_verdict, _rupee_amounts, verify_claims
from backend.services.evidence_retriever import (
    BaseSearchProvider,
    EvidenceProvider,
    DuckDuckGoProvider,
    NoOpProvider,
    SerperProvider,
    TavilyProvider,
    _deduplicate,
    _get_provider,
    _get_providers,
    _build_queries,
    _apply_fetched_page,
    _normalise_url,
    retrieve_evidence,
)
from backend.services.source_fetcher import (
    _PinnedNetworkBackend,
    _SSRFBlockedError,
    _resolve_and_check,
    _validate_url,
    classify_source_quality,
    fetch_source,
)

# The integration tests exercise the analysis pipeline with an authenticated
# test identity. Dedicated security tests cover missing/invalid tokens and limits.
app.dependency_overrides[require_analysis_access] = lambda: "test-user"
client = InProcessTestClient(app)


# ===========================================================================
# 1 — Input validation
# ===========================================================================


class TestInputValidation(unittest.TestCase):
    """Claim processor correctly rejects invalid inputs."""

    def test_empty_string_raises(self):
        with self.assertRaises(ClaimProcessingError):
            process_claim("")

    def test_whitespace_only_raises(self):
        with self.assertRaises(ClaimProcessingError):
            process_claim("   \t\n")

    def test_too_short_raises(self):
        with self.assertRaises(ClaimProcessingError):
            process_claim("Hi")

    def test_exactly_at_minimum_does_not_raise(self):
        # 10 non-whitespace characters — should not raise
        result = process_claim("A" * 10)
        self.assertIsNotNone(result)

    def test_too_long_raises(self):
        with self.assertRaises(ClaimProcessingError):
            process_claim("a" * 5_001)

    def test_exactly_at_maximum_does_not_raise(self):
        result = process_claim("a" * 5_000)
        self.assertIsNotNone(result)

    def test_non_string_raises(self):
        with self.assertRaises((ClaimProcessingError, AttributeError, TypeError)):
            process_claim(None)  # type: ignore

    def test_integer_raises(self):
        with self.assertRaises((ClaimProcessingError, AttributeError, TypeError)):
            process_claim(12345)  # type: ignore


# ===========================================================================
# 2 — Claim processing
# ===========================================================================


class TestClaimProcessing(unittest.TestCase):
    """Claim processor extracts and classifies assertions correctly."""

    def test_preserves_original_text(self):
        raw = "RBI says account will be blocked.\n"
        result = process_claim(raw)
        self.assertEqual(result.original_text, raw)

    def test_normalises_whitespace(self):
        raw = "RBI   has   announced  this."
        result = process_claim(raw)
        self.assertNotIn("   ", result.normalised_text)

    def test_produces_at_least_one_assertion(self):
        result = process_claim(
            "RBI has announced that all bank accounts will be blocked tonight."
        )
        self.assertGreater(len(result.assertions), 0)

    def test_rbi_claim_classified_as_regulatory(self):
        result = process_claim(
            "RBI has announced that all bank accounts will be blocked tonight."
        )
        types = [a.assertion_type for a in result.assertions]
        self.assertIn("regulatory", types)

    def test_payment_demand_detected(self):
        result = process_claim(
            "You must pay ₹500 to avoid account suspension immediately."
        )
        types = [a.assertion_type for a in result.assertions]
        self.assertTrue(
            any(t in ("payment_demand", "urgent_threat") for t in types),
            f"Expected payment or urgency type in {types}",
        )

    def test_deadline_detected(self):
        result = process_claim(
            "Your account will be closed tonight unless you act."
        )
        text_lower = " ".join(a.text.lower() for a in result.assertions)
        self.assertIn("tonight", text_lower)

    def test_otp_claim_classified_as_credential_request(self):
        result = process_claim(
            "Please share your OTP and bank password immediately to avoid suspension."
        )
        types = [a.assertion_type for a in result.assertions]
        self.assertIn("credential_request", types)

    def test_currency_entity_extracted(self):
        result = process_claim(
            "NPCI has imposed a mandatory fee of ₹1,000 on all UPI transactions."
        )
        all_entities = [e for a in result.assertions for e in a.entities]
        currency_entities = [e for e in all_entities if e.startswith("CURRENCY:")]
        self.assertTrue(len(currency_entities) > 0, f"No CURRENCY entity found in {all_entities}")

    def test_org_entity_extracted_for_rbi(self):
        result = process_claim(
            "The Reserve Bank of India (RBI) has issued a new circular for all banks."
        )
        all_entities = [e for a in result.assertions for e in a.entities]
        org_entities = [e for e in all_entities if e.startswith("ORG:")]
        self.assertTrue(len(org_entities) > 0, f"No ORG entity found in {all_entities}")

    def test_word_count_populated(self):
        result = process_claim(
            "SEBI has announced new trading rules for retail investors."
        )
        self.assertGreater(result.word_count, 0)

    def test_char_count_populated(self):
        result = process_claim(
            "SEBI has announced new trading rules for retail investors."
        )
        self.assertGreater(result.char_count, 0)

    def test_multiple_sentence_input_produces_multiple_assertions(self):
        result = process_claim(
            "RBI has frozen all savings accounts. You must pay ₹500 tonight. "
            "Failure to comply will result in legal action."
        )
        # At minimum we expect 2 assertions from 3 distinct sentences
        self.assertGreaterEqual(len(result.assertions), 2)

    def test_dicgc_coordinated_bank_categories_are_not_split_into_fragments(self):
        text = (
            "Under DICGC rules framed by RBI, bank deposits are insured up to "
            "₹5 lakh per depositor across commercial and cooperative banks."
        )
        result = process_claim(text)
        assertion_texts = [assertion.text for assertion in result.assertions]

        self.assertEqual(len(assertion_texts), 3)
        self.assertTrue(any("₹5 lakh per depositor" in text for text in assertion_texts))
        self.assertTrue(any("across commercial banks." in text for text in assertion_texts))
        self.assertTrue(any("across cooperative banks." in text for text in assertion_texts))
        self.assertFalse(any(text.endswith("commercial") for text in assertion_texts))
        self.assertFalse(any(text == "cooperative banks." for text in assertion_texts))

    def test_dicgc_single_category_keeps_limit_and_category_separate(self):
        result = process_claim(
            "Under DICGC rules, bank deposits are insured up to ₹5 lakh per depositor "
            "across commercial banks."
        )
        self.assertEqual(len(result.assertions), 2)
        self.assertTrue(any("₹5 lakh per depositor." in item.text for item in result.assertions))
        self.assertTrue(any("across commercial banks." in item.text for item in result.assertions))

    def test_abbreviation_and_currency_punctuation_do_not_split_assertions(self):
        result = process_claim(
            "DICGC insures deposits up to Rs. 5 lakh per depositor. RBI publishes FAQs."
        )
        self.assertTrue(any("Rs. 5 lakh per depositor." in item.text for item in result.assertions))
        self.assertTrue(any("RBI publishes FAQs." == item.text for item in result.assertions))

    def test_independent_conjoined_clauses_split_only_when_complete(self):
        result = process_claim(
            "RBI issued a circular and banks must follow the rules."
        )
        self.assertEqual(len(result.assertions), 2)
        self.assertIn("RBI issued a circular", result.assertions[0].text)
        self.assertIn("banks must follow", result.assertions[1].text)

    def test_commencement_and_headquarters_compound_splits_into_complete_assertions(self):
        result = process_claim(
            "RBI commenced operations on 1 April 1935 and is headquartered in Mumbai."
        )
        self.assertEqual(len(result.assertions), 2)
        self.assertEqual(
            result.assertions[0].text,
            "RBI commenced operations on 1 April 1935",
        )
        self.assertEqual(
            result.assertions[1].text,
            "RBI is headquartered in Mumbai.",
        )

    def test_devanagari_detected_as_hindi_hint(self):
        result = process_claim(
            "बैंक खाता आज रात बंद हो जाएगा जब तक आप ₹500 का भुगतान नहीं करते।"
        )
        self.assertEqual(result.language_hint, "hi")

    def test_english_text_detected_as_en_hint(self):
        result = process_claim(
            "HDFC Bank has announced new charges for debit card transactions."
        )
        self.assertEqual(result.language_hint, "en")


# ===========================================================================
# 3 — Evidence retrieval helpers (deterministic, no live network)
# ===========================================================================


class TestEvidenceRetrieverHelpers(unittest.TestCase):
    """Test deduplication and URL normalisation without network calls."""

    def _make_item(self, url: str) -> EvidenceItem:
        return EvidenceItem(url=url, retrieval_success=True)

    def test_deduplication_removes_exact_duplicates(self):
        items = [
            self._make_item("https://rbi.org.in/page"),
            self._make_item("https://rbi.org.in/page"),
            self._make_item("https://sebi.gov.in/news"),
        ]
        result = _deduplicate(items)
        self.assertEqual(len(result), 2)

    def test_deduplication_normalises_trailing_slash(self):
        items = [
            self._make_item("https://rbi.org.in/page/"),
            self._make_item("https://rbi.org.in/page"),
        ]
        result = _deduplicate(items)
        self.assertEqual(len(result), 1)

    def test_deduplication_preserves_order(self):
        urls = [
            "https://rbi.org.in/a",
            "https://sebi.gov.in/b",
            "https://npci.org.in/c",
        ]
        items = [self._make_item(u) for u in urls]
        result = _deduplicate(items)
        self.assertEqual([i.url for i in result], urls)

    def test_malformed_url_does_not_crash_normalise(self):
        try:
            normalised = _normalise_url("not_a_url")
        except Exception:
            self.fail("_normalise_url should not raise on malformed input")

    def test_noop_provider_returns_empty(self):
        provider = NoOpProvider()
        results = provider.search("test query")
        self.assertEqual(results, [])

    def test_noop_provider_id(self):
        provider = NoOpProvider()
        self.assertEqual(provider.provider_id, "none")


class TestEvidenceRetrieverMocked(unittest.TestCase):
    """Test evidence retriever with a mocked DuckDuckGo provider."""

    def _make_claim(self, text: str = "RBI has blocked accounts tonight.") -> ExtractedClaim:
        return ExtractedClaim(
            original_text=text,
            normalised_text=text,
            assertions=[Assertion(text=text, assertion_type="regulatory")],
            word_count=len(text.split()),
            char_count=len(text),
        )

    def test_retrieve_evidence_with_mock_items(self):
        """Provider returns items → bundle contains them."""
        from backend.services import evidence_retriever

        mock_item = EvidenceItem(
            url="https://rbi.org.in/test",
            title="RBI notice",
            excerpt="RBI has not issued such notice",
            retrieval_success=True,
        )

        with patch.object(
            evidence_retriever.DuckDuckGoProvider, "search", return_value=[mock_item]
        ):
            # Override provider list to use DuckDuckGo for this test only
            with patch.object(evidence_retriever, "_get_providers", return_value=[evidence_retriever.DuckDuckGoProvider()]):
                bundle = evidence_retriever.retrieve_evidence(self._make_claim())

        self.assertGreater(len(bundle.items), 0)

    def test_retrieve_evidence_with_provider_error(self):
        """Provider error item → bundle records error."""
        from backend.services import evidence_retriever

        error_item = EvidenceItem(
            url="about:error",
            retrieval_success=False,
            retrieval_error="Search request timed out.",
            source_quality=SourceQuality.REJECTED,
        )
        with patch.object(evidence_retriever.DuckDuckGoProvider, "search", return_value=[error_item]):
            with patch.object(evidence_retriever, "_get_providers", return_value=[evidence_retriever.DuckDuckGoProvider()]):
                bundle = evidence_retriever.retrieve_evidence(self._make_claim())

        self.assertIsNotNone(bundle.provider_error)

    def test_retrieve_evidence_no_provider_returns_empty_bundle(self):
        """NoOpProvider → empty items, no provider_error."""
        from backend.services import evidence_retriever

        with patch.object(evidence_retriever, "_get_providers", return_value=[NoOpProvider()]):
            bundle = evidence_retriever.retrieve_evidence(self._make_claim())

        self.assertEqual(bundle.items, [])
        self.assertIsNone(bundle.provider_error)
        self.assertEqual(bundle.search_provider_used, "none")


# ===========================================================================
# 4 — Source fetcher (SSRF protection and URL validation)
# ===========================================================================


class TestSourceFetcherValidation(unittest.TestCase):
    """Source fetcher rejects invalid and unsafe URLs before making requests."""

    def test_empty_url_fails(self):
        item = fetch_source("")
        self.assertFalse(item.retrieval_success)

    def test_ftp_scheme_rejected(self):
        item = fetch_source("ftp://example.com/file.txt")
        self.assertFalse(item.retrieval_success)
        self.assertIn("Scheme", item.retrieval_error or "")

    def test_cloud_metadata_rejected(self):
        item = fetch_source("http://169.254.169.254/latest/meta-data")
        self.assertFalse(item.retrieval_success)

    def test_malformed_port_and_embedded_credentials_are_rejected(self):
        for url in (
            "https://example.com:99999/path",
            "https://user:pass@example.com/path",
            "https://example.com:not-a-port/path",
        ):
            with self.subTest(url=url):
                item = fetch_source(url)
                self.assertFalse(item.retrieval_success)

    def test_dns_resolution_rejects_private_address_without_network_request(self):
        unsafe_ips = (
            "127.0.0.1",
            "10.0.0.7",
            "169.254.1.10",
            "100.64.0.1",
            "192.0.2.1",
            "224.0.0.1",
            "::1",
            "fe80::1",
        )
        for address in unsafe_ips:
            is_ipv6 = ":" in address
            family = socket.AF_INET6 if is_ipv6 else socket.AF_INET
            sockaddr = (address, 0, 0, 0) if is_ipv6 else (address, 0)
            fake_results = [(family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr)]
            with self.subTest(address=address), patch(
                "backend.services.source_fetcher.socket.getaddrinfo",
                return_value=fake_results,
            ):
                with self.assertRaises(_SSRFBlockedError):
                    _resolve_and_check("rebind.example")

    def test_dns_resolution_rejects_mixed_public_and_private_answers(self):
        fake_results = [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("10.0.0.7", 0)),
        ]
        with patch("backend.services.source_fetcher.socket.getaddrinfo", return_value=fake_results):
            with self.assertRaises(_SSRFBlockedError):
                _resolve_and_check("mixed.example")

    def test_dns_resolution_pins_public_ip_for_connection(self):
        fake_results = [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", 0))
        ]
        with patch("backend.services.source_fetcher.socket.getaddrinfo", return_value=fake_results):
            addresses = _resolve_and_check("safe.example")
        self.assertEqual(addresses, ("8.8.8.8",))

        with patch("httpcore.SyncBackend.connect_tcp", autospec=True, return_value=object()) as connect:
            backend = _PinnedNetworkBackend("safe.example", addresses, time.monotonic() + 5)
            backend.connect_tcp("safe.example", 443)
        self.assertEqual(connect.call_args.args[1], "8.8.8.8")

    def test_dns_resolution_rejects_no_addresses(self):
        with patch("backend.services.source_fetcher.socket.getaddrinfo", return_value=[]):
            with self.assertRaises(_SSRFBlockedError):
                _resolve_and_check("empty.example")

    def test_localhost_blocked(self):
        item = fetch_source("http://localhost/admin")
        self.assertFalse(item.retrieval_success)
        self.assertIn("SSRF", item.retrieval_error or "")

    def test_loopback_ip_blocked(self):
        item = fetch_source("http://127.0.0.1:8080/secret")
        self.assertFalse(item.retrieval_success)
        self.assertIn("SSRF", item.retrieval_error or "")

    def test_rbi_url_passes_validation(self):
        """URL passes validation (network fetch is mocked to avoid real requests)."""
        with patch("backend.services.source_fetcher._do_fetch") as mock_fetch:
            mock_fetch.return_value = EvidenceItem(
                url="https://rbi.org.in/test",
                title="RBI page",
                excerpt="Official RBI content",
                retrieval_success=True,
                source_quality=SourceQuality.AUTHORITATIVE,
            )
            result = fetch_source("https://rbi.org.in/test-page")
        self.assertTrue(result.retrieval_success)

    def test_fetches_readable_page_text(self):
        response = MagicMock()
        response.status_code = 200
        response.url = "https://rbi.org.in/test-page"
        response.headers = {"content-type": "text/html; charset=utf-8"}
        response.iter_bytes.return_value = [
            b"<html><head><title>RBI</title></head><body><main><p>Official page text.</p></main></body></html>"
        ]
        response.reason_phrase = "OK"
        response_context = MagicMock()
        response_context.__enter__.return_value = response
        client_mock = MagicMock()
        client_mock.__enter__.return_value = client_mock
        client_mock.stream.return_value = response_context

        with patch("backend.services.source_fetcher._resolve_and_check"), patch(
            "backend.services.source_fetcher.httpx.Client", return_value=client_mock
        ):
            item = fetch_source("https://rbi.org.in/test-page")

        self.assertTrue(item.retrieval_success)
        self.assertEqual(item.title, "RBI")
        self.assertIn("Official page text.", item.excerpt)
        self.assertEqual(item.evidence_origin, "fetched_page")

    def test_redirect_to_private_ip_is_rejected_before_request(self):
        response = MagicMock()
        response.status_code = 302
        response.url = "https://rbi.org.in/test-page"
        response.headers = {"location": "http://127.0.0.1/admin"}
        response_context = MagicMock()
        response_context.__enter__.return_value = response
        client_mock = MagicMock()
        client_mock.__enter__.return_value = client_mock
        client_mock.stream.return_value = response_context

        with patch(
            "backend.services.source_fetcher._resolve_and_check",
            side_effect=[None, _SSRFBlockedError("loopback address")],
        ), patch(
            "backend.services.source_fetcher.httpx.Client", return_value=client_mock
        ):
            item = fetch_source("https://rbi.org.in/test-page")

        self.assertFalse(item.retrieval_success)
        self.assertIn("SSRF", item.retrieval_error or "")
        client_mock.stream.assert_called_once()

    def test_redirect_count_is_bounded(self):
        response = MagicMock()
        response.status_code = 302
        response.url = "https://rbi.org.in/test-page"
        response.headers = {"location": "/again"}
        response_context = MagicMock()
        response_context.__enter__.return_value = response
        client_mock = MagicMock()
        client_mock.__enter__.return_value = client_mock
        client_mock.stream.return_value = response_context

        with patch(
            "backend.services.source_fetcher._resolve_and_check",
            return_value=("8.8.8.8",),
        ), patch(
            "backend.services.source_fetcher.httpx.Client", return_value=client_mock
        ):
            item = fetch_source("https://rbi.org.in/test-page")

        self.assertFalse(item.retrieval_success)
        self.assertIn("Too many redirects", item.retrieval_error or "")
        self.assertEqual(client_mock.stream.call_count, 6)

    def test_source_fetch_timeout_is_reported_as_retrieval_failure(self):
        with patch(
            "backend.services.source_fetcher._do_fetch",
            side_effect=httpx.ReadTimeout("test timeout"),
        ):
            item = fetch_source("https://rbi.org.in/test-page")
        self.assertFalse(item.retrieval_success)
        self.assertIn("timed out", item.retrieval_error or "")

    def test_http_error_is_reported_as_fetch_failure(self):
        response = MagicMock()
        response.status_code = 503
        response.reason_phrase = "Service Unavailable"
        response.url = "https://rbi.org.in/test-page"
        response.headers = {"content-type": "text/html"}
        response_context = MagicMock()
        response_context.__enter__.return_value = response
        client_mock = MagicMock()
        client_mock.__enter__.return_value = client_mock
        client_mock.stream.return_value = response_context

        with patch("backend.services.source_fetcher._resolve_and_check"), patch(
            "backend.services.source_fetcher.httpx.Client", return_value=client_mock
        ):
            item = fetch_source("https://rbi.org.in/test-page")

        self.assertFalse(item.retrieval_success)
        self.assertIn("HTTP 503", item.retrieval_error or "")

    def test_classify_authoritative_domain(self):
        quality = classify_source_quality("https://rbi.org.in/circulars")
        self.assertEqual(quality, SourceQuality.AUTHORITATIVE)

    def test_classify_reputable_domain(self):
        quality = classify_source_quality("https://thehindu.com/news/article")
        self.assertEqual(quality, SourceQuality.REPUTABLE)

    def test_classify_unknown_domain(self):
        quality = classify_source_quality("https://randomsite12345.com/news")
        self.assertEqual(quality, SourceQuality.UNKNOWN)

    def test_classify_www_prefix_stripped_correctly(self):
        """www. prefix must be removed correctly (removeprefix, not lstrip)."""
        quality_with_www = classify_source_quality("https://www.rbi.org.in/circulars")
        self.assertEqual(quality_with_www, SourceQuality.AUTHORITATIVE)
        # Edge case: domain starting with 'w' chars that lstrip would wrongly strip
        quality_web = classify_source_quality("https://www.website.com/page")
        self.assertEqual(quality_web, SourceQuality.UNKNOWN)

    def test_classify_pib_gov_in_authoritative(self):
        """PIB (Press Information Bureau) must be classified as AUTHORITATIVE."""
        quality = classify_source_quality("https://pib.gov.in/factcheck/rbi-scam")
        self.assertEqual(quality, SourceQuality.AUTHORITATIVE)

    def test_classify_subdomain_of_trusted_domain(self):
        """Subdomains of trusted domains should inherit classification."""
        quality = classify_source_quality("https://press.rbi.org.in/releases/2026")
        self.assertEqual(quality, SourceQuality.AUTHORITATIVE)

    def test_classify_sebi_authoritative(self):
        quality = classify_source_quality("https://sebi.gov.in/notices")
        self.assertEqual(quality, SourceQuality.AUTHORITATIVE)

    def test_classify_dicgc_authoritative(self):
        quality = classify_source_quality("https://www.dicgc.org.in/guide-to-deposit-insurance")
        self.assertEqual(quality, SourceQuality.AUTHORITATIVE)


class TestFetchedPageEvidence(unittest.TestCase):
    def test_failed_fetch_retains_snippet_and_discloses_failure(self):
        claim = process_claim("The RBI commenced operations on April 1, 1935.")
        item = EvidenceItem(
            url="https://rbi.org.in/official-page",
            title="RBI page",
            excerpt="The RBI commenced operations on April 1, 1935.",
            source_quality=SourceQuality.AUTHORITATIVE,
            retrieval_success=True,
            evidence_origin="search_snippet",
        )
        failed_page = EvidenceItem(
            url=item.url,
            retrieval_success=False,
            retrieval_error="Request timed out.",
        )

        with patch("backend.services.evidence_retriever.fetch_source", return_value=failed_page):
            _apply_fetched_page(item, timeout=1)

        self.assertEqual(item.excerpt, "The RBI commenced operations on April 1, 1935.")
        self.assertEqual(item.evidence_origin, "search_snippet")
        self.assertEqual(item.page_fetch_error, "Request timed out.")
        verification = verify_claims(claim, EvidenceBundle(items=[item]))
        self.assertEqual(verification.verdict, Verdict.UNVERIFIED)
        self.assertEqual(verification.supporting_evidence, [])

    def test_fetched_page_supersedes_conflicting_search_snippet(self):
        claim = process_claim("The RBI commenced operations on April 1, 1935.")
        item = EvidenceItem(
            url="https://rbi.org.in/official-page",
            title="RBI history",
            excerpt="The RBI commenced operations on April 1, 1935.",
            source_quality=SourceQuality.AUTHORITATIVE,
            retrieval_success=True,
            evidence_origin="search_snippet",
        )
        page = EvidenceItem(
            url=item.url,
            title="RBI history",
            excerpt="The Reserve Bank of India commenced operations on April 2, 1935.",
            source_quality=SourceQuality.AUTHORITATIVE,
            retrieval_success=True,
            evidence_origin="fetched_page",
        )

        with patch("backend.services.evidence_retriever.fetch_source", return_value=page):
            _apply_fetched_page(item, timeout=1)

        result = verify_claims(claim, EvidenceBundle(items=[item]))
        self.assertEqual(item.search_snippet, "The RBI commenced operations on April 1, 1935.")
        self.assertEqual(item.evidence_origin, "fetched_page")
        self.assertEqual(result.verdict, Verdict.FALSE)


# ===========================================================================
# 5 — Verdict engine
# ===========================================================================


def _make_claim(text: str = "RBI has blocked all accounts tonight.") -> ExtractedClaim:
    return ExtractedClaim(
        original_text=text,
        normalised_text=text,
        assertions=[Assertion(text=text, assertion_type="regulatory")],
        word_count=len(text.split()),
        char_count=len(text),
    )


def _make_bundle(items: list[EvidenceItem], provider_error: str | None = None) -> EvidenceBundle:
    return EvidenceBundle(
        items=items,
        search_provider_used="mock",
        provider_error=provider_error,
    )


class TestVerdictEngine(unittest.TestCase):
    """Verdict engine produces correct verdicts for various evidence scenarios."""

    def test_empty_evidence_returns_unverified(self):
        result = verify_claims(_make_claim(), _make_bundle([]))
        self.assertEqual(result.verdict, Verdict.UNVERIFIED)

    def test_provider_error_returns_error(self):
        result = verify_claims(_make_claim(), _make_bundle([], provider_error="timeout"))
        self.assertEqual(result.verdict, Verdict.ERROR)

    def test_supporting_evidence_returns_true(self):
        items = [
            EvidenceItem(
                url="https://rbi.org.in/a",
                title="RBI confirms all accounts blocked announcement",
                excerpt=(
                    "According to the RBI official press release, the organisation confirmed "
                    "that all accounts will be blocked tonight under the new circular."
                ),
                source_quality=SourceQuality.AUTHORITATIVE,
                retrieval_success=True,
            )
        ]
        result = verify_claims(_make_claim(), _make_bundle(items))
        self.assertEqual(result.verdict, Verdict.TRUE)

    def test_contradicting_evidence_returns_false(self):
        items = [
            EvidenceItem(
                url="https://rbi.org.in/clarification",
                title="RBI clarification on fake message",
                excerpt=(
                    "This is fake news. RBI has no such circular. The viral message is a hoax "
                    "and complete misinformation. RBI has not issued any notice to block accounts."
                ),
                source_quality=SourceQuality.AUTHORITATIVE,
                retrieval_success=True,
            )
        ]
        result = verify_claims(_make_claim(), _make_bundle(items))
        self.assertEqual(result.verdict, Verdict.FALSE)

    def test_conflicting_evidence_returns_unverified(self):
        items = [
            EvidenceItem(
                url="https://rbi.org.in/confirm",
                title="RBI confirms announcement",
                excerpt=(
                    "RBI official press release confirmed that all bank accounts will be blocked "
                    "tonight under the new circular."
                ),
                source_quality=SourceQuality.AUTHORITATIVE,
                retrieval_success=True,
            ),
            EvidenceItem(
                url="https://sebi.gov.in/clarify",
                title="Clarification on fake message",
                excerpt=(
                    "This viral message is fake news and misinformation. "
                    "RBI has not issued any notice to block accounts."
                ),
                source_quality=SourceQuality.AUTHORITATIVE,
                retrieval_success=True,
            ),
        ]
        result = verify_claims(_make_claim(), _make_bundle(items))
        self.assertEqual(result.verdict, Verdict.UNVERIFIED)
        self.assertIn("conflicts", result.explanation)

    def test_failed_retrieval_items_excluded(self):
        items = [
            EvidenceItem(
                url="https://rbi.org.in/page",
                retrieval_success=False,
                retrieval_error="HTTP 403",
            )
        ]
        result = verify_claims(_make_claim(), _make_bundle(items))
        # Failed items → no usable evidence → UNVERIFIED
        self.assertEqual(result.verdict, Verdict.UNVERIFIED)

    def test_no_assertions_returns_unverified(self):
        claim = ExtractedClaim(
            original_text="X" * 20,
            normalised_text="X" * 20,
            assertions=[],
        )
        items = [EvidenceItem(url="https://rbi.org.in", excerpt="Some content", retrieval_success=True)]
        result = verify_claims(claim, _make_bundle(items))
        self.assertEqual(result.verdict, Verdict.UNVERIFIED)

    def test_supporting_urls_populated_on_true(self):
        items = [
            EvidenceItem(
                url="https://rbi.org.in/announcement",
                title="RBI official announcement confirmed",
                excerpt="RBI confirmed the official press release for accounts blocked tonight.",
                retrieval_success=True,
            )
        ]
        result = verify_claims(_make_claim(), _make_bundle(items))
        if result.verdict == Verdict.TRUE:
            self.assertTrue(len(result.supporting_evidence) > 0)

    def test_limitations_populated(self):
        result = verify_claims(_make_claim(), _make_bundle([]))
        self.assertTrue(len(result.limitations) > 0)

    def test_absence_of_evidence_not_falsifying(self):
        """Empty evidence must NOT produce verdict=FALSE."""
        result = verify_claims(_make_claim(), _make_bundle([]))
        self.assertNotEqual(result.verdict, Verdict.FALSE)


# ===========================================================================
# 6 — Scam detector
# ===========================================================================


class TestScamDetector(unittest.TestCase):
    """Scam detector assigns correct risk categories and captures indicators."""

    def test_high_risk_rbi_payment_scam(self):
        text = (
            "RBI has announced all accounts will be blocked tonight. "
            "Pay Rs. 500 immediately via UPI. "
            "Share your OTP with our agent."
        )
        result = assess_scam_risk(text)
        self.assertEqual(result.category, RiskCategory.HIGH)
        self.assertGreaterEqual(result.score, 60)

    def test_payment_demand_detected(self):
        result = assess_scam_risk(
            "You must pay ₹1000 mandatory fee to activate your account."
        )
        types = [i.indicator_type for i in result.indicators]
        self.assertIn("payment_demand", types)

    def test_otp_request_detected(self):
        result = assess_scam_risk(
            "Please share your OTP and bank PIN to verify your identity."
        )
        types = [i.indicator_type for i in result.indicators]
        self.assertIn("credential_request", types)

    def test_suspicious_link_detected(self):
        result = assess_scam_risk(
            "Click here to verify: http://bank-update.xyz/login"
        )
        types = [i.indicator_type for i in result.indicators]
        self.assertIn("suspicious_link", types)

    def test_harmless_bank_closure_message(self):
        result = assess_scam_risk(
            "The bank branch will remain closed on Monday for a public holiday."
        )
        self.assertEqual(result.category, RiskCategory.LOW)
        self.assertEqual(len(result.indicators), 0)

    def test_impersonation_detected(self):
        result = assess_scam_risk(
            "This message is from the Reserve Bank of India regarding your account."
        )
        types = [i.indicator_type for i in result.indicators]
        self.assertIn("impersonation", types)

    def test_educational_rbi_reference_is_not_impersonation(self):
        result = assess_scam_risk(
            "Under DICGC rules framed by RBI, deposits are insured up to ₹5 lakh per depositor."
        )
        self.assertEqual(result.category, RiskCategory.LOW)
        self.assertNotIn("impersonation", [item.indicator_type for item in result.indicators])

    def test_impersonation_with_payment_threat_remains_high_risk(self):
        result = assess_scam_risk(
            "This message is from RBI. Pay ₹500 tonight or your bank account will be blocked."
        )
        indicator_types = [item.indicator_type for item in result.indicators]
        self.assertIn("impersonation", indicator_types)
        self.assertIn("payment_demand", indicator_types)
        self.assertIn("urgent_threat", indicator_types)
        self.assertEqual(result.category, RiskCategory.HIGH)

    def test_heuristic_score_is_not_a_probability(self):
        result = assess_scam_risk(
            "This score is generated by deterministic rules."
        )
        self.assertIn("not", result.disclaimer.lower())
        self.assertEqual(result.medium_threshold, MEDIUM_RISK_THRESHOLD)
        self.assertEqual(result.high_threshold, HIGH_RISK_THRESHOLD)

    def test_risk_categories_match_exact_backend_threshold_boundaries(self):
        self.assertEqual(_score_to_category(29), RiskCategory.LOW)
        self.assertEqual(_score_to_category(30), RiskCategory.MEDIUM)
        self.assertEqual(_score_to_category(59), RiskCategory.MEDIUM)
        self.assertEqual(_score_to_category(60), RiskCategory.HIGH)

    def test_app_install_detected(self):
        result = assess_scam_risk(
            "Download and install this APK immediately to update your banking app."
        )
        types = [i.indicator_type for i in result.indicators]
        self.assertIn("app_install", types)

    def test_multiple_indicators_accumulate_score(self):
        text = (
            "URGENT: RBI has blocked your account. "
            "Pay ₹2000 and share OTP. "
            "Download our app at http://fraud.xyz/app"
        )
        result = assess_scam_risk(text)
        self.assertGreater(result.score, 40)
        self.assertGreater(len(result.indicators), 2)

    def test_score_capped_at_100(self):
        text = (
            "Urgent RBI announcement! Account blocked tonight. "
            "Pay ₹500. Share OTP and PIN. "
            "Transfer money to account. Install app. "
            "Click http://scam.xyz. You are selected. "
            "Guaranteed 100% return. Act now or arrest."
        )
        result = assess_scam_risk(text)
        self.assertLessEqual(result.score, 100)

    def test_score_range_valid(self):
        result = assess_scam_risk("Normal message about bank interest rates.")
        self.assertGreaterEqual(result.score, 0)
        self.assertLessEqual(result.score, 100)

    def test_disclaimer_always_present(self):
        result = assess_scam_risk("Any message here.")
        self.assertTrue(len(result.disclaimer) > 0)

    def test_factual_verdict_not_influenced_by_scam_score(self):
        """Scam assessment must be independent of verdict engine."""
        # A high scam score should not change the verdict engine result
        claim = _make_claim("RBI has announced something.")
        bundle = _make_bundle([])
        verdict_result = verify_claims(claim, bundle)

        scam_result = assess_scam_risk("RBI has announced something.")

        # Verdict should remain UNVERIFIED despite high scam score
        self.assertEqual(verdict_result.verdict, Verdict.UNVERIFIED)
        # Both results should be independent objects
        self.assertIsInstance(scam_result.score, int)
        self.assertIsInstance(verdict_result.verdict, Verdict)


# ===========================================================================
# 7 — API integration
# ===========================================================================


class TestAPIHealth(unittest.TestCase):
    """Phase 1 health endpoint is preserved and unchanged."""

    def test_health_returns_200(self):
        r = client.get("/api/health")
        self.assertEqual(r.status_code, 200)

    def test_health_response_fields(self):
        r = client.get("/api/health")
        data = r.json()
        for field in ("status", "app_name", "version", "environment"):
            self.assertIn(field, data)

    def test_health_status_ok(self):
        r = client.get("/api/health")
        self.assertEqual(r.json()["status"], "ok")


class TestAPIAnalyze(unittest.TestCase):
    """POST /api/analyze integration tests (no live network)."""

    _RBI_CLAIM = (
        "RBI has announced that all bank accounts will be blocked tonight "
        "unless customers pay ₹500 for mandatory verification."
    )

    def test_valid_request_returns_200(self):
        r = client.post("/api/analyze", json={"text": self._RBI_CLAIM})
        self.assertEqual(r.status_code, 200)

    def test_response_has_required_fields(self):
        r = client.post("/api/analyze", json={"text": self._RBI_CLAIM})
        data = r.json()
        for field in ("request_id", "status", "original_text", "claims",
                      "verdict", "explanation", "evidence", "scam_assessment", "limitations"):
            self.assertIn(field, data, f"Missing field: {field}")

    def test_request_id_is_string(self):
        r = client.post("/api/analyze", json={"text": self._RBI_CLAIM})
        self.assertIsInstance(r.json()["request_id"], str)
        self.assertTrue(len(r.json()["request_id"]) > 0)

    def test_original_text_preserved(self):
        r = client.post("/api/analyze", json={"text": self._RBI_CLAIM})
        self.assertEqual(r.json()["original_text"], self._RBI_CLAIM)

    def test_verdict_is_valid_value(self):
        r = client.post("/api/analyze", json={"text": self._RBI_CLAIM})
        self.assertIn(r.json()["verdict"], {"TRUE", "FALSE", "PARTIALLY_TRUE", "UNVERIFIED", "ERROR"})

    def test_scam_assessment_structure(self):
        r = client.post("/api/analyze", json={"text": self._RBI_CLAIM})
        sa = r.json()["scam_assessment"]
        self.assertIn("score", sa)
        self.assertIn("category", sa)
        self.assertIn("indicators", sa)
        self.assertIn("disclaimer", sa)

    def test_scam_score_range(self):
        r = client.post("/api/analyze", json={"text": self._RBI_CLAIM})
        score = r.json()["scam_assessment"]["score"]
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

    def test_rbi_scam_claim_gets_high_scam_score(self):
        r = client.post("/api/analyze", json={"text": self._RBI_CLAIM})
        data = r.json()
        self.assertEqual(data["scam_assessment"]["category"], "HIGH")

    def test_claims_list_populated(self):
        r = client.post("/api/analyze", json={"text": self._RBI_CLAIM})
        self.assertIsInstance(r.json()["claims"], list)
        self.assertGreater(len(r.json()["claims"]), 0)

    def test_each_claim_has_text_and_type(self):
        r = client.post("/api/analyze", json={"text": self._RBI_CLAIM})
        for claim in r.json()["claims"]:
            self.assertIn("text", claim)
            self.assertIn("assertion_type", claim)

    def test_verdict_and_scam_are_independent(self):
        """Scam category does not determine verdict category."""
        r = client.post("/api/analyze", json={"text": self._RBI_CLAIM})
        data = r.json()
        # Both fields should be separately present with independent values
        self.assertIn("verdict", data)
        self.assertIn("category", data["scam_assessment"])

    def test_empty_text_returns_422(self):
        r = client.post("/api/analyze", json={"text": ""})
        self.assertEqual(r.status_code, 422)

    def test_whitespace_only_returns_422(self):
        r = client.post("/api/analyze", json={"text": "   "})
        self.assertEqual(r.status_code, 422)

    def test_missing_text_field_returns_422(self):
        r = client.post("/api/analyze", json={})
        self.assertEqual(r.status_code, 422)

    def test_text_too_long_returns_422(self):
        r = client.post("/api/analyze", json={"text": "a" * 5_001})
        self.assertEqual(r.status_code, 422)

    def test_extra_fields_ignored(self):
        r = client.post("/api/analyze", json={"text": self._RBI_CLAIM, "unknown_field": "xyz"})
        self.assertEqual(r.status_code, 200)

    def test_harmless_message_lower_scam_score(self):
        r = client.post(
            "/api/analyze",
            json={"text": "The bank branch will be closed on Monday for a national holiday."},
        )
        data = r.json()
        self.assertEqual(data["scam_assessment"]["category"], "LOW")

    def test_status_completed_on_success(self):
        r = client.post("/api/analyze", json={"text": self._RBI_CLAIM})
        self.assertEqual(r.json()["status"], "completed")

    def test_limitations_list_present(self):
        r = client.post("/api/analyze", json={"text": self._RBI_CLAIM})
        self.assertIsInstance(r.json()["limitations"], list)

    def test_evidence_list_is_list(self):
        r = client.post("/api/analyze", json={"text": self._RBI_CLAIM})
        self.assertIsInstance(r.json()["evidence"], list)

    def test_no_live_network_calls(self):
        """With SEARCH_PROVIDER_ORDER=none, provider and source fetch stay offline."""
        with patch("backend.services.evidence_retriever.httpx.post") as mock_post, patch(
            "backend.services.source_fetcher.httpx.Client"
        ) as mock_source_client:
            r = client.post("/api/analyze", json={"text": self._RBI_CLAIM})
        mock_post.assert_not_called()
        mock_source_client.assert_not_called()
        self.assertEqual(r.status_code, 200)


# ===========================================================================
# pytest-style standalone test functions (auto-discovered by pytest)
# ===========================================================================

def test_pytest_health_returns_200():
    r = client.get("/api/health")
    assert r.status_code == 200


def test_pytest_health_status_ok():
    r = client.get("/api/health")
    assert r.json()["status"] == "ok"


def test_pytest_analyze_valid_request():
    r = client.post("/api/analyze", json={"text": "RBI has announced account suspension tonight unless you pay Rs. 500."})
    assert r.status_code == 200
    data = r.json()
    assert "request_id" in data
    assert data["verdict"] in {"TRUE", "FALSE", "PARTIALLY_TRUE", "UNVERIFIED", "ERROR"}
    assert 0 <= data["scam_assessment"]["score"] <= 100


def test_pytest_analyze_empty_text_422():
    r = client.post("/api/analyze", json={"text": ""})
    assert r.status_code == 422


def test_pytest_analyze_too_long_422():
    r = client.post("/api/analyze", json={"text": "x" * 5_001})
    assert r.status_code == 422


def test_pytest_scam_rbi_high_risk():
    text = "RBI says accounts blocked tonight. Pay Rs. 500. Share OTP."
    result = assess_scam_risk(text)
    assert result.score >= 60
    assert result.category == RiskCategory.HIGH


def test_pytest_scam_harmless_low_risk():
    result = assess_scam_risk("Bank branch closed on Monday for national holiday.")
    assert result.category == RiskCategory.LOW


def test_pytest_claim_rbi_regulatory_type():
    result = process_claim("RBI has issued a circular regarding bank account verification.")
    types = [a.assertion_type for a in result.assertions]
    assert "regulatory" in types


def test_pytest_verdict_empty_evidence_unverified():
    claim = _make_claim("SEBI has suspended trading tonight.")
    bundle = _make_bundle([])
    result = verify_claims(claim, bundle)
    assert result.verdict == Verdict.UNVERIFIED


def test_pytest_ssrf_localhost_blocked():
    item = fetch_source("http://localhost/admin")
    assert not item.retrieval_success
    assert "SSRF" in (item.retrieval_error or "")


def test_pytest_deduplication_works():
    items = [
        EvidenceItem(url="https://rbi.org.in/page", retrieval_success=True),
        EvidenceItem(url="https://rbi.org.in/page/", retrieval_success=True),
        EvidenceItem(url="https://sebi.gov.in/news", retrieval_success=True),
    ]
    result = _deduplicate(items)
    assert len(result) == 2


# ===========================================================================
# 8 — Multi-Provider Evidence Retrieval (Tavily, Serper, DuckDuckGo, Fallback)
# ===========================================================================


class TestMultiProviderEvidenceRetriever(unittest.TestCase):
    """Test multi-provider architecture, controlled fallback, error isolation,
    provider order, and deduplication without live external API calls.
    """

    def _make_claim(self, text: str = "RBI has announced that bank accounts will be blocked tonight.") -> ExtractedClaim:
        return ExtractedClaim(
            original_text=text,
            normalised_text=text,
            assertions=[Assertion(text=text, assertion_type="regulatory")],
            word_count=len(text.split()),
            char_count=len(text),
        )

    def test_irrelevant_first_provider_does_not_prevent_relevant_fallback(self):
        claim = process_claim("The RBI commenced operations on April 1, 1935.")
        irrelevant = EvidenceItem(
            url="https://rbi.org.in/about/history",
            title="Reserve Bank of India",
            excerpt="The Reserve Bank of India was established in 1935.",
            source_quality=SourceQuality.AUTHORITATIVE,
            retrieval_success=True,
            provider="tavily",
        )
        relevant = EvidenceItem(
            url="https://rbi.org.in/about/commencement",
            title="Commencement of operations",
            excerpt="The Reserve Bank of India commenced operations on 1 April 1935.",
            source_quality=SourceQuality.AUTHORITATIVE,
            retrieval_success=True,
            provider="serper",
        )
        tavily = TavilyProvider(api_key="key")
        serper = SerperProvider(api_key="key")

        with patch.object(tavily, "search", return_value=[irrelevant]), patch.object(
            serper, "search", return_value=[relevant]
        ):
            bundle = retrieve_evidence(
                claim,
                providers=[tavily, serper],
                corroborate=False,
                fetch_pages=False,
            )

        self.assertEqual(bundle.providers_attempted, ["tavily", "serper"])
        self.assertTrue(any(item.url == relevant.url for item in bundle.items))

    # 1. Tavily successful responses
    def test_tavily_successful_response(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "query": "RBI bank accounts blocked",
            "results": [
                {
                    "title": "RBI Clarification on Account Rumours",
                    "url": "https://rbi.org.in/press/123",
                    "content": "The Reserve Bank of India has clarified that no accounts will be blocked tonight.",
                    "score": 0.96,
                    "published_date": "2026-10-20",
                }
            ],
        }

        provider = TavilyProvider(api_key="tvly-mock-key")
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            items = provider.search("RBI bank accounts blocked", max_results=3)

        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.url, "https://rbi.org.in/press/123")
        self.assertEqual(item.title, "RBI Clarification on Account Rumours")
        self.assertEqual(item.provider, "tavily")
        self.assertEqual(item.source_quality, SourceQuality.AUTHORITATIVE)
        self.assertEqual(item.published_date, "2026-10-20")
        self.assertTrue(item.retrieval_success)
        mock_post.assert_called_once()
        self.assertEqual(mock_post.call_args[1]["json"]["api_key"], "tvly-mock-key")

    # 2. Serper successful responses
    def test_serper_successful_response(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "searchParameters": {"q": "SEBI verification fee", "gl": "in", "hl": "en"},
            "organic": [
                {
                    "title": "SEBI Public Notice on Verification Fees",
                    "link": "https://sebi.gov.in/notices/456",
                    "snippet": "SEBI warns investors against fake notices demanding verification fees.",
                    "date": "20 Oct 2026",
                    "position": 1,
                }
            ],
        }

        provider = SerperProvider(api_key="serper-mock-key")
        with patch("httpx.post", return_value=mock_resp) as mock_post:
            items = provider.search("SEBI verification fee", max_results=3)

        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.url, "https://sebi.gov.in/notices/456")
        self.assertEqual(item.title, "SEBI Public Notice on Verification Fees")
        self.assertEqual(item.provider, "serper")
        self.assertEqual(item.source_quality, SourceQuality.AUTHORITATIVE)
        self.assertEqual(item.published_date, "20 Oct 2026")
        self.assertTrue(item.retrieval_success)
        mock_post.assert_called_once()
        self.assertEqual(mock_post.call_args[1]["headers"]["X-API-KEY"], "serper-mock-key")

    # 3. Missing API keys
    def test_missing_api_keys_auto_disables_providers(self):
        tavily = TavilyProvider(api_key=None)
        self.assertFalse(tavily.is_available)
        t_res = tavily.search("test")
        self.assertEqual(len(t_res), 1)
        self.assertFalse(t_res[0].retrieval_success)
        self.assertIn("not configured", t_res[0].retrieval_error or "")

        serper = SerperProvider(api_key="")
        self.assertFalse(serper.is_available)
        s_res = serper.search("test")
        self.assertEqual(len(s_res), 1)
        self.assertFalse(s_res[0].retrieval_success)
        self.assertIn("not configured", s_res[0].retrieval_error or "")

    # 4. Invalid API responses (non-JSON, HTTP 401, HTTP 403, HTTP 500)
    def test_invalid_api_responses_handled_gracefully(self):
        # Test non-JSON response
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.side_effect = ValueError("Invalid JSON")
        tavily = TavilyProvider(api_key="test-key")
        with patch("httpx.post", return_value=mock_resp):
            items = tavily.search("query")
        self.assertEqual(len(items), 1)
        self.assertFalse(items[0].retrieval_success)
        self.assertIn("invalid JSON", items[0].retrieval_error or "")

        # Test HTTP 401 Unauthorized
        mock_401 = MagicMock()
        mock_401.status_code = 401
        with patch("httpx.post", return_value=mock_401):
            items_401 = tavily.search("query")
        self.assertEqual(len(items_401), 1)
        self.assertFalse(items_401[0].retrieval_success)
        self.assertIn("authentication failed", items_401[0].retrieval_error or "")

        # Test HTTP 500 Server Error for Serper
        mock_500 = MagicMock()
        mock_500.status_code = 500
        serper = SerperProvider(api_key="test-key")
        with patch("httpx.post", return_value=mock_500):
            items_500 = serper.search("query")
        self.assertEqual(len(items_500), 1)
        self.assertFalse(items_500[0].retrieval_success)
        self.assertIn("HTTP 500", items_500[0].retrieval_error or "")

    # 5. Timeouts and rate limits
    def test_timeouts_and_rate_limits(self):
        import httpx

        # Timeout on Tavily
        tavily = TavilyProvider(api_key="key")
        with patch("httpx.post", side_effect=httpx.TimeoutException("timed out")):
            items = tavily.search("query")
        self.assertEqual(len(items), 1)
        self.assertFalse(items[0].retrieval_success)
        self.assertIn("timed out", items[0].retrieval_error or "")

        # Rate limit (HTTP 429) on Serper
        serper = SerperProvider(api_key="key")
        mock_429 = MagicMock()
        mock_429.status_code = 429
        with patch("httpx.post", return_value=mock_429):
            items_429 = serper.search("query")
        self.assertEqual(len(items_429), 1)
        self.assertFalse(items_429[0].retrieval_success)
        self.assertIn("rate limit exceeded", items_429[0].retrieval_error or "")

    # 6. Provider fallback: Tavily fails -> Serper succeeds
    def test_provider_fallback_tavily_to_serper(self):
        tavily = TavilyProvider(api_key="key")
        serper = SerperProvider(api_key="key")

        with patch.object(
            tavily,
            "search",
            return_value=[
                EvidenceItem(url="about:error", retrieval_success=False, retrieval_error="Tavily timed out.", provider="tavily")
            ],
        ):
            serper_item = EvidenceItem(
                url="https://rbi.org.in/press/fallback",
                title="RBI Official Statement",
                excerpt="No mandatory fee exists.",
                retrieval_success=True,
                provider="serper",
            )
            with patch.object(serper, "search", return_value=[serper_item]):
                bundle = retrieve_evidence(self._make_claim(), providers=[tavily, serper])

        self.assertEqual(len(bundle.items), 1)
        self.assertEqual(bundle.items[0].url, "https://rbi.org.in/press/fallback")
        self.assertEqual(bundle.items[0].provider, "serper")
        self.assertIn("serper", bundle.search_provider_used)
        self.assertIsNone(bundle.provider_error)
        self.assertEqual(bundle.providers_attempted, ["tavily", "serper"])

    # 7. Provider fallback: Tavily & Serper fail -> DuckDuckGo succeeds
    def test_provider_fallback_to_duckduckgo(self):
        tavily = TavilyProvider(api_key="key")
        serper = SerperProvider(api_key="key")
        ddg = DuckDuckGoProvider()

        with patch.object(
            tavily,
            "search",
            return_value=[
                EvidenceItem(url="about:error", retrieval_success=False, retrieval_error="Tavily quota exceeded", provider="tavily")
            ],
        ):
            with patch.object(
                serper,
                "search",
                return_value=[
                    EvidenceItem(url="about:error", retrieval_success=False, retrieval_error="Serper rate limited", provider="serper")
                ],
            ):
                ddg_item = EvidenceItem(
                    url="https://npci.org.in/advisory",
                    title="NPCI Advisory",
                    excerpt="UPI fees rumour is false.",
                    retrieval_success=True,
                    provider="duckduckgo",
                )
                with patch.object(ddg, "search", return_value=[ddg_item]):
                    bundle = retrieve_evidence(self._make_claim(), providers=[tavily, serper, ddg])

        self.assertEqual(len(bundle.items), 1)
        self.assertEqual(bundle.items[0].url, "https://npci.org.in/advisory")
        self.assertEqual(bundle.items[0].provider, "duckduckgo")
        self.assertEqual(bundle.search_provider_used, "duckduckgo")
        self.assertIsNone(bundle.provider_error)
        self.assertEqual(bundle.providers_attempted, ["tavily", "serper", "duckduckgo"])

    # 8. All providers failing
    def test_all_providers_failing_reports_provider_error(self):
        tavily = TavilyProvider(api_key="key")
        serper = SerperProvider(api_key="key")

        with patch.object(
            tavily,
            "search",
            return_value=[
                EvidenceItem(url="about:error", retrieval_success=False, retrieval_error="Tavily down", provider="tavily")
            ],
        ):
            with patch.object(
                serper,
                "search",
                return_value=[
                    EvidenceItem(url="about:error", retrieval_success=False, retrieval_error="Serper down", provider="serper")
                ],
            ):
                bundle = retrieve_evidence(self._make_claim(), providers=[tavily, serper])

        self.assertEqual(bundle.items, [])
        self.assertIsNotNone(bundle.provider_error)
        self.assertIn("tavily", bundle.provider_error)
        self.assertIn("serper", bundle.provider_error)
        self.assertEqual(bundle.search_provider_used, "none")

    # 9. Empty search results distinguished from provider failure
    def test_empty_search_results_distinguished_from_failure(self):
        tavily = TavilyProvider(api_key="key")
        with patch.object(tavily, "search", return_value=[]):
            bundle = retrieve_evidence(self._make_claim(), providers=[tavily])

        self.assertEqual(bundle.items, [])
        self.assertIsNone(bundle.provider_error)
        self.assertEqual(bundle.search_provider_used, "tavily")

    # 10. Duplicate URLs deduplicated across providers
    def test_duplicate_urls_deduplicated_across_providers(self):
        item1 = EvidenceItem(
            url="https://rbi.org.in/press/1",
            title="RBI Press Release",
            excerpt="First excerpt",
            retrieval_success=True,
            provider="tavily",
        )
        item2 = EvidenceItem(
            url="https://rbi.org.in/press/1/",  # trailing slash duplicate
            title="RBI Press Release Duplicate",
            excerpt="Second excerpt",
            retrieval_success=True,
            provider="serper",
        )
        deduped = _deduplicate([item1, item2])
        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0].url, "https://rbi.org.in/press/1")
        self.assertEqual(deduped[0].provider, "tavily")  # Preserves first provider attribution

    # 11. Configuration of provider order
    def test_configuration_of_provider_order(self):
        with patch("backend.services.evidence_retriever.get_settings") as mock_settings:
            mock_s = MagicMock()
            mock_s.search_provider_order_list = ["serper", "tavily"]
            mock_s.SERPER_API_KEY = "serper-key"
            mock_s.TAVILY_API_KEY = "tavily-key"
            mock_settings.return_value = mock_s

            providers = _get_providers()
            self.assertEqual(len(providers), 2)
            self.assertEqual(providers[0].provider_id, "serper")
            self.assertEqual(providers[1].provider_id, "tavily")

    def test_explicit_none_order_disables_every_external_provider(self):
        with patch("backend.services.evidence_retriever.get_settings") as mock_settings:
            mock_s = MagicMock()
            mock_s.search_provider_order_list = ["none"]
            mock_settings.return_value = mock_s

            providers = _get_providers()

        self.assertEqual([provider.provider_id for provider in providers], ["none"])
        self.assertIsInstance(providers[0], NoOpProvider)

    def test_noop_entry_disables_search_even_when_mixed_with_live_provider(self):
        with patch("backend.services.evidence_retriever.get_settings") as mock_settings:
            mock_s = MagicMock()
            mock_s.search_provider_order_list = ["serper", "noop"]
            mock_settings.return_value = mock_s

            providers = _get_providers()

        self.assertEqual([provider.provider_id for provider in providers], ["none"])

    def test_provider_configuration_error_does_not_enable_default_live_search(self):
        with patch(
            "backend.services.evidence_retriever.get_settings",
            side_effect=RuntimeError("invalid configuration"),
        ):
            with self.assertRaisesRegex(RuntimeError, "invalid configuration"):
                _get_providers()

    # 12. Corroboration mode queries multiple providers
    def test_corroboration_mode_queries_multiple_providers(self):
        tavily = TavilyProvider(api_key="key")
        serper = SerperProvider(api_key="key")

        item_t = EvidenceItem(
            url="https://rbi.org.in/press/tavily",
            title="RBI announcement on account blocking",
            excerpt="RBI announced that bank accounts will be blocked tonight.",
            source_quality=SourceQuality.AUTHORITATIVE,
            retrieval_success=True,
            provider="tavily",
        )
        item_s = EvidenceItem(
            url="https://sebi.gov.in/press/serper",
            title="Serper Result",
            retrieval_success=True,
            provider="serper",
        )

        with patch.object(tavily, "search", return_value=[item_t]):
            with patch.object(serper, "search", return_value=[item_s]):
                # Test with corroborate=False (default): stops after Tavily
                bundle_single = retrieve_evidence(self._make_claim(), providers=[tavily, serper], corroborate=False)
                self.assertEqual(len(bundle_single.items), 1)
                self.assertEqual(bundle_single.search_provider_used, "tavily")

                # Test with corroborate=True: queries both Tavily and Serper
                bundle_corroborate = retrieve_evidence(self._make_claim(), providers=[tavily, serper], corroborate=True)
                self.assertEqual(len(bundle_corroborate.items), 2)
                self.assertIn("tavily", bundle_corroborate.search_provider_used)
                self.assertIn("serper", bundle_corroborate.search_provider_used)

    # 13. API analyze endpoint returns provider attribution in response
    def test_api_analyze_returns_provider_attribution(self):
        mock_evidence_bundle = EvidenceBundle(
            items=[
                EvidenceItem(
                    url="https://rbi.org.in/clarification",
                    title="RBI Clarification",
                    excerpt="No accounts will be blocked tonight.",
                    source_quality=SourceQuality.AUTHORITATIVE,
                    retrieval_success=True,
                    provider="tavily",
                )
            ],
            search_provider_used="tavily",
            total_retrieved=1,
            total_deduplicated=1,
            providers_attempted=["tavily"],
        )

        with patch("backend.services.verification_service.retrieve_evidence", return_value=mock_evidence_bundle):
            response = client.post(
                "/api/analyze",
                json={"text": "RBI has announced that bank accounts will be blocked tonight unless ₹500 is paid."},
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertGreater(len(data["evidence"]), 0)
        self.assertEqual(data["evidence"][0]["provider"], "tavily")
        self.assertEqual(data["evidence"][0]["url"], "https://rbi.org.in/clarification")

    # 14. Serper fails (timeout/error/rate limit) and DuckDuckGo succeeds
    def test_serper_fails_and_duckduckgo_succeeds(self):
        serper = SerperProvider(api_key="serper-test-key")
        ddg = DuckDuckGoProvider()

        # Serper returns failure item (e.g. rate limit HTTP 429)
        with patch.object(
            serper,
            "search",
            return_value=[
                EvidenceItem(url="about:error", retrieval_success=False, retrieval_error="Serper rate limit exceeded (HTTP 429).", provider="serper")
            ],
        ):
            # DuckDuckGo fallback succeeds
            ddg_item = EvidenceItem(
                url="https://rbi.org.in/press/fallback_ddg",
                title="RBI Clarification Notice",
                excerpt="No accounts will be blocked tonight.",
                source_quality=SourceQuality.AUTHORITATIVE,
                retrieval_success=True,
                provider="duckduckgo",
            )
            with patch.object(ddg, "search", return_value=[ddg_item]):
                bundle = retrieve_evidence(self._make_claim(), providers=[serper, ddg])

        self.assertEqual(len(bundle.items), 1)
        self.assertEqual(bundle.items[0].url, "https://rbi.org.in/press/fallback_ddg")
        self.assertEqual(bundle.items[0].provider, "duckduckgo")
        self.assertEqual(bundle.search_provider_used, "duckduckgo")
        self.assertIsNone(bundle.provider_error)
        self.assertEqual(bundle.providers_attempted, ["serper", "duckduckgo"])

    # 15. Tavily is completely skipped when key is missing (zero network calls)
    def test_tavily_skipped_when_key_missing(self):
        with patch("backend.services.evidence_retriever.get_settings") as mock_settings:
            mock_s = MagicMock()
            # Even if order explicitly lists tavily, missing key must skip it
            mock_s.search_provider_order_list = ["tavily", "serper", "duckduckgo"]
            mock_s.TAVILY_API_KEY = None  # Missing key
            mock_s.SERPER_API_KEY = "serper-key"
            mock_settings.return_value = mock_s

            providers = _get_providers()
            # Tavily must be omitted completely
            provider_ids = [p.provider_id for p in providers]
            self.assertNotIn("tavily", provider_ids)
            self.assertEqual(provider_ids[0], "serper")
            self.assertEqual(provider_ids[1], "duckduckgo")

        # Calling Tavily search directly without key makes 0 HTTP calls
        tavily = TavilyProvider(api_key=None)
        with patch("httpx.post") as mock_post:
            items = tavily.search("query")
            mock_post.assert_not_called()
        self.assertEqual(len(items), 1)
        self.assertFalse(items[0].retrieval_success)

    # 16. If Serper key is missing, DuckDuckGo is used directly
    def test_serper_key_missing_uses_duckduckgo_directly(self):
        with patch("backend.services.evidence_retriever.get_settings") as mock_settings:
            mock_s = MagicMock()
            mock_s.search_provider_order_list = ["serper", "duckduckgo"]
            mock_s.SERPER_API_KEY = None  # Missing Serper key
            mock_settings.return_value = mock_s

            providers = _get_providers()
            provider_ids = [p.provider_id for p in providers]
            self.assertEqual(provider_ids, ["duckduckgo"])

    # 17. Both Serper and DuckDuckGo fail -> clear search-unavailable state
    def test_both_providers_fail_returns_search_unavailable_state(self):
        serper = SerperProvider(api_key="serper-key")
        ddg = DuckDuckGoProvider()

        with patch.object(
            serper,
            "search",
            return_value=[
                EvidenceItem(url="about:error", retrieval_success=False, retrieval_error="Serper network error", provider="serper")
            ],
        ):
            with patch.object(
                ddg,
                "search",
                return_value=[
                    EvidenceItem(url="about:error", retrieval_success=False, retrieval_error="DuckDuckGo blocked request", provider="duckduckgo")
                ],
            ):
                bundle = retrieve_evidence(self._make_claim(), providers=[serper, ddg])

        # Must report clear unavailable state without fabricating items
        self.assertEqual(bundle.items, [])
        self.assertEqual(bundle.search_provider_used, "none")
        self.assertIsNotNone(bundle.provider_error)
        self.assertIn("serper", bundle.provider_error)
        self.assertIn("duckduckgo", bundle.provider_error)

        # In verification service, this maps to provider_unavailable status with UNVERIFIED verdict
        with patch("backend.services.verification_service.retrieve_evidence", return_value=bundle):
            from backend.services.verification_service import analyse_claim
            res = analyse_claim("RBI has announced bank accounts blocked tonight.")
            self.assertEqual(res.status, "provider_unavailable")
            self.assertEqual(res.verdict, Verdict.ERROR)
            self.assertEqual(res.evidence, [])  # Never fabricate evidence!

    # 18. No API keys are hardcoded in source code or default configuration
    def test_no_api_keys_hardcoded(self):
        from backend.config import Settings
        fresh_settings = Settings(
            _env_file=None,
            SEARCH_PROVIDER_ORDER="serper,duckduckgo",
        )  # use an explicit order while asserting that no provider keys are defaulted
        self.assertIsNone(fresh_settings.TAVILY_API_KEY)
        self.assertIsNone(fresh_settings.SERPER_API_KEY)
        self.assertEqual(fresh_settings.search_provider_order_list, ["serper", "duckduckgo"])


# ===========================================================================
# 9 — Live Search Provider Selection & Evidence-Based Verdict Reliability
# ===========================================================================


class TestEvidenceReliabilityAndProviderSelection(unittest.TestCase):
    """Offline mocked tests verifying provider selection and evidence/verdict reliability."""

    _CLAIM_TEXT = (
        "RBI has announced that all bank accounts will be blocked tonight "
        "unless customers pay ₹500 for mandatory verification."
    )

    def test_serper_selected_when_configured_and_key_present(self):
        """Serper is selected when configured and its key is present."""
        with patch("backend.services.evidence_retriever.get_settings") as mock_settings:
            mock_s = MagicMock()
            mock_s.search_provider_order_list = ["serper", "duckduckgo"]
            mock_s.SERPER_API_KEY = "valid-mock-serper-key"
            mock_settings.return_value = mock_s

            providers = _get_providers()
            self.assertGreater(len(providers), 0)
            self.assertEqual(providers[0].provider_id, "serper")
            self.assertTrue(providers[0].is_available)

    def test_serper_failure_triggers_duckduckgo_fallback(self):
        """Serper failure (e.g. HTTP 401/429/timeout) triggers DuckDuckGo fallback."""
        serper = SerperProvider(api_key="mock-key")
        ddg = DuckDuckGoProvider()

        with patch.object(
            serper,
            "search",
            return_value=[
                EvidenceItem(
                    url="about:error",
                    retrieval_success=False,
                    retrieval_error="Serper authentication failed or quota exhausted (HTTP 401).",
                    provider="serper",
                )
            ],
        ):
            ddg_item = EvidenceItem(
                url="https://rbi.org.in/press/fallback_official",
                title="RBI Clarification Notice",
                excerpt="Official statement on banking guidelines.",
                source_quality=SourceQuality.AUTHORITATIVE,
                retrieval_success=True,
                provider="duckduckgo",
            )
            with patch.object(ddg, "search", return_value=[ddg_item]):
                bundle = retrieve_evidence(process_claim(self._CLAIM_TEXT), providers=[serper, ddg])

        self.assertEqual(bundle.search_provider_used, "duckduckgo")
        self.assertEqual(len(bundle.items), 1)
        self.assertEqual(bundle.items[0].provider, "duckduckgo")
        self.assertEqual(bundle.providers_attempted, ["serper", "duckduckgo"])
        self.assertTrue(any("serper" in err for err in bundle.provider_errors))

    def test_missing_serper_key_skips_serper(self):
        """Missing Serper key skips Serper and falls back to DuckDuckGo directly."""
        with patch("backend.services.evidence_retriever.get_settings") as mock_settings:
            mock_s = MagicMock()
            mock_s.search_provider_order_list = ["serper", "duckduckgo"]
            mock_s.SERPER_API_KEY = None
            mock_settings.return_value = mock_s

            providers = _get_providers()
            provider_ids = [p.provider_id for p in providers]
            self.assertNotIn("serper", provider_ids)
            self.assertIn("duckduckgo", provider_ids)

    def test_irrelevant_keyword_overlap_does_not_justify_false(self):
        """Irrelevant keyword-overlap (e.g. ₹500 note rumors, general KYC scams) must NOT justify FALSE."""
        claim = process_claim(self._CLAIM_TEXT)
        unrelated_items = [
            EvidenceItem(
                url="https://rbi.org.in/banknotes/500",
                title="RBI clarification on Star series Rs 500 banknotes",
                excerpt="The Reserve Bank of India clarifies that ₹500 banknotes with star symbol are genuine legal tender.",
                source_quality=SourceQuality.AUTHORITATIVE,
                retrieval_success=True,
                provider="duckduckgo",
            ),
            EvidenceItem(
                url="https://rbi.org.in/kyc/advisory",
                title="RBI Caution Notice on KYC scams",
                excerpt="RBI warns public against KYC update fraud and cyber scam alerts. Never share OTP.",
                source_quality=SourceQuality.AUTHORITATIVE,
                retrieval_success=True,
                provider="duckduckgo",
            ),
            EvidenceItem(
                url="https://sebi.gov.in/services",
                title="SEBI Investor Services and Verification Portal",
                excerpt="SEBI online portal for intermediary verification and investor complaints.",
                source_quality=SourceQuality.AUTHORITATIVE,
                retrieval_success=True,
                provider="duckduckgo",
            ),
        ]
        bundle = _make_bundle(unrelated_items)
        result = verify_claims(claim, bundle)

        # Must NOT classify claim as FALSE simply because of partial keyword overlaps like "RBI", "500", or "KYC scam warning"
        self.assertNotEqual(result.verdict, Verdict.FALSE)
        self.assertEqual(result.verdict, Verdict.UNVERIFIED)
        self.assertEqual(len(result.contradicting_evidence), 0)
        self.assertEqual(len(result.supporting_evidence), 0)

    def test_insufficient_evidence_produces_unverified(self):
        """Insufficient or inconclusive evidence produces UNVERIFIED."""
        claim = process_claim(self._CLAIM_TEXT)
        inconclusive_items = [
            EvidenceItem(
                url="https://news.example.com/banking",
                title="Banking News Today",
                excerpt="General banking hours and customer holiday advisory across India.",
                source_quality=SourceQuality.REPUTABLE,
                retrieval_success=True,
                provider="duckduckgo",
            )
        ]
        bundle = _make_bundle(inconclusive_items)
        result = verify_claims(claim, bundle)
        self.assertEqual(result.verdict, Verdict.UNVERIFIED)
        self.assertIn("Insufficient", result.explanation)

    def test_conditional_freeze_guidance_does_not_support_universal_tonight_claim(self):
        """General guidance about conditional freezes is not proof of a blanket order."""
        claim = process_claim(
            "RBI has announced that all bank accounts will be blocked tonight "
            "unless customers pay ₹500 for mandatory verification."
        )
        conditional_guidance = EvidenceItem(
            url="https://www.rbi.org.in/commonman/English/scripts/Notification.aspx?Id=378",
            title="Reserve Bank of India",
            excerpt=(
                "At times banks may be required to freeze the accounts of customers "
                "based on orders from enforcement authorities."
            ),
            source_quality=SourceQuality.AUTHORITATIVE,
            retrieval_success=True,
        )
        result = verify_claims(claim, _make_bundle([conditional_guidance]))
        self.assertEqual(result.verdict, Verdict.UNVERIFIED)
        self.assertEqual(result.supporting_evidence, [])

    def test_unrelated_account_action_title_cannot_support_without_matching_excerpt(self):
        """A result title cannot turn a generic excerpt into support for a specific claim."""
        claim = _make_claim()
        title_only = EvidenceItem(
            url="https://www.rbi.org.in/notification/generic-freeze-guidance",
            title="RBI confirms accounts blocked tonight",
            excerpt=(
                "Banks may freeze a customer's account when ordered by an enforcement authority."
            ),
            source_quality=SourceQuality.AUTHORITATIVE,
            retrieval_success=True,
        )
        result = verify_claims(claim, _make_bundle([title_only]))
        self.assertEqual(result.verdict, Verdict.UNVERIFIED)
        self.assertEqual(result.supporting_evidence, [])

    def test_direct_relevant_contradiction_justifies_false(self):
        """Direct, relevant contradiction can justify FALSE."""
        claim = process_claim(self._CLAIM_TEXT)
        debunking_items = [
            EvidenceItem(
                url="https://pib.gov.in/factcheck/rbi-account-fee",
                title="PIB Fact Check: Fake message on RBI blocking accounts for ₹500 fee",
                excerpt=(
                    "A viral post claiming that RBI has announced all bank accounts will be blocked "
                    "tonight unless customers pay a ₹500 mandatory verification fee is fake news. "
                    "RBI has issued no such circular or notice."
                ),
                source_quality=SourceQuality.AUTHORITATIVE,
                retrieval_success=True,
                provider="serper",
            )
        ]
        bundle = _make_bundle(debunking_items)
        result = verify_claims(claim, bundle)
        self.assertEqual(result.verdict, Verdict.FALSE)
        self.assertGreater(len(result.contradicting_evidence), 0)
        self.assertIn("contradicts", result.explanation.lower())

    def test_scam_risk_score_does_not_determine_factual_verdict(self):
        """High scam-risk score does not force verdict to FALSE when evidence is unverified."""
        from backend.services.verification_service import analyse_claim

        unrelated_items = [
            EvidenceItem(
                url="https://rbi.org.in/banknotes/500",
                title="RBI Clarification on Rs 500 notes",
                excerpt="Both types of 500 notes are legal tender.",
                source_quality=SourceQuality.AUTHORITATIVE,
                retrieval_success=True,
                provider="duckduckgo",
            )
        ]
        mock_bundle = EvidenceBundle(
            items=unrelated_items,
            search_provider_used="duckduckgo",
            providers_attempted=["duckduckgo"],
        )
        with patch("backend.services.verification_service.retrieve_evidence", return_value=mock_bundle):
            result = analyse_claim(self._CLAIM_TEXT)

        # Scam detector independently flags urgency & payment demand as HIGH risk
        self.assertEqual(result.scam_assessment.category, RiskCategory.HIGH)
        self.assertGreaterEqual(result.scam_assessment.score, 60)
        # BUT factual verdict remains UNVERIFIED because no direct contradiction was established
        self.assertEqual(result.verdict, Verdict.UNVERIFIED)

    def test_unrelated_official_domain_not_treated_as_relevant_evidence(self):
        """Unrelated official-domain results are not treated as relevant evidence solely because of domain."""
        claim = process_claim(self._CLAIM_TEXT)
        official_unrelated_items = [
            EvidenceItem(
                url="https://rbi.org.in/holiday-calendar",
                title="Reserve Bank of India - Annual Bank Holidays",
                excerpt="List of state-wise bank holidays and financial institution working days.",
                source_quality=SourceQuality.AUTHORITATIVE,
                retrieval_success=True,
                provider="duckduckgo",
            ),
            EvidenceItem(
                url="https://sebi.gov.in/filings",
                title="SEBI Board Meeting Circular",
                excerpt="Official notification regarding mutual fund disclosure norms.",
                source_quality=SourceQuality.AUTHORITATIVE,
                retrieval_success=True,
                provider="duckduckgo",
            ),
        ]
        bundle = _make_bundle(official_unrelated_items)
        result = verify_claims(claim, bundle)

        # Must NOT be marked TRUE or PARTIALLY_TRUE or FALSE
        self.assertEqual(result.verdict, Verdict.UNVERIFIED)
        self.assertEqual(len(result.supporting_evidence), 0)
        self.assertEqual(len(result.contradicting_evidence), 0)

    def test_api_analyze_schema_compatibility(self):
        """POST /api/analyze response matches schema and preserves structure."""
        r = client.post("/api/analyze", json={"text": self._CLAIM_TEXT})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        required_keys = {
            "request_id", "status", "original_text", "claims",
            "verdict", "explanation", "evidence", "scam_assessment", "limitations"
        }
        for k in required_keys:
            self.assertIn(k, data)
        self.assertIsInstance(data["evidence"], list)
        self.assertIsInstance(data["limitations"], list)
        self.assertIn("score", data["scam_assessment"])
        self.assertIn("category", data["scam_assessment"])


# ===========================================================================
# 9 — Regression tests: relational fact verification
# ===========================================================================


class TestRelationalFactVerification(unittest.TestCase):
    """Regression tests for the relational entity verification engine.

    These tests use mock evidence items that simulate what live Serper search
    would return, so they remain fully deterministic and offline.
    """

    def _make_claim_obj(self, text: str) -> ExtractedClaim:
        return process_claim(text)

    def _bundle(self, items: list[EvidenceItem]) -> EvidenceBundle:
        return EvidenceBundle(
            items=items,
            search_provider_used="mock",
        )

    # -----------------------------------------------------------------------
    # Claim: "RBI is the central bank of the United States" -> FALSE
    # -----------------------------------------------------------------------

    def test_rbi_is_central_bank_of_usa_returns_false(self):
        """RBI as central bank of USA should be FALSE given FedReserve evidence."""
        claim = self._make_claim_obj(
            "The Reserve Bank of India (RBI) is the central bank of the United States of America."
        )
        items = [
            EvidenceItem(
                url="https://www.federalreserve.gov/",
                title="Federal Reserve Board - Home",
                excerpt=(
                    "The Federal Reserve, the central bank of the United States, "
                    "provides the nation with a safe, flexible, and stable monetary and financial system."
                ),
                source_quality=SourceQuality.AUTHORITATIVE,
                retrieval_success=True,
                provider="serper",
            ),
            EvidenceItem(
                url="https://en.wikipedia.org/wiki/Reserve_Bank_of_India",
                title="Reserve Bank of India",
                excerpt=(
                    "The Reserve Bank of India (RBI) is the central bank of the Republic of India "
                    "and the regulatory organisation for the Indian banking & financial system."
                ),
                source_quality=SourceQuality.REPUTABLE,
                retrieval_success=True,
                provider="serper",
            ),
        ]
        result = verify_claims(claim, self._bundle(items))
        self.assertEqual(result.verdict, Verdict.FALSE)

    # -----------------------------------------------------------------------
    # Claim: "RBI is India's central bank ..." -> TRUE
    # -----------------------------------------------------------------------

    def test_rbi_is_indias_central_bank_returns_true(self):
        """RBI as India's central bank should be TRUE given RBI/Wikipedia evidence."""
        claim = self._make_claim_obj(
            "The Reserve Bank of India (RBI) is India's central bank and is responsible "
            "for regulating the country's banking system."
        )
        items = [
            EvidenceItem(
                url="https://rbi.org.in/history/Brief_History.html",
                title="Brief History of RBI",
                excerpt=(
                    "The Reserve Bank of India is the central bank of the country. "
                    "Central banks are a relatively recent innovation."
                ),
                source_quality=SourceQuality.AUTHORITATIVE,
                retrieval_success=True,
                provider="serper",
            ),
            EvidenceItem(
                url="https://en.wikipedia.org/wiki/Reserve_Bank_of_India",
                title="Reserve Bank of India",
                excerpt=(
                    "The Reserve Bank of India (RBI) is the central bank of the Republic of India "
                    "and regulates the Indian banking & financial system."
                ),
                source_quality=SourceQuality.REPUTABLE,
                retrieval_success=True,
                provider="serper",
            ),
        ]
        result = verify_claims(claim, self._bundle(items))
        self.assertEqual(result.verdict, Verdict.TRUE)

    # -----------------------------------------------------------------------
    # Claim: "India's central bank is the RBI" -> TRUE (inverse phrasing)
    # -----------------------------------------------------------------------

    def test_indias_central_bank_is_rbi_returns_true(self):
        """India's central bank is the RBI should be TRUE (inverse phrasing)."""
        claim = self._make_claim_obj(
            "India's central bank is the Reserve Bank of India."
        )
        items = [
            EvidenceItem(
                url="https://en.wikipedia.org/wiki/Reserve_Bank_of_India",
                title="Reserve Bank of India",
                excerpt=(
                    "The Reserve Bank of India (RBI) is the central bank of the Republic of India. "
                    "It regulates the monetary system of India."
                ),
                source_quality=SourceQuality.REPUTABLE,
                retrieval_success=True,
                provider="serper",
            ),
        ]
        result = verify_claims(claim, self._bundle(items))
        self.assertEqual(result.verdict, Verdict.TRUE)

    # -----------------------------------------------------------------------
    # Claim: Imaginary policy -> UNVERIFIED
    # -----------------------------------------------------------------------

    def test_unverifiable_claim_returns_unverified(self):
        """A claim about an imaginary policy should return UNVERIFIED, not FALSE."""
        claim = self._make_claim_obj(
            "The RBI announced an imaginary policy yesterday."
        )
        items = [
            EvidenceItem(
                url="https://rbi.org.in/press/general",
                title="RBI Press Releases",
                excerpt="Latest press releases from the Reserve Bank of India on monetary policy.",
                source_quality=SourceQuality.AUTHORITATIVE,
                retrieval_success=True,
                provider="serper",
            ),
        ]
        result = verify_claims(claim, self._bundle(items))
        self.assertEqual(result.verdict, Verdict.UNVERIFIED)
        self.assertNotEqual(result.verdict, Verdict.FALSE)

    # -----------------------------------------------------------------------
    # Sanity: contradiction via known central bank still works
    # -----------------------------------------------------------------------

    def test_federal_reserve_evidence_contradicts_rbi_usa_claim(self):
        """FedReserve evidence contradicting RBI-as-USA-central-bank should reach FALSE."""
        claim = self._make_claim_obj(
            "The Reserve Bank of India (RBI) is the central bank of the United States of America."
        )
        # Explicit evidence from USA.gov confirming Federal Reserve is the US central bank
        items = [
            EvidenceItem(
                url="https://www.usa.gov/agencies/federal-reserve-system",
                title="Federal Reserve System | USAGov",
                excerpt=(
                    "The Federal Reserve is the central bank of the United States. "
                    "It formulates and administers credit and monetary policy."
                ),
                source_quality=SourceQuality.AUTHORITATIVE,
                retrieval_success=True,
                provider="serper",
            ),
        ]
        result = verify_claims(claim, self._bundle(items))
        self.assertEqual(result.verdict, Verdict.FALSE)
        self.assertGreater(len(result.contradicting_evidence), 0)

    def test_rbi_only_evidence_does_not_prove_its_us_relationship_false(self):
        claim = process_claim(
            "The Reserve Bank of India is the central bank of the United States."
        )
        bundle = self._bundle(
            [
                EvidenceItem(
                    url="https://rbi.org.in/history/Brief_History.html",
                    title="Brief History of RBI",
                    excerpt="The Reserve Bank of India is the central bank of India.",
                    source_quality=SourceQuality.AUTHORITATIVE,
                )
            ]
        )
        result = verify_claims(claim, bundle)
        self.assertEqual(result.verdict, Verdict.UNVERIFIED)
        self.assertEqual(result.contradicting_evidence, [])

    def test_official_queries_are_generated_for_relational_claims(self):
        us_claim = process_claim(
            "The Reserve Bank of India is the central bank of the United States."
        )
        india_claim = process_claim(
            "The Reserve Bank of India is India's central bank."
        )
        self.assertTrue(
            any("site:federalreserve.gov" in query for query in _build_queries(us_claim))
        )
        self.assertTrue(
            any("site:rbi.org.in" in query for query in _build_queries(india_claim))
        )

    def test_unknown_source_does_not_establish_relational_claim(self):
        claim = process_claim("The Reserve Bank of India is India's central bank.")
        bundle = self._bundle(
            [
                EvidenceItem(
                    url="https://unknown.example/rbi",
                    title="Reserve Bank of India",
                    excerpt="The Reserve Bank of India is India's central bank.",
                    source_quality=SourceQuality.UNKNOWN,
                )
            ]
        )
        result = verify_claims(claim, bundle)
        self.assertEqual(result.verdict, Verdict.UNVERIFIED)
        self.assertEqual(result.supporting_evidence, [])

    def test_explicit_relational_denial_is_not_mistaken_for_support(self):
        claim = process_claim("The Reserve Bank of India is India's central bank.")
        bundle = self._bundle(
            [
                EvidenceItem(
                    url="https://rbi.org.in/clarification",
                    title="RBI clarification",
                    excerpt="The Reserve Bank of India is not the central bank of India.",
                    source_quality=SourceQuality.AUTHORITATIVE,
                )
            ]
        )
        result = verify_claims(claim, bundle)
        self.assertEqual(result.verdict, Verdict.FALSE)

    def test_unrelated_official_rbi_page_is_not_regulation_evidence(self):
        claim = process_claim(
            "The Reserve Bank of India is responsible for regulating the country's banking system."
        )
        bundle = self._bundle(
            [
                EvidenceItem(
                    url="https://rbi.org.in/forex/department",
                    title="Foreign Exchange Department",
                    excerpt=(
                        "Monitors integration of government systems with Reserve Bank's core banking "
                        "platform and handles regulatory issues and currency swaps."
                    ),
                    source_quality=SourceQuality.AUTHORITATIVE,
                )
            ]
        )
        result = verify_claims(claim, bundle)
        self.assertEqual(result.verdict, Verdict.UNVERIFIED)
        self.assertEqual(result.supporting_evidence, [])

    def test_api_returns_evidence_relationship_assessments(self):
        text = "The Reserve Bank of India is India's central bank."
        bundle = self._bundle(
            [
                EvidenceItem(
                    url="https://rbi.org.in/history/Brief_History.html",
                    title="Brief History of RBI",
                    excerpt="The Reserve Bank of India is the central bank of the country. India.",
                    source_quality=SourceQuality.AUTHORITATIVE,
                )
            ]
        )
        with patch(
            "backend.services.verification_service.retrieve_evidence",
            return_value=bundle,
        ):
            response = client.post("/api/analyze", json={"text": text})

        self.assertEqual(response.status_code, 200)
        evidence = response.json()["evidence"][0]
        self.assertEqual(evidence["assessments"][0]["relationship"], "supports")
        self.assertEqual(evidence["assessments"][0]["relevance"], "relevant")


class TestAttributeVerification(unittest.TestCase):
    def _claim(self, text: str) -> ExtractedClaim:
        return process_claim(text)

    def _evidence(self, excerpt: str, url: str = "https://rbi.org.in/facts") -> EvidenceItem:
        return EvidenceItem(
            url=url,
            title="Reserve Bank of India",
            excerpt=excerpt,
            source_quality=SourceQuality.AUTHORITATIVE,
        )

    def _verify(self, claim_text: str, excerpts: list[str]):
        items = [
            self._evidence(excerpt, f"https://rbi.org.in/facts/{index}")
            for index, excerpt in enumerate(excerpts)
        ]
        return verify_claims(
            self._claim(claim_text),
            EvidenceBundle(items=items, search_provider_used="mock"),
        )

    def test_rbi_commencement_date_supports_equivalent_date_format(self):
        result = self._verify(
            "RBI commenced operations on 1 April 1935.",
            ["The Reserve Bank of India commenced operations on April 1, 1935."],
        )
        self.assertEqual(result.verdict, Verdict.TRUE)

    def test_rbi_commencement_date_conflict_is_false_only_on_stated_alternative(self):
        result = self._verify(
            "RBI commenced operations on 1 April 1935.",
            ["The Reserve Bank of India commenced operations on 1 April 1936."],
        )
        self.assertEqual(result.verdict, Verdict.FALSE)

    def test_numeric_date_formats_are_normalized(self):
        result = self._verify(
            "RBI commenced operations on 1 April 1935.",
            ["Reserve Bank of India commenced operations on 1935-04-01."],
        )
        self.assertEqual(result.verdict, Verdict.TRUE)

    def test_rbi_headquarters_location_supports_city_alias(self):
        result = self._verify(
            "RBI is headquartered in Mumbai.",
            ["The Reserve Bank of India headquarters are located in Bombay."],
        )
        self.assertEqual(result.verdict, Verdict.TRUE)

    def test_rbi_headquarters_conflicting_location_is_false(self):
        result = self._verify(
            "RBI is headquartered in Mumbai.",
            ["The Reserve Bank of India is headquartered in New Delhi."],
        )
        self.assertEqual(result.verdict, Verdict.FALSE)

    def test_general_amount_attribute_matches_equivalent_rupee_format(self):
        result = self._verify(
            "SBI daily transaction limit is ₹1 lakh.",
            ["SBI daily transaction limit is ₹1,00,000."],
        )
        self.assertEqual(result.verdict, Verdict.TRUE)

    def test_general_amount_attribute_contradiction_requires_same_subject_and_attribute(self):
        direct_conflict = self._verify(
            "SBI daily transaction limit is ₹1 lakh.",
            ["SBI daily transaction limit is ₹2 lakh."],
        )
        unrelated_amount = self._verify(
            "SBI daily transaction limit is ₹1 lakh.",
            ["SBI savings balance is ₹2 lakh."],
        )
        self.assertEqual(direct_conflict.verdict, Verdict.FALSE)
        self.assertEqual(unrelated_amount.verdict, Verdict.UNVERIFIED)

    def test_official_evidence_silent_about_attribute_remains_unverified(self):
        result = self._verify(
            "RBI commenced operations on 1 April 1935.",
            ["The Reserve Bank of India regulates monetary policy and banking."],
        )
        self.assertEqual(result.verdict, Verdict.UNVERIFIED)

    def test_generic_fact_check_or_false_word_about_another_claim_is_not_decisive(self):
        result = self._verify(
            "RBI commenced operations on 1 April 1935.",
            [
                "Fact check: false reports about a new RBI banknote policy were circulated."
            ],
        )
        self.assertEqual(result.verdict, Verdict.UNVERIFIED)

    def test_unrelated_authoritative_page_does_not_support_attribute(self):
        result = self._verify(
            "RBI is headquartered in Mumbai.",
            ["RBI press release confirms a new banking policy in India."],
        )
        self.assertEqual(result.verdict, Verdict.UNVERIFIED)

    def test_direct_attribute_support_and_contradiction_need_no_signal_phrases(self):
        support = self._verify(
            "RBI commenced operations on 1 April 1935.",
            ["Reserve Bank of India commenced operations on 1 April 1935."],
        )
        contradiction = self._verify(
            "RBI commenced operations on 1 April 1935.",
            ["Reserve Bank of India commenced operations on 1 April 1936."],
        )
        self.assertEqual(support.verdict, Verdict.TRUE)
        self.assertEqual(contradiction.verdict, Verdict.FALSE)

    def test_conflicting_authoritative_attribute_values_are_unverified(self):
        result = self._verify(
            "RBI commenced operations on 1 April 1935.",
            [
                "Reserve Bank of India commenced operations on 1 April 1935.",
                "Reserve Bank of India commenced operations on 1 April 1936.",
            ],
        )
        self.assertEqual(result.verdict, Verdict.UNVERIFIED)
        self.assertIn("conflicts", result.explanation)

    def test_mixed_assertions_with_unresolved_part_are_unverified(self):
        results = [
            AssertionVerification(assertion_text="supported", verdict=Verdict.TRUE),
            AssertionVerification(assertion_text="contradicted", verdict=Verdict.FALSE),
            AssertionVerification(assertion_text="unresolved", verdict=Verdict.UNVERIFIED),
        ]
        verdict, _ = _aggregate_verdict(results, [], [], ["unresolved"])
        self.assertEqual(verdict, Verdict.UNVERIFIED)

    def test_mixed_supported_and_contradicted_parts_are_partially_true(self):
        results = [
            AssertionVerification(assertion_text="supported", verdict=Verdict.TRUE),
            AssertionVerification(assertion_text="contradicted", verdict=Verdict.FALSE),
        ]
        verdict, _ = _aggregate_verdict(results, [], [], [])
        self.assertEqual(verdict, Verdict.PARTIALLY_TRUE)

    def test_true_plus_unverified_and_false_plus_unverified_are_unverified(self):
        cases = [
            [Verdict.TRUE, Verdict.UNVERIFIED],
            [Verdict.FALSE, Verdict.UNVERIFIED],
        ]
        for case in cases:
            with self.subTest(case=case):
                results = [
                    AssertionVerification(assertion_text=str(index), verdict=value)
                    for index, value in enumerate(case)
                ]
                verdict, _ = _aggregate_verdict(results, [], [], ["unresolved"])
                self.assertEqual(verdict, Verdict.UNVERIFIED)

    def test_all_supported_and_all_contradicted_have_decisive_aggregate(self):
        cases = [
            ([Verdict.TRUE, Verdict.TRUE], Verdict.TRUE),
            ([Verdict.FALSE, Verdict.FALSE], Verdict.FALSE),
        ]
        for values, expected in cases:
            results = [
                AssertionVerification(assertion_text=str(index), verdict=value)
                for index, value in enumerate(values)
            ]
            verdict, _ = _aggregate_verdict(results, [], [], [])
            self.assertEqual(verdict, expected)


class TestDicgcDepositInsuranceVerification(unittest.TestCase):
    """DICGC amount and bank-category propositions are checked independently."""

    CLAIM = (
        "Under DICGC rules framed by RBI, bank deposits are insured up to "
        "₹5 lakh per depositor across commercial and cooperative banks."
    )
    LIMIT_EXCERPT = (
        "The DICGC insures principal and interest upto a maximum amount of ₹ 5 lakh."
    )
    COMMERCIAL_EXCERPT = (
        "Which banks are insured by the DICGC? Commercial Banks: All commercial banks "
        "including branches of foreign banks functioning in India, local area banks and ..."
    )
    FAQ_EXCERPT = (
        "Each depositor in a bank is insured upto a maximum of ₹ 5,00,000 (Rupees ... "
        "Are deposits in different banks separately insured? Yes. If you have ..."
    )

    def _bundle(self, items: list[EvidenceItem]) -> EvidenceBundle:
        return EvidenceBundle(items=items, search_provider_used="mock")

    def _single_assertion_claim(self, text: str) -> ExtractedClaim:
        return ExtractedClaim(
            original_text=text,
            normalised_text=text,
            assertions=[Assertion(text=text)],
            word_count=len(text.split()),
            char_count=len(text),
        )

    def _official_item(self, url: str, title: str, excerpt: str) -> EvidenceItem:
        return EvidenceItem(
            url=url,
            title=title,
            excerpt=excerpt,
            source_quality=SourceQuality.AUTHORITATIVE,
            provider="mock",
        )

    def test_exact_claim_expands_into_complete_policy_assertions(self):
        claim = process_claim(self.CLAIM)
        texts = [assertion.text for assertion in claim.assertions]
        self.assertEqual(len(texts), 3)
        self.assertEqual(
            texts[0],
            "Under DICGC rules framed by RBI, bank deposits are insured up to ₹5 lakh per depositor.",
        )
        self.assertEqual(
            texts[1],
            "Under DICGC rules framed by RBI, bank deposits are insured across commercial banks.",
        )
        self.assertEqual(
            texts[2],
            "Under DICGC rules framed by RBI, bank deposits are insured across cooperative banks.",
        )

    def test_official_limit_and_commercial_coverage_are_assessed_separately(self):
        claim = process_claim(self.CLAIM)
        bundle = self._bundle(
            [
                self._official_item(
                    "https://www.dicgc.org.in/guide-to-deposit-insurance",
                    "Guide to Deposit Insurance",
                    self.LIMIT_EXCERPT,
                ),
                self._official_item(
                    "https://www.rbi.org.in/commonman/english/Scripts/FAQs.aspx?Id=272",
                    "RBI DICGC FAQs",
                    self.COMMERCIAL_EXCERPT,
                ),
                self._official_item(
                    "https://www.dicgc.org.in/FAQs",
                    "DICGC FAQs",
                    self.FAQ_EXCERPT,
                ),
            ]
        )

        result = verify_claims(claim, bundle)

        self.assertEqual(
            [item.verdict for item in result.assertion_results],
            [Verdict.TRUE, Verdict.TRUE, Verdict.UNVERIFIED],
        )
        self.assertEqual(result.verdict, Verdict.UNVERIFIED)
        self.assertIn("cooperative banks", result.unresolved_assertions[0])
        self.assertTrue(
            any(
                item.assertion_text == claim.assertions[0].text
                and item.relationship == "supports"
                and item.evidence_url.endswith("guide-to-deposit-insurance")
                for item in result.evidence_assessments
            )
        )
        self.assertTrue(
            any(
                item.assertion_text == claim.assertions[1].text
                and item.relationship == "supports"
                and item.evidence_url.endswith("Id=272")
                for item in result.evidence_assessments
            )
        )

    def test_all_material_parts_supported_returns_true(self):
        claim = process_claim(self.CLAIM)
        items = [
            self._official_item(
                "https://www.dicgc.org.in/guide-to-deposit-insurance",
                "Guide to Deposit Insurance",
                self.LIMIT_EXCERPT,
            ),
            self._official_item(
                "https://www.rbi.org.in/commonman/english/Scripts/FAQs.aspx?Id=272",
                "RBI DICGC FAQs",
                self.COMMERCIAL_EXCERPT,
            ),
            self._official_item(
                "mock://dicgc/cooperative-coverage",
                "Deterministic cooperative-bank coverage fixture",
                "DICGC FAQs: Cooperative banks are insured by the DICGC.",
            ),
        ]
        result = verify_claims(claim, self._bundle(items))
        self.assertEqual(result.verdict, Verdict.TRUE)
        self.assertTrue(all(item.verdict == Verdict.TRUE for item in result.assertion_results))

    def test_five_lakh_numeric_and_textual_representations_are_equivalent(self):
        representations = ["₹5 lakh", "₹5,00,000", "five lakh"]
        normalized = [_rupee_amounts(value) for value in representations]
        self.assertEqual(normalized, [{500_000}] * len(representations))

        evidence = self._official_item(
            "https://www.dicgc.org.in/guide-to-deposit-insurance",
            "Guide to Deposit Insurance",
            self.LIMIT_EXCERPT,
        )
        for amount in representations[:3]:
            assertion = f"DICGC insures deposits up to {amount} per depositor."
            result = verify_claims(
                self._single_assertion_claim(assertion),
                self._bundle([evidence]),
            )
            self.assertEqual(result.verdict, Verdict.TRUE, assertion)

    def test_limit_phrase_with_indian_grouping_and_words_is_not_misread_as_conflicting(self):
        evidence = self._official_item(
            "https://www.dicgc.org.in/FAQs",
            "What is the maximum deposit amount insured by the DICGC?",
            "Each depositor in a bank is insured upto a maximum of ₹ 5,00,000 "
            "(Rupees Five Lakhs) for both principal and interest amount",
        )
        result = verify_claims(
            self._single_assertion_claim(
                "DICGC insures deposits up to ₹5 lakh per depositor."
            ),
            self._bundle([evidence]),
        )
        self.assertEqual(result.verdict, Verdict.TRUE)
        self.assertEqual(result.contradicting_evidence, [])

    def test_unrelated_official_rbi_or_dicgc_items_do_not_support_policy(self):
        claim = process_claim(self.CLAIM)
        bundle = self._bundle(
            [
                self._official_item(
                    "https://www.rbi.org.in/",
                    "RBI banking information",
                    "The Reserve Bank of India publishes financial system information.",
                ),
                self._official_item(
                    "https://www.dicgc.org.in/FAQs",
                    "DICGC FAQs",
                    "DICGC explains that deposits in different banks are separately insured.",
                ),
            ]
        )
        result = verify_claims(claim, bundle)
        self.assertEqual(result.verdict, Verdict.UNVERIFIED)
        self.assertEqual(result.supporting_evidence, [])
        self.assertFalse(
            any(item.relationship == "supports" for item in result.evidence_assessments)
        )

    def test_reliable_contradictory_limit_is_retained(self):
        assertion = "DICGC insures deposits up to ₹5 lakh per depositor."
        contrary = self._official_item(
            "mock://dicgc/contradictory-limit",
            "Deterministic contradictory limit fixture",
            "DICGC deposit insurance is limited to a maximum of ₹1 lakh per depositor.",
        )
        result = verify_claims(
            self._single_assertion_claim(assertion),
            self._bundle([contrary]),
        )
        self.assertEqual(result.verdict, Verdict.FALSE)
        self.assertEqual(result.contradicting_evidence, [contrary])
        self.assertTrue(
            any(item.relationship == "contradicts" for item in result.evidence_assessments)
        )

    def test_conflicting_limit_sources_remain_unverified(self):
        assertion = "DICGC insures deposits up to ₹5 lakh per depositor."
        supporting = self._official_item(
            "https://www.dicgc.org.in/guide-to-deposit-insurance",
            "Guide to Deposit Insurance",
            self.LIMIT_EXCERPT,
        )
        contradicting = self._official_item(
            "mock://dicgc/conflicting-limit",
            "Deterministic conflicting limit fixture",
            "DICGC deposit insurance is limited to a maximum of ₹1 lakh per depositor.",
        )
        result = verify_claims(
            self._single_assertion_claim(assertion),
            self._bundle([supporting, contradicting]),
        )
        self.assertEqual(result.verdict, Verdict.UNVERIFIED)
        self.assertIn("conflicts", result.explanation)
        self.assertEqual(result.supporting_evidence, [supporting])
        self.assertEqual(result.contradicting_evidence, [contradicting])

    def test_supported_and_false_material_parts_return_partially_true(self):
        assertions = [
            Assertion(text="DICGC insures deposits up to ₹5 lakh per depositor."),
            Assertion(text="DICGC insures deposits across cooperative banks."),
        ]
        claim = ExtractedClaim(
            original_text="Combined DICGC claim.",
            normalised_text="Combined DICGC claim.",
            assertions=assertions,
        )
        items = [
            self._official_item(
                "https://www.dicgc.org.in/guide-to-deposit-insurance",
                "Guide to Deposit Insurance",
                self.LIMIT_EXCERPT,
            ),
            self._official_item(
                "mock://dicgc/contradictory-cooperative-coverage",
                "Deterministic contradictory category fixture",
                "DICGC does not insure cooperative banks.",
            ),
        ]
        result = verify_claims(claim, self._bundle(items))
        self.assertEqual(result.verdict, Verdict.PARTIALLY_TRUE)

    def test_false_part_with_an_unresolved_part_does_not_force_false(self):
        claim = ExtractedClaim(
            original_text="Combined DICGC claim.",
            normalised_text="Combined DICGC claim.",
            assertions=[
                Assertion(text="DICGC insures deposits up to ₹5 lakh per depositor."),
                Assertion(text="DICGC covers an unrelated new account rule."),
            ],
        )
        contradiction = self._official_item(
            "mock://dicgc/contradictory-limit",
            "Deterministic contradictory limit fixture",
            "DICGC deposit insurance is limited to a maximum of ₹1 lakh per depositor.",
        )
        result = verify_claims(claim, self._bundle([contradiction]))
        self.assertEqual(result.verdict, Verdict.UNVERIFIED)
        self.assertEqual(
            [item.verdict for item in result.assertion_results],
            [Verdict.FALSE, Verdict.UNVERIFIED],
        )

    def test_unreliable_source_cannot_establish_official_limit(self):
        evidence = EvidenceItem(
            url="https://example.invalid/dicgc-limit",
            title="DICGC deposit insurance",
            excerpt=self.LIMIT_EXCERPT,
            source_quality=SourceQuality.UNKNOWN,
        )
        result = verify_claims(
            self._single_assertion_claim(
                "DICGC insures deposits up to ₹5 lakh per depositor."
            ),
            self._bundle([evidence]),
        )
        self.assertEqual(result.verdict, Verdict.UNVERIFIED)
        self.assertEqual(result.supporting_evidence, [])

    def test_incomplete_assertion_cannot_produce_decisive_verdict(self):
        incomplete = self._single_assertion_claim("cooperative banks.")
        evidence = self._official_item(
            "https://www.dicgc.org.in/FAQs",
            "DICGC FAQs",
            "DICGC FAQ about deposits and banks.",
        )
        result = verify_claims(incomplete, self._bundle([evidence]))
        self.assertEqual(result.verdict, Verdict.UNVERIFIED)
        self.assertNotIn(result.verdict, (Verdict.TRUE, Verdict.FALSE))

    def test_dicgc_claim_api_preserves_schema_and_marks_snippets(self):
        bundle = self._bundle(
            [
                self._official_item(
                    "https://www.dicgc.org.in/guide-to-deposit-insurance",
                    "Guide to Deposit Insurance",
                    self.LIMIT_EXCERPT,
                )
            ]
        )
        with patch(
            "backend.services.verification_service.retrieve_evidence",
            return_value=bundle,
        ):
            response = client.post("/api/analyze", json={"text": self.CLAIM})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["verdict"], "UNVERIFIED")
        self.assertEqual(len(data["claims"]), 3)
        self.assertIn("evidence_origin", data["evidence"][0])
        self.assertEqual(data["evidence"][0]["evidence_origin"], "search_snippet")
        self.assertTrue(any("search-provider snippets" in note for note in data["limitations"]))

    def test_dicgc_search_queries_cover_limit_and_both_bank_categories(self):
        queries = _build_queries(process_claim(self.CLAIM))
        self.assertLessEqual(len(queries), 4)
        self.assertTrue(any("deposit insurance maximum" in query for query in queries))
        self.assertTrue(any("commercial banks coverage" in query for query in queries))
        self.assertTrue(any("cooperative banks coverage" in query for query in queries))


# ===========================================================================
# 13 — Demo Claim Regression Suite & Compound Allegation Verification
# ===========================================================================


class TestDemoClaimVerificationRegression(unittest.TestCase):
    """Deterministic regression tests covering compound allegations and official fact-checks."""

    DEMO_CLAIM = (
        "RBI has announced that all bank accounts will be blocked tonight "
        "unless customers pay ₹500 for mandatory verification."
    )

    def test_exact_demo_claim_with_relevant_pib_fact_check_returns_false(self):
        claim = process_claim(self.DEMO_CLAIM)
        self.assertEqual(len(claim.assertions), 4)

        pib_fact_check = EvidenceItem(
            url="https://pib.gov.in/FactCheck/fake-rbi-account-blocking",
            title="PIB Fact Check: Viral message claiming RBI announced account blocking is fake",
            excerpt=(
                "A viral message claims RBI has announced that all bank accounts will be blocked "
                "tonight unless customers pay a ₹500 fee for mandatory verification. "
                "PIB Fact Check: This claim is fake. RBI has issued no such circular or notice. "
                "RBI never asks for fees or blocks customer bank accounts."
            ),
            source_quality=SourceQuality.AUTHORITATIVE,
            retrieval_success=True,
        )
        bundle = EvidenceBundle(items=[pib_fact_check], search_provider_used="mock")
        result = verify_claims(claim, bundle)
        self.assertEqual(result.verdict, Verdict.FALSE)
        self.assertEqual(len(result.unresolved_assertions), 0)
        self.assertEqual(len(result.contradicting_evidence), 1)

    def test_exact_claim_with_only_unrelated_rbi_pib_pages_returns_unverified(self):
        claim = process_claim(self.DEMO_CLAIM)
        unrelated_items = [
            EvidenceItem(
                url="https://rbi.org.in/banknotes/500",
                title="RBI clarification on ₹500 banknotes",
                excerpt="The Reserve Bank of India clarifies that ₹500 banknotes with star symbol are legal tender.",
                source_quality=SourceQuality.AUTHORITATIVE,
                retrieval_success=True,
            ),
            EvidenceItem(
                url="https://pib.gov.in/PressRelease/general-banking",
                title="PIB update on banking hours",
                excerpt="Public information on commercial banking hours and national holidays.",
                source_quality=SourceQuality.AUTHORITATIVE,
                retrieval_success=True,
            ),
        ]
        bundle = EvidenceBundle(items=unrelated_items, search_provider_used="mock")
        result = verify_claims(claim, bundle)
        self.assertEqual(result.verdict, Verdict.UNVERIFIED)
        self.assertEqual(len(result.contradicting_evidence), 0)
        self.assertEqual(len(result.supporting_evidence), 0)

    def test_source_calling_different_rbi_rumor_fake_does_not_contradict(self):
        claim = process_claim(self.DEMO_CLAIM)
        different_rumor_item = EvidenceItem(
            url="https://pib.gov.in/FactCheck/fake-500-note-demonetization",
            title="PIB Fact Check: Claim regarding demonetization of ₹500 notes is fake",
            excerpt=(
                "A viral message claims that RBI will withdraw all ₹500 currency notes by next month. "
                "PIB Fact Check: This message is fake news. RBI has issued no such circular."
            ),
            source_quality=SourceQuality.AUTHORITATIVE,
            retrieval_success=True,
        )
        bundle = EvidenceBundle(items=[different_rumor_item], search_provider_used="mock")
        result = verify_claims(claim, bundle)
        self.assertEqual(result.verdict, Verdict.UNVERIFIED)
        self.assertEqual(len(result.contradicting_evidence), 0)

    def test_direct_denial_no_such_circular_tied_to_account_blocking(self):
        claim = process_claim("RBI has announced that all bank accounts will be blocked.")
        denial_item = EvidenceItem(
            url="https://rbi.org.in/PressReleases/rbi-circular-clarification",
            title="RBI Clarification on Viral Social Media Claims",
            excerpt=(
                "Regarding social media posts alleging that bank accounts will be blocked, "
                "the Reserve Bank of India clarifies that RBI has issued no such circular."
            ),
            source_quality=SourceQuality.AUTHORITATIVE,
            retrieval_success=True,
        )
        bundle = EvidenceBundle(items=[denial_item], search_provider_used="mock")
        result = verify_claims(claim, bundle)
        self.assertEqual(result.verdict, Verdict.FALSE)
        self.assertEqual(len(result.contradicting_evidence), 1)

    def test_search_snippet_omits_decisive_wording_but_fetched_page_includes_it(self):
        claim = process_claim(self.DEMO_CLAIM)
        item = EvidenceItem(
            url="https://pib.gov.in/FactCheck/rbi-account-fee-notice",
            title="PIB Fact Check: Social media rumors clarification",
            excerpt="PIB fact check unit clarifies social media messages regarding recent banking advisories.",
            source_quality=SourceQuality.AUTHORITATIVE,
            retrieval_success=True,
            evidence_origin="search_snippet",
        )
        bundle_before = EvidenceBundle(items=[item], search_provider_used="mock")
        res_before = verify_claims(claim, bundle_before)
        self.assertEqual(res_before.verdict, Verdict.UNVERIFIED)

        page = EvidenceItem(
            url=item.url,
            title="PIB Fact Check: Social media rumors clarification",
            excerpt=(
                "A viral message claims RBI has announced that all bank accounts will be blocked tonight "
                "unless customers pay ₹500 for mandatory verification. "
                "PIB Fact Check: This message is fake. RBI has issued no such circular or notice. "
                "RBI does not block bank accounts or ask for fees."
            ),
            source_quality=SourceQuality.AUTHORITATIVE,
            retrieval_success=True,
            evidence_origin="fetched_page",
        )
        with patch("backend.services.evidence_retriever.fetch_source", return_value=page):
            _apply_fetched_page(item, timeout=5.0)

        self.assertEqual(item.evidence_origin, "fetched_page")
        self.assertEqual(
            item.search_snippet,
            "PIB fact check unit clarifies social media messages regarding recent banking advisories.",
        )
        bundle_after = EvidenceBundle(items=[item], search_provider_used="mock")
        res_after = verify_claims(claim, bundle_after)
        self.assertEqual(res_after.verdict, Verdict.FALSE)

    def test_page_fetch_failure_unsafe_redirect_provider_fallback_and_no_result(self):
        claim = process_claim(self.DEMO_CLAIM)

        # 1. Page fetch failure retains snippet and marks page_fetch_error
        item = EvidenceItem(
            url="https://rbi.org.in/failing-page",
            title="RBI Page",
            excerpt="RBI cautionary guidance.",
            source_quality=SourceQuality.AUTHORITATIVE,
            retrieval_success=True,
            evidence_origin="search_snippet",
        )
        failed_fetch = EvidenceItem(
            url=item.url,
            retrieval_success=False,
            retrieval_error="Connection timed out after 10s.",
            source_quality=SourceQuality.REJECTED,
        )
        with patch("backend.services.evidence_retriever.fetch_source", return_value=failed_fetch):
            _apply_fetched_page(item, timeout=1.0)
        self.assertEqual(item.page_fetch_error, "Connection timed out after 10s.")
        self.assertEqual(item.evidence_origin, "search_snippet")
        self.assertEqual(item.search_snippet, "RBI cautionary guidance.")

        # 2. Unsafe redirect / private IP blocked
        unsafe_fetch = fetch_source("http://127.0.0.1:8000/internal")
        self.assertFalse(unsafe_fetch.retrieval_success)
        self.assertEqual(unsafe_fetch.source_quality, SourceQuality.REJECTED)
        self.assertIn("Blocked", unsafe_fetch.retrieval_error)

        unsafe_private = fetch_source("http://10.0.0.1/admin")
        self.assertFalse(unsafe_private.retrieval_success)
        self.assertEqual(unsafe_private.source_quality, SourceQuality.REJECTED)

        # 3. Provider fallback
        class FailingProvider(BaseSearchProvider):
            @property
            def provider_id(self): return "mock_failing"
            def search(self, query, max_results=5, timeout=None):
                return [EvidenceItem(url="about:error", retrieval_success=False, retrieval_error="HTTP 429", provider="mock_failing")]

        class SuccessProvider(BaseSearchProvider):
            @property
            def provider_id(self): return "mock_success"
            def search(self, query, max_results=5, timeout=None):
                return [EvidenceItem(url="https://rbi.org.in/press/ok", title="OK", excerpt="Info", source_quality=SourceQuality.AUTHORITATIVE, provider="mock_success")]

        bundle = retrieve_evidence(claim, providers=[FailingProvider(), SuccessProvider()], fetch_pages=False)
        self.assertEqual(bundle.search_provider_used, "mock_success")
        self.assertIn("mock_failing", bundle.providers_attempted)
        self.assertIn("mock_success", bundle.providers_attempted)

        # 4. No-result case
        class EmptyProvider(BaseSearchProvider):
            @property
            def provider_id(self): return "mock_empty"
            def search(self, query, max_results=5, timeout=None):
                return []

        empty_bundle = retrieve_evidence(claim, providers=[EmptyProvider()], fetch_pages=False)
        self.assertEqual(len(empty_bundle.items), 0)
        empty_res = verify_claims(claim, empty_bundle)
        self.assertEqual(empty_res.verdict, Verdict.UNVERIFIED)

    def test_mixed_multi_assertion_claim_where_one_part_is_unresolved(self):
        claim = process_claim(self.DEMO_CLAIM)
        partial_denial = EvidenceItem(
            url="https://rbi.org.in/press/account-blocking-clarification",
            title="RBI Notice on Account Blocking",
            excerpt="RBI clarifies that no bank accounts will be blocked. RBI has issued no such circular.",
            source_quality=SourceQuality.AUTHORITATIVE,
            retrieval_success=True,
        )
        bundle = EvidenceBundle(items=[partial_denial], search_provider_used="mock")
        result = verify_claims(claim, bundle)
        self.assertEqual(result.verdict, Verdict.UNVERIFIED)
        self.assertIn("Customers must pay ₹500 for mandatory verification.", result.unresolved_assertions)
        self.assertIn("unresolved", result.explanation.lower())


if __name__ == "__main__":
    unittest.main()

