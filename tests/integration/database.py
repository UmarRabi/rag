import asyncio
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Row, pool, text
from sqlalchemy.ext.asyncio import create_async_engine


async def _run(url: str, statement: str, params: dict[str, Any]) -> Sequence[Row[Any]]:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.begin() as connection:
            result = await connection.execute(text(statement), params)
            return result.fetchall() if result.returns_rows else []
    finally:
        await engine.dispose()


def run_sql(url: str, statement: str, **params: Any) -> Sequence[Row[Any]]:
    return asyncio.run(_run(url, statement, params))
