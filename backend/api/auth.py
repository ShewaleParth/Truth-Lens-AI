"""Supabase access-token validation for protected API endpoints."""

from __future__ import annotations

import httpx
from fastapi import Header, HTTPException, status

try:
    from backend.config import get_settings
except ModuleNotFoundError:
    from config import get_settings  # type: ignore


async def require_authenticated_user(
    authorization: str | None = Header(default=None),
) -> str:
    """Validate a Supabase access token using Supabase Auth's supported user API.

    Returns the authenticated Supabase user ID. Missing/invalid credentials fail
    closed. Supabase outages are reported as 503 rather than treated as auth.
    Tokens and response bodies are deliberately never logged.
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in with Google to analyze a claim.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A valid bearer access token is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    settings = get_settings()
    supabase_url = (settings.SUPABASE_URL or "").strip().rstrip("/")
    publishable_key = (settings.SUPABASE_PUBLISHABLE_KEY or "").strip()
    if not supabase_url or not publishable_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Server authentication is not configured.",
        )

    try:
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=False) as client:
            response = await client.get(
                f"{supabase_url}/auth/v1/user",
                headers={
                    "apikey": publishable_key,
                    "Authorization": f"Bearer {token.strip()}",
                    "Accept": "application/json",
                },
            )
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service timed out. Please retry shortly.",
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service is temporarily unreachable.",
        ) from exc

    if response.status_code in (401, 403):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Your sign-in session is invalid or expired. Sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if response.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service could not validate the session.",
        )

    try:
        user_id = response.json().get("id")
    except (ValueError, AttributeError):
        user_id = None
    if not isinstance(user_id, str) or not user_id.strip():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service returned an invalid user response.",
        )
    return user_id
