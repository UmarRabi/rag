from collections.abc import Callable
from typing import Any

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from tests.fakes import FakeModels, FixedLanguageDetector
from tests.integration.client import AUTHENTICATED, create_collection, create_tenant, ingest, search

PASSWORD = "Reset your password from security settings."
REFUND = "Refunds arrive within five business days."
SHIPPING = "Orders ship from our Lagos warehouse."


@pytest.fixture
def library(api: TestClient, drain: Callable[[], int]) -> dict[str, str]:
    documents: dict[str, dict[str, Any]] = {
        PASSWORD: {
            "title": "Password help",
            "external_id": "kb-1",
            "metadata": {"audience": "public"},
        },
        REFUND: {"title": "Refunds", "metadata": {"audience": "public"}},
        SHIPPING: {"title": "Shipping", "metadata": {"audience": "internal"}},
    }
    ingested = {
        text: ingest(api, text=text, **fields).json()["document_id"]
        for text, fields in documents.items()
    }
    drain()
    return ingested


def results(response: Any) -> list[dict[str, Any]]:
    assert response.status_code == status.HTTP_200_OK, response.text
    hits: list[dict[str, Any]] = response.json()["results"]
    return hits


def contents(response: Any) -> list[str]:
    return [hit["content"] for hit in results(response)]


def test_vector_search_ranks_the_closest_chunk_first(
    api: TestClient, library: dict[str, str]
) -> None:
    (top, *_) = results(search(api, PASSWORD, mode="vector"))

    assert top["content"] == PASSWORD
    assert top["score"] == pytest.approx(1.0)
    assert top["keyword_score"] is None


def test_keyword_search_matches_word_stems(api: TestClient, library: dict[str, str]) -> None:
    hits = results(search(api, "refund", mode="keyword"))

    assert [hit["content"] for hit in hits] == [REFUND]
    assert hits[0]["vector_score"] is None


def test_keyword_search_uses_each_chunk_language(
    api: TestClient,
    models: FakeModels,
    library: dict[str, str],
    drain: Callable[[], int],
) -> None:
    models.language_detector = FixedLanguageDetector("fr")
    french = "Les remboursements arrivent sous cinq jours."
    ingest(api, text=french)
    drain()

    assert contents(search(api, "remboursement", mode="keyword")) == [french]


def test_hybrid_search_rewards_chunks_found_by_both_rankings(
    api: TestClient,
    library: dict[str, str],
) -> None:
    (top, *_) = results(search(api, REFUND, mode="hybrid"))

    assert top["content"] == REFUND
    assert top["score"] == pytest.approx(1.0)
    assert top["vector_score"] is not None
    assert top["keyword_score"] is not None


def test_hybrid_search_still_returns_meaning_matches_without_keywords(
    api: TestClient,
    library: dict[str, str],
) -> None:
    hits = results(search(api, "zebra crossing", mode="hybrid", top_k=len(library)))

    assert len(hits) == len(library)
    assert all(hit["keyword_score"] is None for hit in hits)


def test_results_describe_their_source(api: TestClient, library: dict[str, str]) -> None:
    (top, *_) = results(search(api, PASSWORD, mode="vector"))

    assert top["document_id"] == library[PASSWORD]
    assert (top["collection"], top["title"], top["external_id"]) == (
        "support",
        "Password help",
        "kb-1",
    )
    assert (top["media_type"], top["modality"], top["language"]) == ("text", "text", "en")
    assert top["metadata"] == {"audience": "public"}


def test_top_k_limits_results(api: TestClient, library: dict[str, str]) -> None:
    top_k = len(library) - 1

    assert len(results(search(api, "anything", top_k=top_k))) == top_k


def test_metadata_filters_narrow_results(api: TestClient, library: dict[str, str]) -> None:
    hits = contents(search(api, "anything", filters={"audience": "internal"}))

    assert hits == [SHIPPING]


def test_search_is_limited_to_the_requested_collections(
    api: TestClient,
    library: dict[str, str],
    drain: Callable[[], int],
) -> None:
    create_collection(api, "internal")
    ingest(api, collection="internal", text="Quarterly revenue targets.")
    drain()

    support_only = contents(search(api, "Quarterly revenue targets.", collections=["support"]))
    everything = contents(search(api, "Quarterly revenue targets."))

    assert "Quarterly revenue targets." not in support_only
    assert everything[0] == "Quarterly revenue targets."


def test_unknown_collection_is_not_found(api: TestClient, library: dict[str, str]) -> None:
    response = search(api, "refund", collections=["support", "billing"])

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert "billing" in response.json()["detail"]


def test_tenants_never_see_each_others_data(
    api: TestClient,
    migrated_database: str,
    library: dict[str, str],
    drain: Callable[[], int],
) -> None:
    create_tenant(migrated_database, "globex")
    create_collection(api, "support", tenant="globex")
    secret = ingest(api, tenant="globex", text="Globex merger plans.").json()["document_id"]
    drain()

    acme_hits = results(search(api, "Globex merger plans.", top_k=50))
    globex_hits = results(search(api, "Globex merger plans.", tenant="globex"))

    assert secret not in {hit["document_id"] for hit in acme_hits}
    assert [hit["document_id"] for hit in globex_hits] == [secret]


def test_modality_filter_excludes_other_sources(api: TestClient, library: dict[str, str]) -> None:
    assert results(search(api, "refund", modalities=["transcript"])) == []


@pytest.mark.parametrize("body", [{"top_k": 0}, {"top_k": 51}, {"mode": "fuzzy"}, {"query": ""}])
def test_invalid_requests_are_rejected(api: TestClient, body: dict[str, Any]) -> None:
    response = api.post(
        "/v1/search",
        json={"query": "refund"} | body,
        headers=AUTHENTICATED,
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


def test_search_returns_one_meaning_match_by_default(
    api: TestClient,
    library: dict[str, str],
) -> None:
    response = search(api, PASSWORD)

    assert response.json()["mode"] == "vector"
    (hit,) = results(response)
    assert hit["content"] == PASSWORD
    assert hit["keyword_score"] is None


def test_min_score_drops_weak_matches(api: TestClient, library: dict[str, str]) -> None:
    exact = results(search(api, PASSWORD, top_k=5, min_score=0.99))
    unrelated = results(search(api, "zebra crossing", top_k=5, min_score=0.5))

    assert [hit["content"] for hit in exact] == [PASSWORD]
    assert unrelated == []


def test_min_score_uses_meaning_similarity_in_hybrid_mode(
    api: TestClient,
    library: dict[str, str],
) -> None:
    hits = results(search(api, REFUND, mode="hybrid", top_k=5, min_score=0.99))

    assert [hit["content"] for hit in hits] == [REFUND]
