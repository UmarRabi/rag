import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.settings import Settings

logger = logging.getLogger(__name__)

KEY_NAMESPACE = "rag:ratelimit"


class RateBucket(StrEnum):
    SEARCH = "search"
    INGEST = "ingest"
    API = "api"


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    reset_seconds: int

    def headers(self) -> dict[str, str]:
        return {
            "X-RateLimit-Limit": str(self.limit),
            "X-RateLimit-Remaining": str(self.remaining),
            "X-RateLimit-Reset": str(self.reset_seconds),
        }


class RateLimiter(Protocol):
    async def hit(self, key: str, limit: int, window_seconds: int) -> RateLimitDecision: ...


class RedisRateLimiter:
    def __init__(self, redis: Redis, namespace: str = KEY_NAMESPACE) -> None:
        self._redis = redis
        self._namespace = namespace

    async def hit(self, key: str, limit: int, window_seconds: int) -> RateLimitDecision:
        now = time.time()
        window = int(now // window_seconds)
        reset_seconds = max(1, window_seconds - int(now % window_seconds))
        counter = f"{self._namespace}:{key}:{window}"
        try:
            async with self._redis.pipeline(transaction=True) as pipeline:
                pipeline.incr(counter)
                pipeline.expire(counter, window_seconds, nx=True)
                count, _ = await pipeline.execute()
        except RedisError:
            logger.warning("Rate limiter unavailable; allowing request", exc_info=True)
            return RateLimitDecision(True, limit, limit, reset_seconds)

        return RateLimitDecision(
            allowed=count <= limit,
            limit=limit,
            remaining=max(limit - count, 0),
            reset_seconds=reset_seconds,
        )


class UnlimitedRateLimiter:
    async def hit(self, key: str, limit: int, window_seconds: int) -> RateLimitDecision:
        return RateLimitDecision(True, limit, limit, window_seconds)


def limit_for(bucket: RateBucket, tenant_settings: Mapping[str, Any], settings: Settings) -> int:
    defaults = {
        RateBucket.SEARCH: settings.rate_limit_search,
        RateBucket.INGEST: settings.rate_limit_ingest,
        RateBucket.API: settings.rate_limit_api,
    }
    overrides = tenant_settings.get("rate_limits") or {}
    override = overrides.get(bucket.value)
    return int(override) if override is not None else defaults[bucket]
