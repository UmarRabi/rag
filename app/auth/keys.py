import hashlib
import hmac
import secrets
import string
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Self

from app.core.errors import ServiceUnavailableError
from app.domain.enums import ApiKeyScope

KEY_SCHEME = "rag"
PREFIX_LENGTH = 8
SECRET_LENGTH = 40
KEY_ALPHABET = string.ascii_letters + string.digits
SCOPE_RANKS = {ApiKeyScope.SEARCH: 1, ApiKeyScope.INGEST: 2, ApiKeyScope.ADMIN: 3}


def random_text(length: int) -> str:
    return "".join(secrets.choice(KEY_ALPHABET) for _ in range(length))


@dataclass(frozen=True, slots=True)
class ApiKeyToken:
    prefix: str
    secret: str

    @classmethod
    def issue(cls) -> Self:
        return cls(random_text(PREFIX_LENGTH), random_text(SECRET_LENGTH))

    @classmethod
    def parse(cls, token: str) -> Self | None:
        scheme, _, remainder = token.strip().partition("_")
        prefix, _, secret = remainder.partition("_")
        well_formed = (
            scheme == KEY_SCHEME
            and len(prefix) == PREFIX_LENGTH
            and len(secret) == SECRET_LENGTH
            and (prefix + secret).isalnum()
        )
        return cls(prefix, secret) if well_formed else None

    @property
    def value(self) -> str:
        return f"{KEY_SCHEME}_{self.prefix}_{self.secret}"


class KeyHasher:
    def __init__(self, pepper: str) -> None:
        self._pepper = pepper.encode()

    def digest(self, secret: str) -> str:
        if not self._pepper:
            raise ServiceUnavailableError("RAG_API_KEY_PEPPER is not configured")
        return hmac.new(self._pepper, secret.encode(), hashlib.sha256).hexdigest()

    def matches(self, secret: str, digest: str) -> bool:
        return hmac.compare_digest(self.digest(secret), digest)


def grants(scopes: Iterable[str], required: ApiKeyScope) -> bool:
    return any(SCOPE_RANKS[ApiKeyScope(scope)] >= SCOPE_RANKS[required] for scope in scopes)
