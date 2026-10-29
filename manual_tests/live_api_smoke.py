"""Opt-in authenticated API smoke test; not part of automated pytest."""

from __future__ import annotations

import os
import sys

import httpx


def main() -> int:
    if os.getenv("RUN_LIVE_API_TESTS") != "1":
        raise SystemExit("Set RUN_LIVE_API_TESTS=1 to make live API requests.")
    token = os.getenv("TRUTHLENS_ACCESS_TOKEN", "").strip()
    if not token:
        raise SystemExit("TRUTHLENS_ACCESS_TOKEN is required; obtain it through the normal Google sign-in flow.")

    base_url = os.getenv("TRUTHLENS_API_URL", "http://127.0.0.1:8000").rstrip("/")
    headers = {"Authorization": f"Bearer {token}"}
    scenarios = [
        "The Reserve Bank of India (RBI) is the central bank of the United States of America.",
        "The Reserve Bank of India (RBI) is India's central bank and regulates India's banking system.",
        "RBI has announced that all bank accounts will be blocked tonight unless customers pay ₹500 for mandatory verification.",
    ]

    with httpx.Client(timeout=35.0, follow_redirects=False) as client:
        health = client.get(f"{base_url}/api/health")
        health.raise_for_status()
        print(f"Health: {health.status_code}")

        for index, claim in enumerate(scenarios, start=1):
            response = client.post(
                f"{base_url}/api/analyze",
                json={"text": claim},
                headers=headers,
            )
            if response.status_code in (401, 403):
                print("Analysis rejected the supplied session; sign in again for a fresh user token.")
                return 1
            response.raise_for_status()
            result = response.json()
            print(
                f"Case {index}: status={result['status']} verdict={result['verdict']} "
                f"risk={result['scam_assessment']['category']} sources={len(result['evidence'])}"
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
