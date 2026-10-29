"""Live End-to-End API Integration & Hackathon Demo Test Suite for TruthLens AI.

Opt-in script for authenticated live API calls. See manual_tests/README.md.
"""

import httpx
import os
import sys

BASE_URL = os.getenv("TRUTHLENS_API_URL", "http://127.0.0.1:8000").rstrip("/")


def _analysis_headers() -> dict[str, str]:
    token = os.getenv("TRUTHLENS_ACCESS_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TRUTHLENS_ACCESS_TOKEN is required for authenticated analysis requests.")
    return {"Authorization": f"Bearer {token}"}

def test_health():
    print("\n[TEST 1] GET /api/health ...")
    r = httpx.get(f"{BASE_URL}/api/health", timeout=5.0)
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    data = r.json()
    assert data["status"] == "ok"
    assert data["app_name"] == "TruthLens AI"
    print("  -> Passed. App:", data["app_name"], "Version:", data["version"])

def test_demo_scenarios():
    demos = [
        {
            "name": "DEMO 1: Fake RBI Fee & Account Block Scam",
            "claim": "RBI has announced that all bank accounts will be blocked tonight unless customers pay Rs 500 for mandatory verification.",
            "expected_scam_category": "HIGH",
        },
        {
            "name": "DEMO 2: Guaranteed SEBI Investment Scheme",
            "claim": "Urgent SEBI approved investment scheme guarantees 100% daily profit. Send Rs 5000 via UPI within 1 hour to double your money.",
            "expected_scam_category": "HIGH",
        },
        {
            "name": "DEMO 3: Official DICGC Deposit Insurance Policy",
            "claim": "Under DICGC rules framed by RBI, bank deposits are insured up to Rs 5 lakh per depositor across commercial and cooperative banks.",
            "expected_scam_category": "LOW",
        },
        {
            "name": "DEMO 4: Unverified / Rumor Claim",
            "claim": "Government is planning a secret surprise demonetization announcement next Monday at midnight.",
            "expected_verdict": "UNVERIFIED",
        },
    ]

    for d in demos:
        print(f"\n[TEST SCENARIO] {d['name']} ...")
        resp = httpx.post(
            f"{BASE_URL}/api/analyze",
            json={"text": d["claim"]},
            headers=_analysis_headers(),
            timeout=35.0
        )
        assert resp.status_code == 200, f"Failed: HTTP {resp.status_code} - {resp.text}"
        res = resp.json()

        print(f"  -> Request ID: {res['request_id']}")
        print(f"  -> Status: {res['status']}")
        print(f"  -> Verdict: {res['verdict']}")
        print(f"  -> Scam Risk: {res['scam_assessment']['category']} (Score: {res['scam_assessment']['score']}/100)")
        print(f"  -> Extracted Assertions ({len(res['claims'])}):")
        for c in res['claims']:
            print(f"     * [{c['assertion_type']}] {c['text']} (Entities: {', '.join(c['entities'])})")
        print(f"  -> Retrieved Evidence Count: {len(res['evidence'])}")
        for e in res['evidence'][:2]:
            print(f"     * [{e['source_quality']} via {e['provider']}] {e['title'][:60]} -> {e['url'][:50]}")
        print(f"  -> Detected Indicators ({len(res['scam_assessment']['indicators'])}):")
        for ind in res['scam_assessment']['indicators']:
            print(f"     * {ind['indicator_type']} (+{ind['weight']} pts): '{ind['matched_text']}'")

        if "expected_scam_category" in d:
            assert res['scam_assessment']['category'] == d['expected_scam_category'], \
                f"Expected scam {d['expected_scam_category']}, got {res['scam_assessment']['category']}"
        if "expected_verdict" in d:
            assert res['verdict'] == d['expected_verdict'], \
                f"Expected verdict {d['expected_verdict']}, got {res['verdict']}"
        print("  -> Passed verification.")

def test_input_validation():
    print("\n[TEST VALIDATION] Empty text -> HTTP 422 ...")
    r = httpx.post(
        f"{BASE_URL}/api/analyze",
        json={"text": "   "},
        headers=_analysis_headers(),
        timeout=5.0,
    )
    assert r.status_code == 422, f"Expected 422, got {r.status_code}"
    print("  -> Passed 422 validation.")

if __name__ == "__main__":
    if os.getenv("RUN_LIVE_API_TESTS") != "1":
        raise SystemExit("Set RUN_LIVE_API_TESTS=1 to run this live integration script.")
    if not os.getenv("TRUTHLENS_ACCESS_TOKEN", "").strip():
        raise SystemExit("TRUTHLENS_ACCESS_TOKEN is required; analysis requests are authenticated.")
    try:
        test_health()
        test_demo_scenarios()
        test_input_validation()
        print("\n==========================================")
        print("ALL E2E INTEGRATION & DEMO TESTS PASSED!")
        print("==========================================")
    except Exception as exc:
        print(f"\nTEST SUITE FAILED: {exc}")
        sys.exit(1)
