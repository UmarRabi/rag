import argparse
import asyncio
import sys
from collections.abc import Awaitable, Callable

from app.auth.keys import KeyHasher
from app.auth.service import ApiKeyService, IssuedApiKey, TenantService
from app.core.errors import ServiceError
from app.core.settings import get_settings
from app.domain.enums import ApiKeyScope
from app.infra.database import Database
from app.ingestion.service import requeue_all


async def with_services[T](action: Callable[[TenantService, ApiKeyService], Awaitable[T]]) -> T:
    settings = get_settings()
    database = Database.from_settings(settings)
    try:
        async with database.session() as session:
            keys = ApiKeyService(session, KeyHasher(settings.api_key_pepper))
            return await action(TenantService(session, keys), keys)
    finally:
        await database.dispose()


async def create_tenant(slug: str, name: str) -> IssuedApiKey:
    async def action(tenants: TenantService, keys: ApiKeyService) -> IssuedApiKey:
        return (await tenants.create(slug, name, {})).admin_key

    return await with_services(action)


async def create_api_key(slug: str, name: str, scopes: list[ApiKeyScope]) -> IssuedApiKey:
    async def action(tenants: TenantService, keys: ApiKeyService) -> IssuedApiKey:
        tenant = await tenants.get(slug)
        return await keys.issue(tenant.id, name, scopes)

    return await with_services(action)


async def reprocess_documents(slug: str | None) -> int:
    async def action(tenants: TenantService, keys: ApiKeyService) -> int:
        tenant_id = (await tenants.get(slug)).id if slug else None
        return await requeue_all(tenants.session, tenant_id)

    return await with_services(action)


def show(issued: IssuedApiKey, heading: str) -> None:
    print(heading)
    print(f"  scopes: {', '.join(issued.key.scopes)}")
    print(f"  key:    {issued.token}")
    print("Store this key now; it cannot be shown again.")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="rag")
    commands = root.add_subparsers(dest="command", required=True)

    tenant = commands.add_parser("create-tenant", help="Create a tenant and its first admin key")
    tenant.add_argument("slug")
    tenant.add_argument("name")

    reprocess = commands.add_parser("reprocess", help="Queue documents to be processed again")
    reprocess.add_argument("slug", nargs="?", help="Only this tenant's documents")

    key = commands.add_parser("create-api-key", help="Issue an API key for a tenant")
    key.add_argument("slug")
    key.add_argument("--name", default="CLI key")
    key.add_argument(
        "--scopes",
        default=ApiKeyScope.SEARCH.value,
        help="Comma separated: search, ingest, admin",
    )
    return root


def main() -> None:
    try:
        run(parser().parse_args())
    except ServiceError as error:
        print(f"Error: {error.message}", file=sys.stderr)
        sys.exit(1)


def run(arguments: argparse.Namespace) -> None:
    if arguments.command == "create-tenant":
        issued = asyncio.run(create_tenant(arguments.slug, arguments.name))
        show(issued, f"Created tenant '{arguments.slug}'.")
    elif arguments.command == "reprocess":
        count = asyncio.run(reprocess_documents(arguments.slug))
        print(f"Queued {count} documents for processing.")
    elif arguments.command == "create-api-key":
        scopes = [ApiKeyScope(scope.strip()) for scope in arguments.scopes.split(",")]
        issued = asyncio.run(create_api_key(arguments.slug, arguments.name, scopes))
        show(issued, f"Issued API key '{arguments.name}' for '{arguments.slug}'.")


if __name__ == "__main__":
    main()
