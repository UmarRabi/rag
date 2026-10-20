import asyncio
from dataclasses import asdict

from fastapi import APIRouter, Request
from starlette.datastructures import UploadFile

from app.api.dependencies import ImageSearchServiceDep, SearchTenant, SettingsDep
from app.api.openapi import IMAGE_SEARCH_DESCRIPTION, errors
from app.api.requests import (
    JSON_CONTENT,
    MULTIPART_CONTENT,
    content_type_of,
    json_body,
    validated,
)
from app.api.schemas import (
    ImageResult,
    ImageSearchFields,
    ImageSearchRequest,
    ImageSearchResponse,
)
from app.auth.principal import TenantRef
from app.core.errors import InvalidContentError, UnsupportedMediaTypeError
from app.core.settings import Settings
from app.domain.enums import MediaType
from app.ingestion.content import fingerprint
from app.pipelines.detection import SNIFF_BYTES, detect
from app.pipelines.image import load_image
from app.search.images import ImageHit, ImageQuery, ImageSearchService

IMAGE_FIELD = "image"

MULTIPART_SCHEMA = {
    "type": "object",
    "required": [IMAGE_FIELD],
    "properties": {
        IMAGE_FIELD: {"type": "string", "format": "binary", "description": "PNG, JPEG, WebP..."},
        "collections": {"type": "string", "description": "Comma separated collection slugs"},
        "top_k": {"type": "integer", "default": 5},
        "filters": {"type": "string", "description": "JSON object matched against metadata"},
    },
}

IMAGE_SEARCH_BODY = {
    "requestBody": {
        "required": True,
        "content": {
            JSON_CONTENT: {"schema": ImageSearchRequest.model_json_schema()},
            MULTIPART_CONTENT: {"schema": MULTIPART_SCHEMA},
        },
    },
}

router = APIRouter(prefix="/v1/search", tags=["search"], responses=errors(404, 413, 415, 503))


def image_query(settings: Settings, fields: ImageSearchFields | ImageSearchRequest) -> ImageQuery:
    return ImageQuery(
        top_k=fields.top_k,
        candidates=settings.search_candidates(fields.top_k),
        collections=fields.collections,
        filters=fields.filters,
        min_score=fields.min_score,
    )


def respond(hits: list[ImageHit]) -> ImageSearchResponse:
    return ImageSearchResponse(results=[ImageResult.model_validate(asdict(hit)) for hit in hits])


async def search_by_text(
    request: Request,
    tenant: TenantRef,
    service: ImageSearchService,
    settings: Settings,
) -> ImageSearchResponse:
    body = validated(ImageSearchRequest, await json_body(request))
    query = image_query(settings, body)
    return respond(await service.by_text(tenant, body.query, query))


async def search_by_image(
    request: Request,
    tenant: TenantRef,
    service: ImageSearchService,
    settings: Settings,
) -> ImageSearchResponse:
    async with request.form(max_files=1) as form:
        upload = form.get(IMAGE_FIELD)
        if not isinstance(upload, UploadFile):
            raise InvalidContentError(f"Upload the query image in the '{IMAGE_FIELD}' field")
        fields = validated(
            ImageSearchFields,
            {name: value for name, value in form.items() if isinstance(value, str)},
        )
        await asyncio.to_thread(fingerprint, upload.file, settings.max_document_bytes)
        detected = detect(upload.file.read(SNIFF_BYTES), upload.content_type, upload.filename)
        if detected.media_type is not MediaType.IMAGE:
            raise UnsupportedMediaTypeError("The query file must be an image")
        upload.file.seek(0)
        image = await asyncio.to_thread(load_image, upload.file.read())

    query = image_query(settings, fields)
    return respond(await service.by_image(tenant, image, query))


@router.post(
    "/images",
    summary="Search images by description or by example",
    description=IMAGE_SEARCH_DESCRIPTION,
    openapi_extra=IMAGE_SEARCH_BODY,
)
async def search_images(
    request: Request,
    tenant: SearchTenant,
    service: ImageSearchServiceDep,
    settings: SettingsDep,
) -> ImageSearchResponse:
    content_type = content_type_of(request)
    if content_type == JSON_CONTENT:
        return await search_by_text(request, tenant, service, settings)
    if content_type == MULTIPART_CONTENT:
        return await search_by_image(request, tenant, service, settings)
    raise UnsupportedMediaTypeError(
        f"Send {JSON_CONTENT} with a query or {MULTIPART_CONTENT} with an image",
    )
