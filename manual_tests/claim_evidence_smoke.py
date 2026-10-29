"""Opt-in live Serper smoke test; not part of automated pytest."""

from __future__ import annotations

import os
import sys
from pathlib import Path

if os.getenv("RUN_LIVE_SEARCH_TESTS") != "1":
    raise SystemExit("Set RUN_LIVE_SEARCH_TESTS=1 to make live Serper requests.")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.config import get_settings
from backend.core.claim_processor import process_claim
from backend.core.verdict_engine import verify_claims
from backend.services.evidence_retriever import SerperProvider, retrieve_evidence


def main() -> int:
    if not get_settings().SERPER_API_KEY:
        raise SystemExit("SERPER_API_KEY is not configured in the backend environment.")

    provider = SerperProvider()
    scenarios = [
        ("The Reserve Bank of India (RBI) is the central bank of the United States of America.", "FALSE"),
        ("The Reserve Bank of India (RBI) is India's central bank and regulates India's banking system.", "TRUE"),
        ("India's central bank is the Reserve Bank of India.", "TRUE"),
        ("The US central banking system is the Reserve Bank of India.", "FALSE"),
        ("The RBI announced an imaginary policy yesterday.", "UNVERIFIED"),
    ]

    failures = 0
    for text, expected in scenarios:
        claim = process_claim(text)
        evidence = retrieve_evidence(claim, providers=[provider])
        result = verify_claims(claim, evidence)
        actual = result.verdict.value
        outcome = "PASS" if actual == expected else "MISMATCH"
        failures += actual != expected
        print(f"[{outcome}] expected={expected} actual={actual}: {text}")
        print(f"  sources={len(evidence.items)} provider_status={evidence.search_provider_used}")
        for item in evidence.items[:2]:
            print(f"  source: {item.url}")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
