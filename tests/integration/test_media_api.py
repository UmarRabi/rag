from collections.abc import Callable
from typing import Any

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from tests.documents import mp4_video, png_image, wav_audio
from tests.fakes import FakeModels
from tests.integration.client import (
    AUTHENTICATED,
    as_tenant,
    create_collection,
    create_tenant,
    document,
    upload,
)
from tests.integration.database import run_sql


def media_vectors(database: str, document_id: str) -> list[tuple[int | None, int | None]]:
    rows = run_sql(
        database,
        "SELECT page, timestamp_ms FROM media_vectors WHERE document_id = :id ORDER BY position",
        id=document_id,
    )
    return [(row.page, row.timestamp_ms) for row in rows]


def chunk_modalities(database: str, document_id: str) -> list[tuple[str, int | None]]:
    rows = run_sql(
        database,
        "SELECT modality, start_ms FROM chunks WHERE document_id = :id ORDER BY position",
        id=document_id,
    )
    return [(row.modality, row.start_ms) for row in rows]


def image_search(api: TestClient, tenant: str = "acme", **body: Any) -> list[dict[str, Any]]:
    response = api.post("/v1/search/images", json=body, headers=as_tenant(tenant))
    assert response.status_code == status.HTTP_200_OK, response.text
    results: list[dict[str, Any]] = response.json()["results"]
    return results


@pytest.fixture
def gallery(api: TestClient, drain: Callable[[], int]) -> dict[str, str]:
    ids = {
        colour: upload(
            api, png_image(colour), f"{colour}.png", "image/png", title=f"{colour} router"
        ).json()["document_id"]
        for colour in ("red", "blue")
    }
    drain()
    return ids


def test_images_are_processed_on_the_media_queue(
    api: TestClient,
    drain: Callable[[], int],
    migrated_database: str,
) -> None:
    body = upload(api, png_image("red"), "red.png", "image/png").json()

    (row,) = run_sql(
        migrated_database, "SELECT queue FROM jobs WHERE document_id = :id", id=body["document_id"]
    )
    assert (body["media_type"], row.queue) == ("image", "media")

    drain()

    ready = document(api, body["document_id"])
    assert (ready["status"], ready["chunk_count"]) == ("ready", 2)
    assert chunk_modalities(migrated_database, body["document_id"]) == [
        ("caption", None),
        ("ocr", None),
    ]
    assert media_vectors(migrated_database, body["document_id"]) == [(None, None)]


def test_image_captions_and_text_are_found_by_normal_search(
    api: TestClient,
    gallery: dict[str, str],
) -> None:
    response = api.post(
        "/v1/search",
        json={"query": "A product photo on a white desk", "mode": "keyword"},
        headers=AUTHENTICATED,
    )

    modalities = {hit["modality"] for hit in response.json()["results"]}
    assert modalities == {"caption"}


def test_text_finds_matching_images(api: TestClient, gallery: dict[str, str]) -> None:
    (top, *_) = image_search(api, query="a red router")

    assert top["document_id"] == gallery["red"]
    assert top["score"] == pytest.approx(1.0)
    assert top["caption"] == "A product photo on a white desk"
    assert top["title"] == "red router"


def test_an_image_finds_similar_images(api: TestClient, gallery: dict[str, str]) -> None:
    response = api.post(
        "/v1/search/images",
        files={"image": ("query.png", png_image("blue", size=32), "image/png")},
        data={"top_k": "1"},
        headers=AUTHENTICATED,
    )

    (top,) = response.json()["results"]
    assert top["document_id"] == gallery["blue"]
    assert top["score"] == pytest.approx(1.0)


def test_image_search_respects_collections_and_filters(
    api: TestClient,
    drain: Callable[[], int],
    gallery: dict[str, str],
) -> None:
    create_collection(api, "catalog")
    upload(
        api,
        png_image("red", size=48),
        "catalog.png",
        "image/png",
        collection="catalog",
        metadata='{"line": "pro"}',
    )
    drain()

    support_only = image_search(api, query="red", collections=["support"])
    filtered = image_search(api, query="red", filters={"line": "pro"})

    assert {hit["collection"] for hit in support_only} == {"support"}
    assert [hit["collection"] for hit in filtered] == ["catalog"]


def test_other_tenants_never_see_images(
    api: TestClient,
    gallery: dict[str, str],
    migrated_database: str,
) -> None:
    create_tenant(migrated_database, "globex")

    assert image_search(api, tenant="globex", query="a red router") == []


def test_non_image_query_files_are_rejected(api: TestClient) -> None:
    response = api.post(
        "/v1/search/images",
        files={"image": ("notes.txt", b"just text", "text/plain")},
        headers=AUTHENTICATED,
    )

    assert response.status_code == status.HTTP_415_UNSUPPORTED_MEDIA_TYPE


def test_audio_is_transcribed_with_timestamps(
    api: TestClient,
    drain: Callable[[], int],
    migrated_database: str,
) -> None:
    body = upload(api, wav_audio(), "call.wav", "audio/wav").json()
    drain()

    ready = document(api, body["document_id"])
    assert (ready["status"], ready["media_type"]) == ("ready", "audio")
    (row,) = run_sql(
        migrated_database,
        "SELECT duration_ms FROM documents WHERE id = :id",
        id=body["document_id"],
    )
    assert row.duration_ms == 9500
    assert chunk_modalities(migrated_database, body["document_id"]) == [
        ("transcript", 0),
        ("transcript", 2400),
        ("transcript", 6800),
    ]

    (hit, *_) = api.post(
        "/v1/search",
        json={"query": "reset the router", "mode": "keyword"},
        headers=AUTHENTICATED,
    ).json()["results"]
    assert (hit["modality"], hit["start_ms"], hit["end_ms"]) == ("transcript", 2400, 6800)


def test_video_keyframes_and_speech_are_indexed(
    api: TestClient,
    drain: Callable[[], int],
    models: FakeModels,
    migrated_database: str,
) -> None:
    body = upload(
        api, mp4_video(["red", "blue", "green"], with_audio=True), "demo.mp4", "video/mp4"
    ).json()
    drain()

    assert document(api, body["document_id"])["status"] == "ready"
    assert media_vectors(migrated_database, body["document_id"]) == [(None, 0), (None, 10000)]
    modalities = {
        modality for modality, _ in chunk_modalities(migrated_database, body["document_id"])
    }
    assert modalities == {"transcript", "caption", "ocr"}

    (top, *_) = image_search(api, query="green", top_k=1)
    assert (top["document_id"], top["timestamp_ms"]) == (body["document_id"], 10000)
    assert top["caption"] == "A product photo on a white desk"
