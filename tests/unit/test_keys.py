import pytest

from app.auth.keys import ApiKeyToken, KeyHasher, grants
from app.core.errors import ServiceUnavailableError
from app.domain.enums import ApiKeyScope


def test_issued_tokens_round_trip_through_parsing() -> None:
    token = ApiKeyToken.issue()

    assert ApiKeyToken.parse(token.value) == token
    assert token.value.startswith(f"rag_{token.prefix}_")


def test_issued_tokens_are_unique() -> None:
    assert len({ApiKeyToken.issue().value for _ in range(200)}) == 200


@pytest.mark.parametrize(
    "token",
    [
        "",
        "rag_short_secret",
        "key_abcdefgh_" + "x" * 40,
        "rag_abcdefgh_" + "x" * 39,
        "rag_abc-efgh_" + "x" * 40,
    ],
)
def test_malformed_tokens_are_rejected(token: str) -> None:
    assert ApiKeyToken.parse(token) is None


def test_hashes_depend_on_the_pepper() -> None:
    secret = ApiKeyToken.issue().secret
    digest = KeyHasher("pepper-one").digest(secret)

    assert KeyHasher("pepper-one").matches(secret, digest)
    assert not KeyHasher("pepper-two").matches(secret, digest)
    assert secret not in digest


def test_hashing_without_a_pepper_is_refused() -> None:
    with pytest.raises(ServiceUnavailableError):
        KeyHasher("").digest("secret")


@pytest.mark.parametrize(
    ("scopes", "required", "allowed"),
    [
        (["search"], ApiKeyScope.SEARCH, True),
        (["search"], ApiKeyScope.INGEST, False),
        (["ingest"], ApiKeyScope.SEARCH, True),
        (["ingest"], ApiKeyScope.ADMIN, False),
        (["admin"], ApiKeyScope.INGEST, True),
        (["search", "ingest"], ApiKeyScope.INGEST, True),
    ],
)
def test_higher_scopes_include_lower_ones(
    scopes: list[str], required: ApiKeyScope, allowed: bool
) -> None:
    assert grants(scopes, required) is allowed
