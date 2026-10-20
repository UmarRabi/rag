import importlib
from types import ModuleType

from app.core.errors import ServiceUnavailableError


def optional_module(name: str, group: str) -> ModuleType:
    try:
        return importlib.import_module(name)
    except ImportError as error:
        raise ServiceUnavailableError(
            f"'{name}' is not installed; run `uv sync --group {group}`",
        ) from error
