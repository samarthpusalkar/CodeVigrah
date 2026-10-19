"""A tiny in-memory sliding-window rate limiter, keyed by (bucket, client IP).

Good enough for one process on one machine. Behind a load balancer or with several workers you would move this
to a shared store such as Redis.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, window_seconds: float = 3600.0, clock=time.monotonic):
        self.window = window_seconds
        self.clock = clock
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, bucket: str, client: str, limit: int) -> bool:
        """Record a hit and return True if it is within ``limit`` per window (``limit <= 0`` means unlimited)."""
        if limit <= 0:
            return True
        now = self.clock()
        with self._lock:
            q = self._hits[(bucket, client)]
            while q and q[0] <= now - self.window:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            if len(self._hits) > 10_000:  # forget idle clients so memory stays bounded
                for key in [k for k, v in self._hits.items() if not v or v[-1] <= now - self.window]:
                    del self._hits[key]
            return True

    def retry_after(self, bucket: str, client: str) -> int:
        with self._lock:
            q = self._hits.get((bucket, client))
            return max(1, int(q[0] + self.window - self.clock())) if q else 1
