import re
from enum import StrEnum

from sqlalchemy import Enum

ENUM_COLUMN_LENGTH = 32


def snake_case(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def str_enum(enum_class: type[StrEnum]) -> Enum:
    return Enum(
        enum_class,
        name=snake_case(enum_class.__name__),
        native_enum=False,
        create_constraint=True,
        length=ENUM_COLUMN_LENGTH,
        validate_strings=True,
        values_callable=lambda members: [member.value for member in members],
    )


def sql_text_array(enum_class: type[StrEnum]) -> str:
    values = ", ".join(f"'{member.value}'" for member in enum_class)
    return f"ARRAY[{values}]::text[]"
