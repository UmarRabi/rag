from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "media_vectors",
    "jobs",
    "chunks",
    "documents",
    "collections",
    "storage_connections",
    "api_keys",
    "tenants",
)
HNSW_PARAMETERS = {"m": 16, "ef_construction": 64}


def enum_column(name: str, server_default: str | None = None) -> sa.Column[str]:
    return sa.Column(name, sa.String(32), server_default=server_default, nullable=False)


def enum_check(
    table: str,
    column: str,
    constraint: str,
    values: Sequence[str],
) -> sa.CheckConstraint:
    allowed = ", ".join(f"'{value}'" for value in values)
    return sa.CheckConstraint(f"{column} IN ({allowed})", name=op.f(f"ck_{table}_{constraint}"))


def uuid_column(name: str, *, nullable: bool = False) -> sa.Column[object]:
    return sa.Column(name, sa.UUID(), nullable=nullable)


def text_column(name: str, *, nullable: bool = True) -> sa.Column[str]:
    return sa.Column(name, sa.Text(), nullable=nullable)


def timestamp_column(name: str, *, defaulted: bool = False) -> sa.Column[object]:
    if defaulted:
        return sa.Column(
            name,
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        )
    return sa.Column(name, postgresql.TIMESTAMP(timezone=True), nullable=True)


def jsonb_column(name: str) -> sa.Column[object]:
    return sa.Column(
        name,
        postgresql.JSONB(astext_type=sa.Text()),
        server_default=sa.text("'{}'::jsonb"),
        nullable=False,
    )


def tenant_foreign_key(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id"],
        ["tenants.id"],
        name=op.f(f"fk_{table}_tenant_id_tenants"),
        ondelete="CASCADE",
    )


def document_foreign_key(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["document_id"],
        ["documents.id"],
        name=op.f(f"fk_{table}_document_id_documents"),
        ondelete="CASCADE",
    )


def storage_connection_foreign_key(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["storage_connection_id"],
        ["storage_connections.id"],
        name=op.f(f"fk_{table}_storage_connection_id_storage_connections"),
    )


def document_part_columns() -> list[sa.Column[object]]:
    return [
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        uuid_column("tenant_id"),
        uuid_column("collection_id"),
        uuid_column("document_id"),
        sa.Column("position", sa.Integer(), nullable=False),
    ]


