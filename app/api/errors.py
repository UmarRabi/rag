from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.core.errors import (
    ConflictError,
    ForbiddenError,
    InvalidContentError,
    NotFoundError,
    PayloadTooLargeError,
    RateLimitedError,
    ServiceError,
    ServiceUnavailableError,
    UnauthorizedError,
    UnsupportedMediaTypeError,
)

BEARER_CHALLENGE = {"WWW-Authenticate": "Bearer"}

STATUS_CODES: dict[type[ServiceError], int] = {
    NotFoundError: status.HTTP_404_NOT_FOUND,
    ConflictError: status.HTTP_409_CONFLICT,
    InvalidContentError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    UnsupportedMediaTypeError: status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    PayloadTooLargeError: status.HTTP_413_CONTENT_TOO_LARGE,
    UnauthorizedError: status.HTTP_401_UNAUTHORIZED,
    ForbiddenError: status.HTTP_403_FORBIDDEN,
    RateLimitedError: status.HTTP_429_TOO_MANY_REQUESTS,
    ServiceUnavailableError: status.HTTP_503_SERVICE_UNAVAILABLE,
}


def status_code_for(error: ServiceError) -> int:
    for error_type in type(error).__mro__:
        if error_type in STATUS_CODES:
            return STATUS_CODES[error_type]
    return status.HTTP_400_BAD_REQUEST


async def handle_service_error(request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, ServiceError)
    headers = error.headers | (BEARER_CHALLENGE if isinstance(error, UnauthorizedError) else {})
    return JSONResponse(
        status_code=status_code_for(error),
        content={"detail": error.message},
        headers=headers,
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ServiceError, handle_service_error)
