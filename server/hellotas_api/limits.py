"""Rate limits, kept in memory. Enough for one small server; with several instances, each counts on its own."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException

# action -> (how many, per how many seconds)
LIMITS = {
    "login": (5, 3600),          # sign-in emails per address
    "login_ip": (20, 3600),      # sign-in emails per visitor
    "post": (10, 86400),         # wall posts and opportunities per user
    "ask": (15, 86400),          # buddy requests per user
    "suggest": (8, 86400),       # event suggestions per visitor
    "subscribe": (5, 3600),      # digest sign-ups per visitor
    "report": (20, 86400),
}


class Limiter:
    def __init__(self):
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, action: str, key: str) -> None:
        count, window = LIMITS[action]
        now = time.monotonic()
        with self._lock:
            hits = self._hits[f"{action}:{key}"]
            while hits and now - hits[0] > window:
                hits.popleft()
            if len(hits) >= count:
                retry = int(window - (now - hits[0])) + 1
                raise HTTPException(status_code=429, detail="Too many requests; try again later.",
                                    headers={"Retry-After": str(retry)})
            hits.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
