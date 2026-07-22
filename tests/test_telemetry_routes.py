from pathlib import Path

from fastapi.testclient import TestClient

from src.app_settings import AppSettings
from src.server import create_app
from src.telemetry import Telemetry


PDF_BYTES = b"%PDF-1.4\n%%EOF\n"


def _configure_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEMETRY_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("TELEMETRY_CACHE_MAX_DOCS", "10")
    monkeypatch.setenv("TELEMETRY_CACHE_MAX_MB", "10")


def test_single_telemetry_route_generates_then_uses_cache(
    monkeypatch,
    tmp_path,
):
    _configure_cache(monkeypatch, tmp_path)
    calls = []

    def fake_generate(self, output_path):
        calls.append(output_path)
        Path(output_path).write_bytes(PDF_BYTES)
        return output_path

    monkeypatch.setattr(Telemetry, "get_fl_telemetry", fake_generate)
    app = create_app(settings=AppSettings(allowed_origins=["*"]))
    url = "/get-telemetry?year=2026&trackName=Belgian&session=R&driverName=ANT"

    with TestClient(app) as client:
        first = client.get(url)
        second = client.get(url)

    assert first.status_code == 200
    assert first.headers["content-type"] == "application/pdf"
    assert first.content == PDF_BYTES
    assert second.status_code == 200
    assert second.content == PDF_BYTES
    assert len(calls) == 1


def test_comparison_route_preserves_driver_arguments(monkeypatch, tmp_path):
    _configure_cache(monkeypatch, tmp_path)
    received = []

    def fake_generate(self, driver_a, driver_b, output_path):
        received.append((driver_a, driver_b))
        Path(output_path).write_bytes(PDF_BYTES)
        return output_path

    monkeypatch.setattr(Telemetry, "get_comparison_telemetry_pdf", fake_generate)
    app = create_app(settings=AppSettings(allowed_origins=["*"]))

    with TestClient(app) as client:
        response = client.get(
            "/get-telemetry-compare"
            "?year=2026&trackName=Belgian&session=R&driverA=ANT&driverB=HAM"
        )

    assert response.status_code == 200
    assert response.content == PDF_BYTES
    assert received == [("ANT", "HAM")]


def test_telemetry_routes_keep_missing_parameter_response(monkeypatch, tmp_path):
    _configure_cache(monkeypatch, tmp_path)
    app = create_app(settings=AppSettings(allowed_origins=["*"]))

    with TestClient(app) as client:
        response = client.get("/get-telemetry?year=2026")

    assert response.status_code == 400
    assert response.json() == {
        "error": "Missing required parameters: year, trackName, session, driverName"
    }
