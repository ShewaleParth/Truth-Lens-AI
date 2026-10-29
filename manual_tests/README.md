# Manual live smoke tests

These scripts are deliberately outside the automated `pytest` test path. They make real HTTP/search requests and may consume external provider quota. They never run unless the matching opt-in variable is set.

## Live search-provider smoke test

From the repository root, configure `SERPER_API_KEY` through the backend environment, then explicitly opt in:

```powershell
$env:RUN_LIVE_SEARCH_TESTS = '1'
python manual_tests/claim_evidence_smoke.py
```

The script submits five claim queries to Serper. It prints verdicts and source URLs, but never prints the API key.

## Authenticated API smoke test

Start the backend and set `TRUTHLENS_ACCESS_TOKEN` to a short-lived Supabase user access token obtained through the normal Google login flow. Do not paste or commit the token. Set `TRUTHLENS_API_URL` if the backend is not at `http://127.0.0.1:8000`.

```powershell
$env:RUN_LIVE_API_TESTS = '1'
$env:TRUTHLENS_ACCESS_TOKEN = '<short-lived user access token>'
python manual_tests/live_api_smoke.py
```

This submits three analysis requests and therefore may invoke configured live search providers. The access token is sent only in the Authorization header and is not printed.

The legacy `backend/tests/e2e_live_integration.py` is also a manual integration script. It now requires the same API opt-in and access token before sending any analysis request.
