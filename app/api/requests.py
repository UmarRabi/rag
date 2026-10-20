from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ValidationError

JSON_CONTENT = "application/json"
MULTIPART_CONTENT = "multipart/form-data"


def content_type_of(request: Request) -> str:
    return request.headers.get("content-type", "").split(";", 1)[0].strip().lower()


def validated[ModelT: BaseModel](model: type[ModelT], data: Any) -> ModelT:
    try:
        return model.model_validate(data)
    except ValidationError as error:
        raise RequestValidationError(error.errors()) from error


async def json_body(request: Request) -> Any:
    try:
        return await request.json()
    except ValueError as error:
        raise RequestValidationError(
            [{"type": "json_invalid", "loc": ("body",), "msg": "Invalid JSON", "input": None}],
        ) from error
