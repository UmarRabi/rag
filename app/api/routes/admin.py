from fastapi import APIRouter, status

from app.api.dependencies import (
    ApiKeyServiceDep,
    AuthenticatorDep,
    PlatformAdmin,
    TenantServiceDep,
)
from app.api.openapi import ADMIN_ERRORS
from app.api.schemas import (
    ApiKeyCreate,
    CreatedTenantResponse,
    IssuedApiKeyResponse,
    TenantCreate,
    TenantResponse,
    TenantUpdate,
)

router = APIRouter(
    prefix="/admin/tenants",
    tags=["platform admin"],
    dependencies=[PlatformAdmin],
    responses=ADMIN_ERRORS,
)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create a tenant and its first admin key",
)
async def create_tenant(body: TenantCreate, tenants: TenantServiceDep) -> CreatedTenantResponse:
    created = await tenants.create(
        body.slug, body.name, body.settings.model_dump(exclude_none=True)
    )
    return CreatedTenantResponse(
        tenant=TenantResponse.model_validate(created.tenant),
        api_key=IssuedApiKeyResponse.from_issued(created.admin_key),
    )


@router.get("", summary="List tenants")
async def list_tenants(tenants: TenantServiceDep) -> list[TenantResponse]:
    return [TenantResponse.model_validate(tenant) for tenant in await tenants.list()]


@router.get("/{slug}", summary="Get a tenant")
async def get_tenant(slug: str, tenants: TenantServiceDep) -> TenantResponse:
    return TenantResponse.model_validate(await tenants.get(slug))


@router.patch(
    "/{slug}",
    summary="Rename, suspend, reactivate or change a tenant's rate limits",
)
async def update_tenant(
    slug: str,
    body: TenantUpdate,
    tenants: TenantServiceDep,
    authenticator: AuthenticatorDep,
) -> TenantResponse:
    changes = body.model_dump(exclude_unset=True)
    if body.settings is not None:
        changes["settings"] = body.settings.model_dump(exclude_none=True)
    tenant = await tenants.update(slug, changes)
    authenticator.forget(tenant_id=tenant.id)
    return TenantResponse.model_validate(tenant)


@router.post(
    "/{slug}/api-keys",
    status_code=status.HTTP_201_CREATED,
    summary="Issue an API key for a tenant",
    description="For onboarding or recovering access when a tenant has lost its admin key.",
)
async def issue_tenant_key(
    slug: str,
    body: ApiKeyCreate,
    tenants: TenantServiceDep,
    keys: ApiKeyServiceDep,
) -> IssuedApiKeyResponse:
    tenant = await tenants.get(slug)
    issued = await keys.issue(tenant.id, body.name, body.scopes, body.expires_at)
    return IssuedApiKeyResponse.from_issued(issued)