def create_cosine_hnsw_index(name: str, table: str) -> None:
    op.create_index(
        name,
        table,
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with=HNSW_PARAMETERS,
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


TENANT_STATUSES = ("active", "suspended")
API_KEY_SCOPES = ("ingest", "search", "admin")
STORAGE_PROVIDERS = ("s3", "r2", "spaces", "wasabi", "s3_compatible")
STORAGE_AUTH_TYPES = ("assume_role", "access_key")
STORAGE_CONNECTION_STATUSES = ("pending", "verified", "failed")
SOURCE_TYPES = ("text", "upload", "url")
MEDIA_TYPES = ("text", "pdf", "docx", "pptx", "xlsx", "html", "image", "audio", "video")
DOCUMENT_STATUSES = ("queued", "processing", "ready", "failed")
CHUNK_MODALITIES = ("text", "ocr", "caption", "transcript")
JOB_KINDS = ("ingest", "reprocess")
JOB_QUEUES = ("light", "media")
JOB_STATUSES = ("pending", "running", "succeeded", "failed")


def create_tenants() -> None:
    op.create_table(
        "tenants",
        uuid_column("id"),
        text_column("name", nullable=False),
        text_column("slug", nullable=False),
        enum_column("status", server_default="active"),
        jsonb_column("settings"),
        timestamp_column("created_at", defaulted=True),
        timestamp_column("updated_at", defaulted=True),
        enum_check("tenants", "status", "tenant_status", TENANT_STATUSES),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tenants")),
        sa.UniqueConstraint("slug", name=op.f("uq_tenants_slug")),
    )


def create_api_keys() -> None:
    scopes = ", ".join(f"'{scope}'" for scope in API_KEY_SCOPES)
    op.create_table(
        "api_keys",
        uuid_column("id"),
        uuid_column("tenant_id"),
        text_column("name", nullable=False),
        text_column("prefix", nullable=False),
        text_column("key_hash", nullable=False),
        sa.Column("scopes", postgresql.ARRAY(sa.Text()), nullable=False),
        timestamp_column("last_used_at"),
        timestamp_column("expires_at"),
        timestamp_column("revoked_at"),
        timestamp_column("created_at", defaulted=True),
        sa.CheckConstraint(
            f"scopes <@ ARRAY[{scopes}]::text[]",
            name=op.f("ck_api_keys_known_scopes"),
        ),
        sa.CheckConstraint("cardinality(scopes) > 0", name=op.f("ck_api_keys_has_scopes")),
        tenant_foreign_key("api_keys"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_keys")),
        sa.UniqueConstraint("prefix", name=op.f("uq_api_keys_prefix")),
    )
    op.create_index(op.f("ix_api_keys_tenant_id"), "api_keys", ["tenant_id"])


def create_storage_connections() -> None:
    op.create_table(
        "storage_connections",
        uuid_column("id"),
        uuid_column("tenant_id"),
        text_column("name", nullable=False),
        enum_column("provider"),
        text_column("bucket", nullable=False),
        text_column("region"),
        text_column("endpoint_url"),
        text_column("prefix"),
        enum_column("auth_type"),
        text_column("role_arn"),
        text_column("external_id"),
        sa.Column("credentials_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("is_default", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        enum_column("status", server_default="pending"),
        timestamp_column("verified_at"),
        text_column("last_error"),
        timestamp_column("created_at", defaulted=True),
        timestamp_column("updated_at", defaulted=True),
        enum_check("storage_connections", "provider", "storage_provider", STORAGE_PROVIDERS),
        enum_check("storage_connections", "auth_type", "storage_auth_type", STORAGE_AUTH_TYPES),
        enum_check(
            "storage_connections",
            "status",
            "storage_connection_status",
            STORAGE_CONNECTION_STATUSES,
        ),
        sa.CheckConstraint(
            "(auth_type = 'assume_role' AND role_arn IS NOT NULL)"
            " OR (auth_type = 'access_key' AND credentials_encrypted IS NOT NULL)",
            name=op.f("ck_storage_connections_credentials_match_auth_type"),
        ),
        tenant_foreign_key("storage_connections"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_storage_connections")),
        sa.UniqueConstraint(
            "tenant_id",
            "name",
            name=op.f("uq_storage_connections_tenant_id_name"),
        ),
    )
    op.create_index(
        "uq_storage_connections_default_per_tenant",
        "storage_connections",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )


def create_collections() -> None:
    op.create_table(
        "collections",
        uuid_column("id"),
        uuid_column("tenant_id"),
        text_column("name", nullable=False),
        text_column("slug", nullable=False),
        text_column("description"),
        uuid_column("storage_connection_id", nullable=True),
        jsonb_column("settings"),
        timestamp_column("created_at", defaulted=True),
        timestamp_column("updated_at", defaulted=True),
        storage_connection_foreign_key("collections"),
        tenant_foreign_key("collections"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_collections")),
        sa.UniqueConstraint("tenant_id", "slug", name=op.f("uq_collections_tenant_id_slug")),
    )


def create_documents() -> None:
    op.create_table(
        "documents",
        uuid_column("id"),
        uuid_column("tenant_id"),
        uuid_column("collection_id"),
        text_column("external_id"),
        text_column("title"),
        enum_column("source_type"),
        enum_column("media_type"),
        text_column("mime_type"),
        text_column("source_url"),
        uuid_column("storage_connection_id", nullable=True),
        text_column("storage_uri"),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        text_column("language"),
        text_column("content_hash", nullable=False),
        jsonb_column("metadata"),
        enum_column("status", server_default="queued"),
        text_column("error"),
        sa.Column("chunk_count", sa.Integer(), server_default="0", nullable=False),
        timestamp_column("processed_at"),
        timestamp_column("created_at", defaulted=True),
        timestamp_column("updated_at", defaulted=True),
        enum_check("documents", "source_type", "source_type", SOURCE_TYPES),
        enum_check("documents", "media_type", "media_type", MEDIA_TYPES),
        enum_check("documents", "status", "document_status", DOCUMENT_STATUSES),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["collections.id"],
            name=op.f("fk_documents_collection_id_collections"),
            ondelete="CASCADE",
        ),
        storage_connection_foreign_key("documents"),
        tenant_foreign_key("documents"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
        sa.UniqueConstraint(
            "collection_id",
            "content_hash",
            name=op.f("uq_documents_collection_id_content_hash"),
        ),
        sa.UniqueConstraint(
            "collection_id",
            "external_id",
            name=op.f("uq_documents_collection_id_external_id"),
        ),
    )
    op.create_index(
        op.f("ix_documents_storage_connection_id"),
        "documents",
        ["storage_connection_id"],
        postgresql_where=sa.text("storage_connection_id IS NOT NULL"),
    )
    op.create_index(
        op.f("ix_documents_tenant_id_collection_id_created_at"),
        "documents",
        ["tenant_id", "collection_id", "created_at"],
    )


def create_chunks() -> None:
    op.create_table(
        "chunks",
        *document_part_columns(),
        enum_column("modality"),
        text_column("content", nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        text_column("language"),
        sa.Column(
            "text_search_config",
            postgresql.REGCONFIG(),
            server_default=sa.text("'simple'::regconfig"),
            nullable=False,
        ),
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector(text_search_config, content)", persisted=True),
            nullable=False,
        ),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("start_ms", sa.Integer(), nullable=True),
        sa.Column("end_ms", sa.Integer(), nullable=True),
        jsonb_column("metadata"),
        sa.Column("embedding", Vector(768), nullable=False),
        text_column("embedding_model", nullable=False),
        timestamp_column("created_at", defaulted=True),
        enum_check("chunks", "modality", "chunk_modality", CHUNK_MODALITIES),
        document_foreign_key("chunks"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chunks")),
        sa.UniqueConstraint("document_id", "position", name=op.f("uq_chunks_document_id_position")),
    )
    create_cosine_hnsw_index("ix_chunks_embedding", "chunks")
    op.create_index(
        "ix_chunks_metadata",
        "chunks",
        ["metadata"],
        postgresql_using="gin",
        postgresql_ops={"metadata": "jsonb_path_ops"},
    )
    op.create_index("ix_chunks_search_vector", "chunks", ["search_vector"], postgresql_using="gin")
    op.create_index(
        op.f("ix_chunks_tenant_id_collection_id"),
        "chunks",
        ["tenant_id", "collection_id"],
    )


def create_media_vectors() -> None:
    op.create_table(
        "media_vectors",
        *document_part_columns(),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("timestamp_ms", sa.Integer(), nullable=True),
        text_column("storage_uri"),
        sa.Column("embedding", Vector(512), nullable=False),
        text_column("embedding_model", nullable=False),
        timestamp_column("created_at", defaulted=True),
        document_foreign_key("media_vectors"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_media_vectors")),
        sa.UniqueConstraint(
            "document_id",
            "position",
            name=op.f("uq_media_vectors_document_id_position"),
        ),
    )
    create_cosine_hnsw_index("ix_media_vectors_embedding", "media_vectors")
    op.create_index(
        op.f("ix_media_vectors_tenant_id_collection_id"),
        "media_vectors",
        ["tenant_id", "collection_id"],
    )


def create_jobs() -> None:
    op.create_table(
        "jobs",
        uuid_column("id"),
        uuid_column("tenant_id"),
        uuid_column("document_id"),
        enum_column("kind"),
        enum_column("queue"),
        enum_column("status", server_default="pending"),
        sa.Column("priority", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("attempts", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.SmallInteger(), server_default="5", nullable=False),
        timestamp_column("run_after", defaulted=True),
        text_column("locked_by"),
        timestamp_column("locked_at"),
        text_column("last_error"),
        timestamp_column("created_at", defaulted=True),
        timestamp_column("updated_at", defaulted=True),
        enum_check("jobs", "kind", "job_kind", JOB_KINDS),
        enum_check("jobs", "queue", "job_queue", JOB_QUEUES),
        enum_check("jobs", "status", "job_status", JOB_STATUSES),
        sa.CheckConstraint(
            "attempts <= max_attempts",
            name=op.f("ck_jobs_attempts_within_limit"),
        ),
        document_foreign_key("jobs"),
        tenant_foreign_key("jobs"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
    )
    op.create_index(op.f("ix_jobs_document_id"), "jobs", ["document_id"])
    op.create_index(
        "ix_jobs_pending",
        "jobs",
        ["queue", sa.literal_column("priority DESC"), "run_after"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_jobs_running",
        "jobs",
        ["locked_at"],
        postgresql_where=sa.text("status = 'running'"),
    )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    create_tenants()
    create_api_keys()
    create_storage_connections()
    create_collections()
    create_documents()
    create_chunks()
    create_media_vectors()
    create_jobs()


def downgrade() -> None:
    for table in TABLES:
        op.drop_table(table)
