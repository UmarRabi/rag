from typing import Any

import pytest
from fakeredis import FakeAsyncRedis
from redis.exceptions import ConnectionError as RedisConnectionError

from app.auth.rate_limit import RateBucket, RedisRateLimiter, limit_for
from app.core.settings import Settings


async def test_requests_over_the_limit_are_refused() -> None:
    limiter = RedisRateLimiter(FakeAsyncRedis())

    decisions = [await limiter.hit("search:key-1", limit=3, window_seconds=60) for _ in range(4)]

    assert [decision.allowed for decision in decisions] == [True, True, True, False]
    assert [decision.remaining for decision in decisions] == [2, 1, 0, 0]
    assert 1 <= decisions[-1].reset_seconds <= 60


async def test_keys_are_counted_separately() -> None:
    limiter = RedisRateLimiter(FakeAsyncRedis())

    await limiter.hit("search:key-1", limit=1, window_seconds=60)

    assert (await limiter.hit("search:key-2", limit=1, window_seconds=60)).allowed


async def test_counters_expire_with_the_window() -> None:
    redis = FakeAsyncRedis()
    await RedisRateLimiter(redis).hit("api:key-1", limit=5, window_seconds=60)

    (counter,) = await redis.keys("rag:ratelimit:api:key-1:*")

    assert 0 < await redis.ttl(counter) <= 60


class BrokenRedis(FakeAsyncRedis):
    def pipeline(self, *args: Any, **kwargs: Any) -> Any:
        raise RedisConnectionError("Redis is down")


async def test_requests_are_allowed_when_redis_is_unavailable() -> None:
    decision = await RedisRateLimiter(BrokenRedis()).hit("api:key-1", limit=1, window_seconds=60)

    assert decision.allowed


@pytest.mark.parametrize(
    ("tenant_settings", "bucket", "limit"),
    [
        ({}, RateBucket.SEARCH, 60),
        ({"rate_limits": {"search": 500}}, RateBucket.SEARCH, 500),
        ({"rate_limits": {"search": 500}}, RateBucket.INGEST, 30),
        ({"rate_limits": {"api": None}}, RateBucket.API, 120),
    ],
)
def test_tenants_can_override_default_limits(
    tenant_settings: dict[str, Any],
    bucket: RateBucket,
    limit: int,
) -> None:
    settings = Settings(rate_limit_search=60, rate_limit_ingest=30, rate_limit_api=120)

    assert limit_for(bucket, tenant_settings, settings) == limit
