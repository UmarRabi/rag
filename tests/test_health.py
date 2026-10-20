import pytest
from fastapi import status
from fastapi.testclient import TestClient


def test_live_reports_ok(client: TestClient) -> None:
    response = client.get("/health/live")

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"status": "ok"}


@pytest.mark.integration
def test_ready_reports_pgvector(client: TestClient) -> None:
    response = client.get("/health/ready")

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["status"] == "ready"
    assert body["database"] is True
    assert body["pgvector"]
