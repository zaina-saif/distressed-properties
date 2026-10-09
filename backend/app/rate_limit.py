"""Per-user rate limits for routes that are costly or would let one account
copy the database (Excel export, property photos, the property list).

Counts are kept in memory, which suits the single API instance on Railway;
with several instances each would count separately (a shared store such as
Redis would then be needed).
"""
from __future__ import annotations

import math
import time
from collections import defaultdict, deque
from typing import Callable

from fastapi import Depends, HTTPException

from app.auth import Access, require_access

_hits: dict[tuple[str, str], deque] = defaultdict(deque)


def check(bucket: str, key: str, limit: int, window: int, now: float | None = None) -> float | None:
    """Record a hit; return None if allowed, else the seconds until the next hit is allowed."""
    now = time.time() if now is None else now
    hits = _hits[(bucket, key)]
    while hits and now - hits[0] >= window:
        hits.popleft()
    if len(hits) >= limit:
        return window - (now - hits[0])
    hits.append(now)
    return None


def per_user(bucket: str, limit: int, window: int = 3600) -> Callable[..., Access]:
    """A dependency that allows `limit` requests per user per `window` seconds."""
    def dependency(access: Access = Depends(require_access)) -> Access:
        if access.is_developer:
            return access
        wait = check(bucket, access.user_id, limit, window)
        if wait is not None:
            raise HTTPException(status_code=429, detail="Too many requests. Please wait a little and try again.",
                                headers={"Retry-After": str(math.ceil(wait))})
        return access
    return dependency
