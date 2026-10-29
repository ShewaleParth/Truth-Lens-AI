# TrustLens AI — First Push and Deployment Checklist

## Before the first commit

- [ ] Review `git status --short`; this repository currently has no commits and the project files are untracked.
- [ ] Select only intended source, docs, workflow and deployment files. Do not stage `backend/.env`, `frontend/.env`, caches, `node_modules`, `frontend/dist`, databases or local output.
- [ ] Confirm `git check-ignore backend/.env frontend/.env` still ignores both local environment files.
- [ ] Review the complete staged diff before committing. This task did not stage, commit, add a remote, or push.
- [ ] Run the Linux GitHub workflow after pushing and resolve any failures before deployment.

## Local verification outstanding

- [ ] Run `python -m pytest backend/tests -q` on Linux. The full backend suite hangs in Windows Proactor socketpair setup before an ASGI health request; 62 deterministic focused tests and one limiter test passed locally.
- [ ] Build/run the root Dockerfile and verify `/api/health`. Docker is unavailable in this workspace.
- [ ] Complete a real Supabase Google OAuth round-trip and authenticated analysis request. Mocked token tests exist; the live project flow was not exercised.
- [ ] Test configured Serper/Tavily/DuckDuckGo externally only when credentials/network are available. Set `SEARCH_PROVIDER_ORDER=none` to disable outbound search; no-op must not contact providers.
- [ ] Generate a pinned/hash-locked Python dependency file after package-index access is available. Current Python requirements are bounded ranges, not a complete lock; PyPI DNS resolution prevented generating a trustworthy lock here.
- [ ] If deploying multiple workers/replicas, add gateway/WAF rate limiting or a shared quota store. The current limiter is process-local.

## Vercel frontend

- [ ] Root directory: `frontend`.
- [ ] Install command: `npm ci`.
- [ ] Build command: `npm run build`.
- [ ] Output directory: `dist`.
- [ ] Set `VITE_API_BASE_URL` to the backend's HTTPS origin (without `/api`).
- [ ] Set `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY`. The publishable key is intended for the browser; never use a service-role key.
- [ ] Add production and required preview redirect URLs in Supabase Auth; verify the Google provider callback configuration for the actual deployed hostname.
- [ ] Test Google login, session restore, authenticated analyze, sign-out, expired/invalid session and API-error display.

## Backend runtime (App Runner or ECS)

Supply runtime configuration through the host's secret/config store, not the image:

| Variable | Purpose |
|---|---|
| `ENVIRONMENT` | Set to `production`. |
| `DEBUG` | Set to `false`. |
| `HOST` | Set to `0.0.0.0`. |
| `PORT` | Host-injected port, default `8000`. |
| `SUPABASE_URL` | Supabase project URL used for server-side token validation. |
| `SUPABASE_PUBLISHABLE_KEY` | Public/publishable key for Auth user lookup; do not use service-role credentials. |
| `CORS_ORIGINS` | Exact deployed HTTPS frontend origins; empty only for same-origin hosting. |
| `SEARCH_PROVIDER_ORDER` | Provider order such as `serper,duckduckgo`; set `none` to disable external search. |
| `SERPER_API_KEY` | Optional server-side Serper key if enabled. |
| `TAVILY_API_KEY` | Optional server-side Tavily key if enabled. |
| `ANALYZE_RATE_LIMIT_REQUESTS` | Per-process request budget; default `10`. |
| `ANALYZE_RATE_LIMIT_WINDOW_SECONDS` | Per-process window; default `60`. |
| `MAX_INPUT_LENGTH` | Claim length limit; default `5000`. |
| `REQUEST_TIMEOUT_SECONDS` | Request-wide analysis timeout; default `15.0`. |

- [ ] Build and run the container with TLS termination and `/api/health` checks.
- [ ] Keep the per-user limiter on one worker/replica or add an aggregate gateway/WAF limit; process memory is not shared.
- [ ] Restrict outbound egress as defense in depth; code checks and pins public resolutions and revalidates redirects, but OS resolver behavior is host-controlled.
- [ ] Verify the service is non-root and the image contains no local `.env`, credentials or local test artifacts.
- [ ] Confirm production startup fails clearly when required Supabase config is absent and succeeds when configured.
- [ ] Verify `/api/analyze` rejects missing, invalid and expired tokens and accepts a valid Supabase user token.
- [ ] Verify retrieval/provider failure remains distinguishable from `UNVERIFIED`, and heuristic scam risk stays separate from factual verdict.

## Release gate

- [ ] Linux backend suite passes in GitHub Actions.
- [ ] Frontend lint, TypeScript and production build pass in CI.
- [ ] Docker build and container health check pass in CI.
- [ ] Real OAuth and authenticated API flow pass in deployed staging.
- [ ] Search behavior has been tested or explicitly disabled and communicated.
- [ ] Shared/public traffic protections, secrets, logs, monitoring and rollback are configured.

Until those checks are complete, the project is suitable for GitHub CI validation but not deployment.
