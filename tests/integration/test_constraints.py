import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ApiKey, Chunk, Document, Tenant
from tests.integration.factories import (
    make_chunk,
    make_collection,
    make_document,
    make_tenant,
    persist,
    storage_connection,
)

UUID_VERSION = 7


async def assert_rejected(session: AsyncSession, statement: str) -> None:
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            await session.execute(text(statement))


async def test_generated_ids_are_time_ordered(session: AsyncSession) -> None:
    first = await make_tenant(session, "first")
    second = await make_tenant(session, "second")

    assert first.id.version == second.id.version == UUID_VERSION
    assert first.id < second.id


async def test_search_vector_follows_text_search_config(session: AsyncSession) -> None:
    collection = await make_collection(session, await make_tenant(session))
    document = await make_document(session, collection)
    await make_chunk(session, document, "Resetting passwords", text_search_config="english")

    matches = await session.scalar(
        select(func.count())
        .select_from(Chunk)
        .where(Chunk.search_vector.op("@@")(func.plainto_tsquery("english", "reset password"))),
    )

    assert matches == 1


async def test_unknown_document_status_is_rejected(session: AsyncSession) -> None:
    collection = await make_collection(session, await make_tenant(session))
    await make_document(session, collection)

    await assert_rejected(session, "UPDATE documents SET status = 'archived'")


async def test_identical_content_in_a_collection_is_rejected(session: AsyncSession) -> None:
    collection = await make_collection(session, await make_tenant(session))
    await make_document(session, collection, "Refund policy")

    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            await make_document(session, collection, "Refund policy")


async def test_identical_content_is_allowed_across_collections(session: AsyncSession) -> None:
    tenant = await make_tenant(session)
    support = await make_collection(session, tenant, "support")
    internal = await make_collection(session, tenant, "internal")

    collections = (support, internal)
    for collection in collections:
        await make_document(session, collection, "Refund policy")

    assert await session.scalar(select(func.count()).select_from(Document)) == len(collections)


async def test_api_key_scopes_must_be_known(session: AsyncSession) -> None:
    tenant = await make_tenant(session)
    await persist(
        session,
        ApiKey(tenant_id=tenant.id, name="Widget", prefix="rag_a", key_hash="h", scopes=["search"]),
    )

    await assert_rejected(session, "UPDATE api_keys SET scopes = ARRAY['superuser']")
    await assert_rejected(session, "UPDATE api_keys SET scopes = ARRAY[]::text[]")


async def test_storage_connection_needs_credentials_for_its_auth_type(
    session: AsyncSession,
) -> None:
    tenant = await make_tenant(session)

    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            await persist(session, storage_connection(tenant, role_arn=None))


async def test_only_one_default_storage_connection_per_tenant(session: AsyncSession) -> None:
    tenant = await make_tenant(session)
    await persist(session, storage_connection(tenant, name="Primary", is_default=True))

    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            await persist(session, storage_connection(tenant, name="Backup", is_default=True))


async def test_storage_connection_in_use_cannot_be_deleted(session: AsyncSession) -> None:
    tenant = await make_tenant(session)
    connection = await persist(session, storage_connection(tenant))
    collection = await make_collection(session, tenant)
    await make_document(session, collection, storage_connection_id=connection.id)

    await assert_rejected(session, f"DELETE FROM storage_connections WHERE id = '{connection.id}'")


async def test_deleting_a_tenant_removes_everything_it_owns(session: AsyncSession) -> None:
    tenant = await make_tenant(session)
    connection = await persist(session, storage_connection(tenant))
    collection = await make_collection(session, tenant)
    document = await make_document(session, collection, storage_connection_id=connection.id)
    await make_chunk(session, document, "Shipping times")

    await session.execute(text("DELETE FROM tenants WHERE id = :id"), {"id": tenant.id})

    for model in (Tenant, Document, Chunk):
        assert await session.scalar(select(func.count()).select_from(model)) == 0
