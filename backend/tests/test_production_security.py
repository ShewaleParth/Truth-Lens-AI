"""Regression coverage for protected analysis and deployment safeguards."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from backend.api import auth as auth_module
from backend.api.auth import require_authenticated_user
from backend.api.rate_limit import UserRateLimiter
from backend.api.routes import require_analysis_access, router
from backend.core.models import AnalysisResult


def test_missing_access_token_is_rejected_without_contacting_supabase() -> None:
    with pytest.raises(HTTPException) as exc:
        asyncio.run(require_authenticated_user(None))
    assert exc.value.status_code == 401


def test_invalid_supabase_access_token_is_rejected() -> None:
    class Response:
        status_code = 401

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, *args, **kwargs):
            return Response()

    settings = SimpleNamespace(
        SUPABASE_URL="https://project.example.supabase.co",
        SUPABASE_PUBLISHABLE_KEY="test-publishable-key",
    )
    with patch.object(auth_module, "get_settings", return_value=settings), patch.object(
        auth_module.httpx, "AsyncClient", return_value=Client()
    ):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(require_authenticated_user("Bearer invalid-token"))
    assert exc.value.status_code == 401


def test_expired_supabase_access_token_is_rejected() -> None:
    class Response:
        status_code = 401

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, *args, **kwargs):
            # Supabase Auth returns 401 for an expired session as well as an
            # invalid token; the backend must reject both without fabricating a user.
            return Response()

    settings = SimpleNamespace(
        SUPABASE_URL="https://project.example.supabase.co",
        SUPABASE_PUBLISHABLE_KEY="test-publishable-key",
    )
    with patch.object(auth_module, "get_settings", return_value=settings), patch.object(
        auth_module.httpx, "AsyncClient", return_value=Client()
    ):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(require_authenticated_user("Bearer expired-token"))
    assert exc.value.status_code == 401


def test_valid_supabase_token_resolves_to_user_id() -> None:
    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {"id": "user-123"}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, headers):
            assert url == "https://project.example.supabase.co/auth/v1/user"
            assert headers["Authorization"] == "Bearer valid-token"
            return Response()

    settings = SimpleNamespace(
        SUPABASE_URL="https://project.example.supabase.co/",
        SUPABASE_PUBLISHABLE_KEY="test-publishable-key",
    )
    with patch.object(auth_module, "get_settings", return_value=settings), patch.object(
        auth_module.httpx, "AsyncClient", return_value=Client()
    ):
        user_id = asyncio.run(require_authenticated_user("Bearer valid-token"))
    assert user_id == "user-123"


def test_analysis_limit_returns_429_after_configured_window_budget() -> None:
    limiter = UserRateLimiter()
    limiter.check("user-123", limit=1, window_seconds=60)
    with pytest.raises(HTTPException) as exc:
        limiter.check("user-123", limit=1, window_seconds=60)
    assert exc.value.status_code == 429
    assert exc.value.headers["Retry-After"]


def test_analyze_route_rejects_requests_without_authentication() -> None:
    app = FastAPI()
    app.include_router(router, prefix="/api")

    async def request():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return await client.post("/api/analyze", json={"text": "A claim to check."})

    response = asyncio.run(request())
    assert response.status_code == 401


def test_internal_analysis_error_is_http_500_not_an_unverified_verdict(monkeypatch) -> None:
    from backend.api import routes

    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[require_authenticated_user] = lambda: "test-user"
    app.dependency_overrides[require_analysis_access] = lambda: "test-user"
    monkeypatch.setattr(
        routes,
        "analyse_claim",
        lambda text: AnalysisResult(
            request_id="internal-error-test",
            status="error",
            original_text=text,
        ),
    )

    async def request():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return await client.post("/api/analyze", json={"text": "A claim to check."})

    response = asyncio.run(request())
    assert response.status_code == 500
    assert "internal processing error" in response.json()["detail"]
