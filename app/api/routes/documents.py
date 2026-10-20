import uuid
from pathlib import PurePosixPath

from fastapi import APIRouter, Response, status
from fastapi.responses import RedirectResponse

from app.api.dependencies import (
    EditorTenant,
    IngestionServiceDep,
    ReaderTenant,
    SessionDep,
    SettingsDep,
    StorageDep,
)
from app.api.openapi import errors
from app.api.schemas import DocumentResponse
from app.auth.principal import TenantRef
from app.core.errors import NotFoundError
from app.db.models import Document
from app.repositories.documents import DocumentRepository
from app.repositories.storage_connections import StorageConnectionRepository
from app.storage.base import StorageLocation

router = APIRouter(prefix="/v1/documents", tags=["documents"], responses=errors(404))


async def tenant_document(
    session: SessionDep, tenant: TenantRef, document_id: uuid.UUID
) -> Document:
    document = await DocumentRepository(session).get(tenant.id, document_id)
    if document is None:
        raise NotFoundError("Document not found")
    return document


@router.get("/{document_id}", summary="Get a document's processing status and details")
async def get_document(
    document_id: uuid.UUID,
    tenant: ReaderTenant,
    session: SessionDep,
) -> DocumentResponse:
    return DocumentResponse.model_validate(await tenant_document(session, tenant, document_id))


@router.get(
    "/{document_id}/file",
    summary="Download the original file",
    description=(
        "Redirects (307) to a short-lived presigned URL when the file is in S3. "
        "With local storage the file is returned directly."
    ),
    response_class=Response,
    responses={
        status.HTTP_200_OK: {"description": "The original file"},
        status.HTTP_307_TEMPORARY_REDIRECT: {"description": "Presigned download URL"},
    },
)
async def download_document(
    document_id: uuid.UUID,
    tenant: ReaderTenant,
    session: SessionDep,
    storage: StorageDep,
    settings: SettingsDep,
) -> Response:
    document = await tenant_document(session, tenant, document_id)
    if document.storage_uri is None:
        raise NotFoundError("Document has no stored file")

    connection = await StorageConnectionRepository(session).by_id(document.storage_connection_id)
    object_storage = await storage.for_connection(connection, require_verified=False)
    location = StorageLocation.parse(document.storage_uri)
    url = await object_storage.presigned_url(location, settings.storage_presigned_url_seconds)
    if url is not None:
        return RedirectResponse(url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)

    filename = PurePosixPath(location.key).name
    return Response(
        content=await object_storage.get(location),
        media_type=document.mime_type or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post(
    "/{document_id}/reprocess",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Process a document again",
    description="Re-extracts, re-chunks and re-embeds the stored original, e.g. after a model "
    "or chunking change.",
)
async def reprocess_document(
    document_id: uuid.UUID,
    tenant: EditorTenant,
    service: IngestionServiceDep,
) -> DocumentResponse:
    return DocumentResponse.model_validate(await service.reprocess(tenant, document_id))


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a document, its chunks and its stored file",
)
async def delete_document(
    document_id: uuid.UUID,
    tenant: EditorTenant,
    service: IngestionServiceDep,
) -> Response:
    await service.delete(tenant, document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
