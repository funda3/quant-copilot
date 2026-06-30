from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_healthz_status_code() -> None:
    response = client.get("/healthz")
    assert response.status_code == 200


def test_healthz_body_status_ok() -> None:
    response = client.get("/healthz")
    assert response.json()["status"] == "ok"


def test_healthz_body_contains_version() -> None:
    response = client.get("/healthz")
    assert "version" in response.json()


def test_healthz_version_is_non_empty_string() -> None:
    version = client.get("/healthz").json()["version"]
    assert isinstance(version, str)
    assert len(version) > 0


def test_healthz_version_matches_app_version() -> None:
    version = client.get("/healthz").json()["version"]
    assert version == app.version
