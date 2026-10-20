import json
import uuid
from datetime import datetime
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from app.auth.service import IssuedApiKey
from app.domain.enums import (
    ApiKeyScope,
    ChunkModality,
    DocumentStatus,
    MediaType,
    SearchMode,
    SourceType,
    StorageAuthType,
    StorageConnectionStatus,
    StorageProvider,
    TenantStatus,
)
from app.ingestion.service import IngestionOutcome

SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]{0,62}$"

Slug = Annotated[str, Field(pattern=SLUG_PATTERN)]
TextMimeType = Literal["text/plain", "text/markdown", "text/csv", "application/json"]
MetadataScalar = str | int | float | bool
MetadataValue = MetadataScalar | list[MetadataScalar]


class Schema(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


def examples(*values: dict[str, Any]) -> ConfigDict:
    return ConfigDict(json_schema_extra={"examples": list(values)})


class CollectionCreate(Schema):
    model_config = examples(
        {"name": "Customer support", "slug": "support", "description": "Public help articles"},
    )

    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(pattern=SLUG_PATTERN)
    description: str | None = Field(default=None, max_length=2000)
    storage_connection_id: uuid.UUID | None = None


class CollectionUpdate(Schema):
    model_config = examples({"name": "Support articles"}, {"storage_connection_id": None})

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    storage_connection_id: uuid.UUID | None = None


class CollectionResponse(Schema):
    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    storage_connection_id: uuid.UUID | None
    created_at: datetime


class FileIngestFields(Schema):
    collection: str = Field(pattern=SLUG_PATTERN)
    title: str | None = Field(default=None, max_length=500)
    external_id: str | None = Field(default=None, min_length=1, max_length=255)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata", mode="before")
    @classmethod
    def parse_metadata(cls, value: Any) -> Any:
        if isinstance(value, str):
            return json.loads(value) if value.strip() else {}
        return value


class StorageConnectionCreate(Schema):
    model_config = examples(
        {
            "name": "Acme AWS bucket",
            "provider": "s3",
            "bucket": "acme-rag-files",
            "region": "eu-west-1",
            "prefix": "rag",
            "auth_type": "assume_role",
            "role_arn": "arn:aws:iam::123456789012:role/interra-rag",
            "external_id": "acme-7f3c",
            "is_default": True,
        },
        {
            "name": "Acme R2 bucket",
            "provider": "r2",
            "bucket": "acme-rag-files",
            "endpoint_url": "https://<account-id>.r2.cloudflarestorage.com",
            "auth_type": "access_key",
            "access_key_id": "<access key id>",
            "secret_access_key": "<secret access key>",
        },
    )

    name: str = Field(min_length=1, max_length=200)
    provider: StorageProvider
    bucket: str = Field(min_length=3, max_length=63)
    region: str | None = Field(default=None, max_length=64)
    endpoint_url: str | None = Field(default=None, max_length=500)
    prefix: str | None = Field(default=None, max_length=500)
    auth_type: StorageAuthType
    role_arn: str | None = Field(default=None, max_length=2048)
    external_id: str | None = Field(default=None, max_length=1224)
    access_key_id: str | None = Field(default=None, max_length=128)
    secret_access_key: SecretStr | None = None
    is_default: bool = False

    @model_validator(mode="after")
    def credentials_match_auth_type(self) -> Self:
        if self.auth_type is StorageAuthType.ASSUME_ROLE and not self.role_arn:
            raise ValueError("role_arn is required for assume_role connections")
        if self.auth_type is StorageAuthType.ACCESS_KEY and not (
            self.access_key_id and self.secret_access_key
        ):
            raise ValueError(
                "access_key_id and secret_access_key are required for access_key connections"
            )
        return self


class StorageConnectionResponse(Schema):
    id: uuid.UUID
    name: str
    provider: StorageProvider
    bucket: str
    region: str | None
    endpoint_url: str | None
    prefix: str | None
    auth_type: StorageAuthType
    role_arn: str | None
    external_id: str | None
    is_default: bool
    status: StorageConnectionStatus
    verified_at: datetime | None
    last_error: str | None
    created_at: datetime


class TextIngestRequest(Schema):
    model_config = examples(
        {
            "collection": "support",
            "title": "Resetting your password",
            "external_id": "kb-42",
            "text": "Open Settings, choose Security and click Reset password. "
            "A reset link is emailed to you and expires after 30 minutes.",
            "metadata": {"audience": "public", "product": "router-x"},
        },
    )

    collection: str = Field(pattern=SLUG_PATTERN)
    text: str = Field(min_length=1)
    mime_type: TextMimeType = "text/plain"
    title: str | None = Field(default=None, max_length=500)
    external_id: str | None = Field(default=None, min_length=1, max_length=255)
    metadata: dict[str, Any] = Field(default_factory=dict)


class IngestResponse(Schema):
    document_id: uuid.UUID
    status: DocumentStatus
    media_type: MediaType
    chunk_count: int
    duplicate: bool

    @classmethod
    def from_outcome(cls, outcome: IngestionOutcome) -> Self:
        document = outcome.document
        return cls(
            document_id=document.id,
            status=document.status,
            media_type=document.media_type,
            chunk_count=document.chunk_count,
            duplicate=outcome.duplicate,
        )


class DocumentResponse(Schema):
    id: uuid.UUID
    collection_id: uuid.UUID
    external_id: str | None
    title: str | None
    source_type: SourceType
    media_type: MediaType
    mime_type: str | None
    size_bytes: int | None
    language: str | None
    status: DocumentStatus
    error: str | None
    chunk_count: int
    metadata: dict[str, Any] = Field(validation_alias="meta")
    created_at: datetime
    updated_at: datetime
    processed_at: datetime | None


class SearchRequest(Schema):
    model_config = examples(
        {
            "query": "I can't get into my account after too many tries",
            "collections": ["support"],
        },
    )

    query: str = Field(min_length=1, max_length=2000)
    collections: list[Slug] = Field(default_factory=list, max_length=50)
    top_k: int = Field(default=1, ge=1, le=50)
    mode: SearchMode = SearchMode.VECTOR
    min_score: float | None = Field(
        default=None,
        ge=0,
        description="Drop results whose meaning similarity is below this value (0 to 1).",
    )
    filters: dict[str, MetadataValue] = Field(default_factory=dict)
    modalities: list[ChunkModality] = Field(default_factory=list)


class SearchResult(Schema):
    chunk_id: int
    document_id: uuid.UUID
    collection: str
    title: str | None
    external_id: str | None
    source_url: str | None
    media_type: MediaType
    content: str
    modality: ChunkModality
    page: int | None
    start_ms: int | None
    end_ms: int | None
    language: str | None
    metadata: dict[str, Any]
    score: float
    vector_score: float | None
    keyword_score: float | None


class SearchResponse(Schema):
    mode: SearchMode
    results: list[SearchResult]


class ApiKeyCreate(Schema):
    model_config = examples({"name": "Website chat widget", "scopes": ["search"]})

    name: str = Field(min_length=1, max_length=200)
    scopes: list[ApiKeyScope] = Field(min_length=1)
    expires_at: datetime | None = None


class ApiKeyResponse(Schema):
    id: uuid.UUID
    name: str
    prefix: str
    scopes: list[ApiKeyScope]
    expires_at: datetime | None
    last_used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class IssuedApiKeyResponse(ApiKeyResponse):
    token: str = Field(description="The full API key. It is shown only once; store it safely.")

    @classmethod
    def from_issued(cls, issued: IssuedApiKey) -> Self:
        return cls.model_validate(
            ApiKeyResponse.model_validate(issued.key).model_dump() | {"token": issued.token},
        )


class RateLimitOverrides(Schema):
    search: int | None = Field(default=None, ge=1)
    ingest: int | None = Field(default=None, ge=1)
    api: int | None = Field(default=None, ge=1)


class TenantSettings(Schema):
    rate_limits: RateLimitOverrides = Field(default_factory=RateLimitOverrides)


class TenantCreate(Schema):
    model_config = examples(
        {"name": "Acme Ltd", "slug": "acme", "settings": {"rate_limits": {"search": 120}}},
    )

    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(pattern=SLUG_PATTERN)
    settings: TenantSettings = Field(default_factory=TenantSettings)


class TenantUpdate(Schema):
    model_config = examples({"status": "suspended"}, {"settings": {"rate_limits": {"ingest": 10}}})

    name: str | None = Field(default=None, min_length=1, max_length=200)
    status: TenantStatus | None = None
    settings: TenantSettings | None = None


class TenantResponse(Schema):
    id: uuid.UUID
    name: str
    slug: str
    status: TenantStatus
    settings: dict[str, Any]
    created_at: datetime


class CreatedTenantResponse(Schema):
    tenant: TenantResponse
    api_key: IssuedApiKeyResponse


class ImageSearchRequest(Schema):
    model_config = examples({"query": "a red router with two antennas"})

    query: str = Field(min_length=1, max_length=500)
    collections: list[Slug] = Field(default_factory=list, max_length=50)
    top_k: int = Field(default=1, ge=1, le=50)
    min_score: float | None = Field(default=None, ge=0, le=1)
    filters: dict[str, MetadataValue] = Field(default_factory=dict)


class ImageSearchFields(Schema):
    collections: list[Slug] = Field(default_factory=list, max_length=50)
    top_k: int = Field(default=1, ge=1, le=50)
    min_score: float | None = Field(default=None, ge=0, le=1)
    filters: dict[str, MetadataValue] = Field(default_factory=dict)

    @field_validator("collections", mode="before")
    @classmethod
    def split_collections(cls, value: Any) -> Any:
        if isinstance(value, str):
            return [slug.strip() for slug in value.split(",") if slug.strip()]
        return value

    @field_validator("filters", mode="before")
    @classmethod
    def parse_filters(cls, value: Any) -> Any:
        if isinstance(value, str):
            return json.loads(value) if value.strip() else {}
        return value


class ImageResult(Schema):
    media_vector_id: int
    document_id: uuid.UUID
    collection: str
    title: str | None
    external_id: str | None
    source_url: str | None
    media_type: MediaType
    page: int | None
    timestamp_ms: int | None
    caption: str | None
    metadata: dict[str, Any]
    score: float


class ImageSearchResponse(Schema):
    results: list[ImageResult]
