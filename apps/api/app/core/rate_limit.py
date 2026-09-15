"""In-process and Redis-backed rate limits. Auth endpoints always enforce a limit."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import HTTPException, status

from app.core.config import get_settings

_memory: dict[str, deque[float]] = defaultdict(deque)
_lock = Lock()


def _prune(bucket: deque[float], window: float, now: float) -> None:
    while bucket and now - bucket[0] > window:
        bucket.popleft()


def _allow_memory(key: str, limit: int, window: float) -> bool:
    now = time.monotonic()
    with _lock:
        bucket = _memory[key]
        _prune(bucket, window, now)
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        return True


def _allow_redis(key: str, limit: int, window: int) -> bool | None:
    settings = get_settings()
    try:
        import redis

        client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=0.4, socket_timeout=0.4)
        pipe = client.pipeline()
        pipe.incr(key)
        pipe.expire(key, window, nx=True)
        count, _ = pipe.execute()
        return int(count) <= limit
    except Exception:  # noqa: BLE001 — fall back to memory
        return None


def enforce_rate_limit(*, key: str, limit: int, window_seconds: int, fail_closed: bool = False) -> None:
    if get_settings().environment == "test":
        return
    redis_ok = _allow_redis(f"rl:{key}", limit, window_seconds)
    allowed = redis_ok if redis_ok is not None else _allow_memory(key, limit, float(window_seconds))
    if redis_ok is None and fail_closed and get_settings().environment == "production":
        allowed = _allow_memory(key, limit, float(window_seconds))
    if not allowed:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many requests")
