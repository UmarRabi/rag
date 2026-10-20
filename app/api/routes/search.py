from dataclasses import asdict

from fastapi import APIRouter

from app.api.dependencies import SearchServiceDep, SearchTenant, SettingsDep
from app.api.openapi import SEARCH_DESCRIPTION, errors
from app.api.schemas import SearchRequest, SearchResponse, SearchResult
from app.search.service import SearchQuery

router = APIRouter(prefix="/v1", tags=["search"], responses=errors(404))


@router.post("/search", summary="Search chunks", description=SEARCH_DESCRIPTION)
async def search(
    body: SearchRequest,
    tenant: SearchTenant,
    service: SearchServiceDep,
    settings: SettingsDep,
) -> SearchResponse:
    query = SearchQuery(
        text=body.query,
        top_k=body.top_k,
        candidates=settings.search_candidates(body.top_k),
        mode=body.mode,
        collections=body.collections,
        filters=body.filters,
        modalities=body.modalities,
        min_score=body.min_score,
    )
    hits = await service.search(tenant, query)
    return SearchResponse(
        mode=body.mode,
        results=[SearchResult.model_validate(asdict(hit)) for hit in hits],
    )
