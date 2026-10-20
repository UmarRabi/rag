import io

from fastapi import APIRouter, Request, status
from fastapi.exceptions import RequestValidationError
from starlette.datastructures import UploadFile

from app.api.dependencies import IngestionServiceDep, IngestTenant, SettingsDep
from app.api.openapi import INGEST_DESCRIPTION, errors
from app.api.requests import (
    JSON_CONTENT,
    MULTIPART_CONTENT,
    content_type_of,
    json_body,
    validated,
)
from app.api.schemas import FileIngestFields, IngestResponse, TextIngestRequest
from app.auth.principal import TenantRef
from app.core.errors import PayloadTooLargeError, UnsupportedMediaTypeError
from app.domain.enums import SourceType
from app.ingestion.content import IncomingContent
from app.ingestion.service import IngestionRequest, IngestionService

FILE_FIELD = "file"
MAX_FORM_FIELDS = 10

MULTIPART_SCHEMA = {
    "type": "object",
    "required": [FILE_FIELD, "collection"],
    "properties": {
        FILE_FIELD: {
            "type": "string",
            "format": "binary",
            "description": "PDF, DOCX, PPTX, XLSX, HTML, Markdown, CSV, JSON or text",
        },
        "collection": {"type": "string", "description": "Collection slug", "example": "support"},
        "title": {"type": "string", "description": "Defaults to the file name"},
        "external_id": {
            "type": "string",
            "description": "Your own ID; reusing it replaces the document",
            "example": "kb-42",
        },
        "metadata": {
            "type": "string",
            "description": "JSON object used for search filters",
            "example": '{"audience": "public", "product": "router-x"}',
        },
    },
}

INGEST_BODY = {
    "requestBody": {
        "required": True,
        "content": {
            JSON_CONTENT: {"schema": TextIngestRequest.model_json_schema()},
            MULTIPART_CONTENT: {"schema": MULTIPART_SCHEMA},
        },
    },
}

router = APIRouter(prefix="/v1", tags=["ingest"], responses=errors(404, 409, 413, 415))


def missing_file() -> RequestValidationError:
    return RequestValidationError(
        [{"type": "missing", "loc": ("body", FILE_FIELD), "msg": "Field required", "input": None}],
    )


async def ingest_text(
    request: Request,
    tenant: TenantRef,
    service: IngestionService,
    max_bytes: int,
) -> IngestResponse:
    body = validated(TextIngestRequest, await json_body(request))
    data = body.text.encode()
    if len(data) > max_bytes:
        raise PayloadTooLargeError(f"Text exceeds {max_bytes} bytes")

    ingestion = IngestionRequest(
        collection=body.collection,
        content=IncomingContent(io.BytesIO(data), body.mime_type),
        source_type=SourceType.TEXT,
        title=body.title,
        external_id=body.external_id,
        metadata=body.metadata,
    )
    return IngestResponse.from_outcome(await service.ingest(tenant, ingestion))


async def ingest_file(
    request: Request,
    tenant: TenantRef,
    service: IngestionService,
) -> IngestResponse:
    async with request.form(max_files=1, max_fields=MAX_FORM_FIELDS) as form:
        upload = form.get(FILE_FIELD)
        if not isinstance(upload, UploadFile):
            raise missing_file()

        fields = {name: value for name, value in form.items() if isinstance(value, str)}
        body = validated(FileIngestFields, fields)
        ingestion = IngestionRequest(
            collection=body.collection,
            content=IncomingContent(upload.file, upload.content_type, upload.filename),
            source_type=SourceType.UPLOAD,
            title=body.title,
            external_id=body.external_id,
            metadata=body.metadata,
        )
        return IngestResponse.from_outcome(await service.ingest(tenant, ingestion))


@router.post(
    "/ingest",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ingest text or a file",
    description=INGEST_DESCRIPTION,
    openapi_extra=INGEST_BODY,
)
async def ingest(
    request: Request,
    tenant: IngestTenant,
    service: IngestionServiceDep,
    settings: SettingsDep,
) -> IngestResponse:
    content_type = content_type_of(request)
    if content_type == JSON_CONTENT:
        return await ingest_text(request, tenant, service, settings.max_text_bytes)
    if content_type == MULTIPART_CONTENT:
        return await ingest_file(request, tenant, service)
    raise UnsupportedMediaTypeError(
        f"Send {JSON_CONTENT} for text or {MULTIPART_CONTENT} for files"
    )
