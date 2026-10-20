import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, LargeBinary, MetaData, Text, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from uuid_utils.compat import uuid7

NAMING_CONVENTION = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
}

EMPTY_JSONB = text("'{}'::jsonb")


class Base(DeclarativeBase):
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {  # noqa: RUF012
        str: Text(),
        bytes: LargeBinary(),
        uuid.UUID: UUID(as_uuid=True),
        datetime: TIMESTAMP(timezone=True),
        dict[str, Any]: JSONB(),
        list[str]: ARRAY(Text()),
    }


class UUIDPrimaryKey:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7, sort_order=-100)


class TenantOwned:
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        sort_order=-90,
    )


class CreatedAt:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), sort_order=100)


class Timestamps(CreatedAt):
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        onupdate=func.now(),
        sort_order=101,
    )
