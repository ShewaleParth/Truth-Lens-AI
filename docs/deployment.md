# TrustLens AI deployment guide

## Current architecture

The React/Vite frontend authenticates users with Supabase Auth (Google OAuth), then sends a Supabase access token as a bearer token to the FastAPI `POST /api/analyze` endpoint. The backend validates the token by calling Supabase Auth's supported `/auth/v1/user` endpoint with the project URL and publishable key. `GET /api/health` remains public. Search providers and page fetching run in the backend. The Docker image builds the frontend and serves its static files from FastAPI, so it can run as one service; Vercel can instead host the frontend separately.

## Vercel frontend

Create a Vercel project using this repository and set **Root Directory** to `frontend`.

- Framework preset: Vite (or Other if Vercel does not detect it)
- Install command: `npm ci`
- Build command: `npm run build`
- Output directory: `dist`

Set these Vercel environment variables for Production (and Preview only if you intend to test there):

| Variable | Value |
| --- | --- |
| `VITE_API_BASE_URL` | Public HTTPS origin of the deployed FastAPI service, with no `/api` suffix, e.g. `https://api.example.com` |
| `VITE_SUPABASE_URL` | Supabase project URL |
| `VITE_SUPABASE_PUBLISHABLE_KEY` | Supabase publishable/anon client key; this is public client configuration, never a service-role key |

Vite embeds `VITE_*` values in the browser bundle. Never put search-provider keys, Supabase service-role keys, or other server secrets in these variables.

## AWS backend/container

The root `Dockerfile` builds the Vite app and runs FastAPI in a non-root container. The process listens on `0.0.0.0` and honors the hosting platform's `PORT` value. It exposes `/api/health` for health checks. The checked-in Compose file is for a single-container deployment; an AWS ECS service or App Runner service can use the image. No AWS resources have been created or deployed from this project.

Build the image with public frontend configuration (these are browser-visible):

```powershell
docker build `
  --build-arg VITE_API_BASE_URL= `
  --build-arg VITE_SUPABASE_URL=https://YOUR_PROJECT.supabase.co `
  --build-arg VITE_SUPABASE_PUBLISHABLE_KEY=YOUR_PUBLISHABLE_KEY `
  -t trustlens-ai:latest .
```

For a separate Vercel frontend, build `VITE_API_BASE_URL` with the HTTPS API origin instead of leaving it blank. Use the same frontend configuration for `docker compose` by copying the root `.env.example` to `.env`. Do not commit either `.env` file.

Configure these backend runtime variables in the hosting service's secret/configuration store. The local backend environment inspected for this report did not yet define `SUPABASE_URL` or `SUPABASE_PUBLISHABLE_KEY`, so add them locally too before testing authenticated analysis:

| Variable | Required / purpose |
| --- | --- |
| `ENVIRONMENT=production` | Enables production checks and disables API docs |
| `DEBUG=false` | Required in production |
| `HOST=0.0.0.0` | Bind on the container interface |
| `PORT` | Supplied by the host; defaults to `8000` |
| `SUPABASE_URL` | Required server-side for access-token validation |
| `SUPABASE_PUBLISHABLE_KEY` | Required server-side for the Supabase Auth user lookup; not a service-role key |
| `CORS_ORIGINS` | Comma-separated deployed frontend HTTPS origins, e.g. `https://app.example.com`; use an empty list only for same-origin serving |
| `SERPER_API_KEY` | Optional server-side evidence search credential |
| `TAVILY_API_KEY` | Optional server-side evidence search credential |
| `SEARCH_PROVIDER_ORDER` | Defaults to `serper,duckduckgo`; set based on enabled providers |
| `ANALYZE_RATE_LIMIT_REQUESTS` | Per-process per-user limit; defaults to 10 |
| `ANALYZE_RATE_LIMIT_WINDOW_SECONDS` | Per-process limiter window; defaults to 60 seconds |
| `MAX_INPUT_LENGTH` | Maximum claim text size; defaults to 5000 characters |
| `REQUEST_TIMEOUT_SECONDS` | Search/request timeout setting used by services |

Store search keys as runtime secrets, not Docker build arguments. Configure AWS ingress to HTTPS at the service/load-balancer edge. Do not expose an unauthenticated analysis route.

## Supabase and Google OAuth

In Supabase Auth URL configuration, add the production frontend URL (and only the required preview URLs) to allowed redirect URLs. Configure the Google OAuth client with the production frontend origin where required and keep Supabase's callback URL as the redirect URI shown by the Supabase Google provider configuration. The app's existing callback flow remains client-side. No live OAuth login was exercised during this readiness check.

The backend independently requires a valid Supabase access token for every analysis request. An unset/misconfigured Supabase server configuration causes production startup to fail. Ensure the configured project is the same project used by the frontend.

## Security and scale limits to resolve before public production

- The analysis rate limiter is in memory in each process. For AWS, use API Gateway route/stage throttling and/or AWS WAF rate-based rules as a no-application-dependency availability limit; WAF primarily keys by client IP, so it is not equivalent to a shared per-Supabase-user quota. Keep one backend process/replica if the in-process per-user quota is a requirement. A shared per-user quota across replicas would require a shared store/service and is not implemented here.
- Source URL fetching now rejects non-global DNS answers, connects to the validated numeric IP while retaining the original hostname for TLS SNI/certificate checks, and repeats validation/pinning for every redirect. It rejects embedded URL credentials and invalid ports, disables environment proxy inheritance, bounds redirects/body size, and applies connection/read/write plus absolute request deadlines. Keep network egress controls as defense in depth; the platform DNS resolver itself is synchronous and subject to the host OS resolver's timeout behavior.
- The Docker build, deployed container, live Supabase token exchange, Google OAuth callback, and live search providers still require testing in an environment with Docker, network access, and the project's service configuration.
- Python dependencies are bounded in `backend/requirements.txt`, not fully hash-locked. Pin and lock the tested deployment environment before treating rebuilds as byte-for-byte reproducible.

API Gateway and WAF are optional AWS services and can incur usage charges. No paid dependency or cloud resource was added or created for this repository change; use the gateway limits only when the deployment's traffic/security requirements justify that service cost.

## Local checks

From `frontend`, run `npm ci`, `npm run lint`, and `npm run build`. From the repository root, run `python -m pytest backend/tests/ -q`. The API integration portion currently stalls in this Windows environment's async/socket path; run the full suite in Linux CI or another supported environment before release. A browser health check is `GET https://YOUR_API_HOST/api/health`.
