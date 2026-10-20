import uuid

from fastapi import APIRouter, Response, status

from app.api.dependencies import AdminPrincipal, ApiKeyServiceDep, AuthenticatorDep
from app.api.openapi import errors
from app.api.schemas import ApiKeyCreate, ApiKeyResponse, IssuedApiKeyResponse

router = APIRouter(prefix="/v1/api-keys", tags=["api keys"], responses=errors())


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Create an API key",
    description="The full key is returned once in `token`. Only its prefix is kept.",
)
async def create_api_key(
    body: ApiKeyCreate,
    caller: AdminPrincipal,
    keys: ApiKeyServiceDep,
) -> IssuedApiKeyResponse:
    issued = await keys.issue(caller.tenant.id, body.name, body.scopes, body.expires_at)
    return IssuedApiKeyResponse.from_issued(issued)


@router.get("", summary="List API keys")
async def list_api_keys(caller: AdminPrincipal, keys: ApiKeyServiceDep) -> list[ApiKeyResponse]:
    return [ApiKeyResponse.model_validate(key) for key in await keys.list(caller.tenant.id)]


@router.delete(
    "/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke an API key",
    responses=errors(404),
)
async def revoke_api_key(
    key_id: uuid.UUID,
    caller: AdminPrincipal,
    keys: ApiKeyServiceDep,
    authenticator: AuthenticatorDep,
) -> Response:
    revoked = await keys.revoke(caller.tenant.id, key_id)
    authenticator.forget(prefix=revoked.prefix)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
