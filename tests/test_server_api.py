from fastapi.testclient import TestClient

from src.app_settings import AppSettings
from src.server import create_app


def test_status_reports_telemetry_service_without_live_provider():
    app = create_app(settings=AppSettings(allowed_origins=["*"]))

    with TestClient(app) as client:
        response = client.get("/status")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["service"] == "telemetry"
    assert "provider" not in response.json()


def test_root_and_health_are_public_but_api_remains_protected():
    settings = AppSettings(
        api_request_key="a-private-test-key",
        allowed_origins=["*"],
    )
    app = create_app(settings=settings)

    with TestClient(app) as client:
        root_response = client.get("/")
        assert root_response.status_code == 200
        assert "<script" not in root_response.text.lower()
        assert "generazioni simultanee" in root_response.text
        assert "FP1, FP2, FP3, Q, SQ, SS, S oppure R" in root_response.text
        assert "marcia, RPM, DRS" not in root_response.text
        assert client.get("/health").status_code == 200
        assert client.get("/status").status_code == 401
        assert (
            client.get(
                "/status",
                headers={"X-API-Key": "a-private-test-key"},
            ).status_code
            == 200
        )


def test_live_routes_are_not_exposed():
    settings = AppSettings(
        api_request_key="a-private-test-key",
        allowed_origins=["*"],
    )
    app = create_app(settings=settings)

    with TestClient(app) as client:
        response = client.get(
            "/live/timing/snapshot",
            headers={"X-API-Key": "a-private-test-key"},
        )

    assert response.status_code == 404
