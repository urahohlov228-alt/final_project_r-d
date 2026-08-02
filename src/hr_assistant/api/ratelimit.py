"""Sliding-window rate limiter (per client, in memory).

Intentionally simple — one process, one window. For multi-instance
deployments swap for a shared store (Redis) behind the same interface.
"""

import time
from collections import deque


class RateLimiter:
    def __init__(self, limit_per_minute: int):
        self._limit = limit_per_minute
        self._hits: dict[str, deque[float]] = {}

    def allow(self, key: str) -> bool:
        if self._limit <= 0:  # disabled
            return True
        now = time.monotonic()
        window = self._hits.setdefault(key, deque())
        while window and now - window[0] > 60.0:
            window.popleft()
        if len(window) >= self._limit:
            return False
        window.append(now)
        # opportunistic cleanup so abandoned clients don't accumulate
        if len(self._hits) > 10_000:
            for stale in [k for k, w in self._hits.items() if not w]:
                del self._hits[stale]
        return True
