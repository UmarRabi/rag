from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.settings import get_settings
from app.ml.provider import LocalModels
from tests.integration.client import ingest, search

pytestmark = pytest.mark.model

ARTICLES = {
    "Password reset": "Open Settings, choose Security and click Reset password.",
    "Refunds": "Refunds reach your card within five business days.",
    "Shipping": "We deliver nationwide in two to four days.",
    "Invoices": "Download invoices from the Billing page.",
}

QUESTIONS = [
    ("I forgot my login credentials", "Password reset"),
    ("When will I get my money back?", "Refunds"),
    ("How long does delivery take?", "Shipping"),
    ("Où trouver ma facture ?", "Invoices"),
    ("¿Cómo cambio mi contraseña?", "Password reset"),
]


@pytest.fixture(scope="module")
def local_models() -> LocalModels:
    return LocalModels(get_settings())


@pytest.fixture
def models(local_models: LocalModels) -> Any:
    return local_models


@pytest.fixture
def articles(api: TestClient, drain: Callable[[], int]) -> None:
    for title, text in ARTICLES.items():
        ingest(api, title=title, text=text)
    drain()


@pytest.mark.parametrize(("question", "expected"), QUESTIONS)
@pytest.mark.parametrize("mode", ["hybrid", "vector"])
def test_questions_find_the_right_article(
    api: TestClient,
    articles: None,
    question: str,
    expected: str,
    mode: str,
) -> None:
    (top, *_) = search(api, question, mode=mode).json()["results"]

    assert top["title"] == expected
