import uuid

from fastapi import APIRouter, status
from sqlalchemy.exc import IntegrityError

from app.api.dependencies import EditorTenant, ReaderTenant, SessionDep
from app.api.openapi import errors
from app.api.schemas import CollectionCreate, CollectionResponse, CollectionUpdate
from app.auth.principal import TenantRef
from app.core.errors import ConflictError, NotFoundError
from app.db.models import Collection
from app.repositories.collections import CollectionRepository
from app.repositories.storage_connections import StorageConnectionRepository

router = APIRouter(prefix="/v1/collections", tags=["collections"], responses=errors())


async def ensure_connection_belongs(
    session: SessionDep,
    tenant: TenantRef,
    connection_id: uuid.UUID | None,
) -> None:
    if connection_id is None:
        return
    if await StorageConnectionRepository(session).get(tenant.id, connection_id) is None:
        raise NotFoundError("Storage connection not found")


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create a collection",
    responses=errors(404, 409),
)
async def create_collection(
    body: CollectionCreate,
    tenant: EditorTenant,
    session: SessionDep,
) -> CollectionResponse:
    await ensure_connection_belongs(session, tenant, body.storage_connection_id)
    collection = Collection(tenant_id=tenant.id, **body.model_dump())
    try:
        await CollectionRepository(session).add(collection)
        await session.commit()
    except IntegrityError as error:
        raise ConflictError(f"Collection '{body.slug}' already exists") from error
    return CollectionResponse.model_validate(collection)


@router.get("", summary="List collections")
async def list_collections(tenant: ReaderTenant, session: SessionDep) -> list[CollectionResponse]:
    collections = await CollectionRepository(session).list_for_tenant(tenant.id)
    return [CollectionResponse.model_validate(collection) for collection in collections]


@router.patch(
    "/{slug}",
    summary="Rename a collection or assign its storage bucket",
    responses=errors(404),
)
async def update_collection(
    slug: str,
    body: CollectionUpdate,
    tenant: EditorTenant,
    session: SessionDep,
) -> CollectionResponse:
    collection = await CollectionRepository(session).get_by_slug(tenant.id, slug)
    if collection is None:
        raise NotFoundError(f"Collection '{slug}' does not exist")

    changes = body.model_dump(exclude_unset=True)
    await ensure_connection_belongs(session, tenant, changes.get("storage_connection_id"))
    for name, value in changes.items():
        setattr(collection, name, value)
    await session.commit()
    return CollectionResponse.model_validate(collection)
