import logging
from typing import Literal

from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from app.api.dependencies import SessionDep
from app.infra.database import extension_version

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["health"])


class Liveness(BaseModel):
    status: Literal["ok"] = "ok"


class Readiness(BaseModel):
    status: Literal["ready", "unavailable"]
    database: bool
    pgvector: str | None


@router.get("/live", summary="Process is up")
async def live() -> Liveness:
    return Liveness()


@router.get("/ready", summary="Database and pgvector are reachable")
async def ready(session: SessionDep, response: Response) -> Readiness:
    try:
        pgvector = await extension_version(session, "vector")
    except (SQLAlchemyError, OSError):
        logger.exception("Database readiness check failed")
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return Readiness(status="unavailable", database=False, pgvector=None)

    if pgvector is None:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return Readiness(status="unavailable", database=True, pgvector=None)

    return Readiness(status="ready", database=True, pgvector=pgvector)
