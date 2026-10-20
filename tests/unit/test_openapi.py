from typing import Any

import pytest

from app.main import create_app

HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    return create_app().openapi()


def operations(spec: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    return [
        (path, method, operation)
        for path, item in spec["paths"].items()
        for method, operation in item.items()
        if method in HTTP_METHODS
    ]


def test_api_keys_and_platform_admin_are_bearer_schemes(spec: dict[str, Any]) -> None:
    schemes = spec["components"]["securitySchemes"]

    assert {name: (scheme["type"], scheme["scheme"]) for name, scheme in schemes.items()} == {
        "ApiKey": ("http", "bearer"),
        "PlatformAdmin": ("http", "bearer"),
    }


def test_every_operation_has_a_summary_and_tag(spec: dict[str, Any]) -> None:
    for path, method, operation in operations(spec):
        assert operation.get("summary"), f"{method.upper()} {path}"
        assert operation.get("tags"), f"{method.upper()} {path}"


EXPECTED_SECURITY: dict[str, list[dict[str, list[str]]]] = {
    "/v1/": [{"ApiKey": []}],
    "/admin/": [{"PlatformAdmin": []}],
}


def test_operations_use_the_right_security_scheme(spec: dict[str, Any]) -> None:
    for path, method, operation in operations(spec):
        for prefix, security in EXPECTED_SECURITY.items():
            if path.startswith(prefix):
                assert operation.get("security") == security, f"{method.upper()} {path}"


def test_ingest_accepts_json_text_and_file_uploads(spec: dict[str, Any]) -> None:
    content = spec["paths"]["/v1/ingest"]["post"]["requestBody"]["content"]

    assert set(content) == {"application/json", "multipart/form-data"}
    assert content["multipart/form-data"]["schema"]["properties"]["file"]["format"] == "binary"
    assert content["application/json"]["schema"]["examples"][0]["collection"] == "support"


def test_request_bodies_have_examples(spec: dict[str, Any]) -> None:
    schemas = spec["components"]["schemas"]

    for name in ("CollectionCreate", "SearchRequest", "StorageConnectionCreate"):
        assert schemas[name]["examples"], name
