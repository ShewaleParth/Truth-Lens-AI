"""Synchronous test helper using HTTPX's in-process ASGI transport.

This avoids binding loopback sockets for tests and remains equivalent for the
application's request/response API surface.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx


class InProcessTestClient:
    def __init__(self, app: Any, base_url: str = "http://testserver") -> None:
        self._app = app
        self._base_url = base_url

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        async def send() -> httpx.Response:
            transport = httpx.ASGITransport(app=self._app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url=self._base_url,
            ) as client:
                return await client.request(method, url, **kwargs)

        return asyncio.run(send())

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", url, **kwargs)
