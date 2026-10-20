import uuid

from fastapi import APIRouter, Response, status
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from app.api.dependencies import AdminTenant, CipherDep, SessionDep, StorageDep
from app.api.openapi import errors
from app.api.schemas import StorageConnectionCreate, StorageConnectionResponse
from app.auth.principal import TenantRef
from app.core.errors import ConflictError, NotFoundError
from app.db.models import StorageConnection
from app.domain.enums import StorageAuthType
from app.repositories.storage_connections import StorageConnectionRepository
from app.storage.crypto import SecretCipher
from app.storage.verification import verify_connection

router = APIRouter(prefix="/v1/storage-connections", tags=["storage"], responses=errors())


def encrypted_credentials(body: StorageConnectionCreate, cipher: SecretCipher) -> bytes | None:
    if body.auth_type is not StorageAuthType.ACCESS_KEY:
        return None
    assert body.access_key_id is not None
    assert body.secret_access_key is not None
    return cipher.encrypt(
        {
            "access_key_id": body.access_key_id,
            "secret_access_key": body.secret_access_key.get_secret_value(),
        },
    )


async def tenant_connection(
    session: SessionDep,
    tenant: TenantRef,
    connection_id: uuid.UUID,
) -> StorageConnection:
    connection = await StorageConnectionRepository(session).get(tenant.id, connection_id)
    if connection is None:
        raise NotFoundError("Storage connection not found")
    return connection


async def clear_default(session: SessionDep, tenant: TenantRef) -> None:
    await session.execute(
        update(StorageConnection)
        .where(StorageConnection.tenant_id == tenant.id, StorageConnection.is_default)
        .values(is_default=False),
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Connect a bucket and verify access",
    responses=errors(409, 503),
)
async def create_storage_connection(
    body: StorageConnectionCreate,
    tenant: AdminTenant,
    session: SessionDep,
    storage: StorageDep,
    cipher: CipherDep,
) -> StorageConnectionResponse:
    connection = StorageConnection(
        tenant_id=tenant.id,
        credentials_encrypted=encrypted_credentials(body, cipher),
        **body.model_dump(exclude={"access_key_id", "secret_access_key"}),
    )
    if body.is_default:
        await clear_default(session, tenant)
    try:
        await StorageConnectionRepository(session).add(connection)
    except IntegrityError as error:
        raise ConflictError(f"Storage connection '{body.name}' already exists") from error

    await verify_connection(storage, connection)
    await session.commit()
    return StorageConnectionResponse.model_validate(connection)


@router.get("", summary="List storage connections")
async def list_storage_connections(
    tenant: AdminTenant,
    session: SessionDep,
) -> list[StorageConnectionResponse]:
    connections = await StorageConnectionRepository(session).list_for_tenant(tenant.id)
    return [StorageConnectionResponse.model_validate(connection) for connection in connections]


@router.post(
    "/{connection_id}/verify",
    summary="Re-check access to a bucket",
    responses=errors(404),
)
async def verify_storage_connection(
    connection_id: uuid.UUID,
    tenant: AdminTenant,
    session: SessionDep,
    storage: StorageDep,
) -> StorageConnectionResponse:
    connection = await tenant_connection(session, tenant, connection_id)
    await verify_connection(storage, connection)
    await session.commit()
    return StorageConnectionResponse.model_validate(connection)


@router.delete(
    "/{connection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove an unused storage connection",
    responses=errors(404, 409),
)
async def delete_storage_connection(
    connection_id: uuid.UUID,
    tenant: AdminTenant,
    session: SessionDep,
) -> Response:
    repository = StorageConnectionRepository(session)
    connection = await tenant_connection(session, tenant, connection_id)
    if await repository.in_use(connection):
        raise ConflictError("Storage connection is still used by collections or documents")
    await session.delete(connection)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
