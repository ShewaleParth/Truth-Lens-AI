"""Small bounded per-process limiter for authenticated claim analysis."""

from __future__ import annotations

import math
import threading
import time
from collections import deque

from fastapi import HTTPException, status


class UserRateLimiter:
    """Thread-safe sliding-window limiter keyed by authenticated user ID.

    State is intentionally bounded and process-local. Production deployments
    with multiple workers or replicas must also apply a shared edge limiter.
    """

    def __init__(self, max_tracked_users: int = 10_000) -> None:
        self._events: dict[str, deque[float]] = {}
        self._max_tracked_users = max_tracked_users
        self._lock = threading.Lock()

    def check(self, user_id: str, limit: int, window_seconds: int) -> None:
        now = time.monotonic()
        window = max(1, int(window_seconds))
        allowed = max(1, int(limit))
        cutoff = now - window

        with self._lock:
            events = self._events.get(user_id)
            if events is None:
                if len(self._events) >= self._max_tracked_users:
                    self._discard_expired(cutoff)
                if len(self._events) >= self._max_tracked_users:
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail="Analysis capacity is temporarily limited. Retry shortly.",
                        headers={"Retry-After": str(window)},
                    )
                events = self._events.setdefault(user_id, deque())

            while events and events[0] <= cutoff:
                events.popleft()

            if len(events) >= allowed:
                retry_after = max(1, math.ceil(window - (now - events[0])))
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Analysis rate limit reached. Wait before submitting another claim.",
                    headers={"Retry-After": str(retry_after)},
                )
            events.append(now)

    def clear(self) -> None:
        """Clear tracked events; intended for deterministic tests."""
        with self._lock:
            self._events.clear()

    def _discard_expired(self, cutoff: float) -> None:
        for key, events in list(self._events.items()):
            while events and events[0] <= cutoff:
                events.popleft()
            if not events:
                self._events.pop(key, None)


analysis_rate_limiter = UserRateLimiter()
