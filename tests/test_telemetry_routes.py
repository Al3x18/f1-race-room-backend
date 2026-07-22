from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.app_settings import AppSettings
from src.server import create_app
from src.telemetry import (
    DriverTelemetryUnavailableError,
    SessionUnavailableError,
    Telemetry,
    TelemetryArtifactError,
    TelemetryError,
    TelemetryGenerationError,
    TelemetryProviderError,
)


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
        "code": "MISSING_REQUIRED_PARAMETERS",
        "detail": "Missing required parameters: year, trackName, session, driverName",
    }


def test_comparison_route_reports_missing_parameters(monkeypatch, tmp_path):
    _configure_cache(monkeypatch, tmp_path)
    app = create_app(settings=AppSettings(allowed_origins=["*"]))

    with TestClient(app) as client:
        response = client.get("/get-telemetry-compare?year=2026")

    assert response.status_code == 400
    assert response.json() == {
        "code": "MISSING_REQUIRED_PARAMETERS",
        "detail": (
            "Missing required parameters: year, trackName, session, driverA, driverB"
        )
    }


def test_telemetry_route_rejects_invalid_year_type(monkeypatch, tmp_path):
    _configure_cache(monkeypatch, tmp_path)
    app = create_app(settings=AppSettings(allowed_origins=["*"]))

    with TestClient(app) as client:
        response = client.get(
            "/get-telemetry"
            "?year=invalid&trackName=Monza&session=Q&driverName=HAM"
        )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["query", "year"]


def test_single_telemetry_route_reports_unavailable_session(monkeypatch, tmp_path):
    _configure_cache(monkeypatch, tmp_path)

    def unavailable_session(self, output_path):
        raise SessionUnavailableError("Session unavailable: 2026 Abu Dhabi Q")

    monkeypatch.setattr(Telemetry, "get_fl_telemetry", unavailable_session)
    app = create_app(settings=AppSettings(allowed_origins=["*"]))

    with TestClient(app) as client:
        response = client.get(
            "/get-telemetry"
            "?year=2026&trackName=Abu%20Dhabi&session=Q&driverName=HAM"
        )

    assert response.status_code == 404
    assert response.json() == {
        "code": "SESSION_UNAVAILABLE",
        "detail": "The requested session is not available."
    }


def test_comparison_route_reports_unavailable_session(monkeypatch, tmp_path):
    _configure_cache(monkeypatch, tmp_path)

    def unavailable_session(self, driver_a, driver_b, output_path):
        raise SessionUnavailableError("Session unavailable: 2026 Abu Dhabi Q")

    monkeypatch.setattr(
        Telemetry,
        "get_comparison_telemetry_pdf",
        unavailable_session,
    )
    app = create_app(settings=AppSettings(allowed_origins=["*"]))

    with TestClient(app) as client:
        response = client.get(
            "/get-telemetry-compare"
            "?year=2026&trackName=Abu%20Dhabi&session=Q"
            "&driverA=HAM&driverB=LEC"
        )

    assert response.status_code == 404
    assert response.json() == {
        "code": "SESSION_UNAVAILABLE",
        "detail": "The requested session is not available."
    }


@pytest.mark.parametrize(
    (
        "method_name",
        "url",
        "error",
        "expected_status",
        "expected_code",
        "expected_detail",
    ),
    [
        (
            "get_fl_telemetry",
            "/get-telemetry"
            "?year=2026&trackName=Monza&session=Q&driverName=HAM",
            FileNotFoundError("private/generated/path.pdf"),
            500,
            "TELEMETRY_FILE_UNAVAILABLE",
            "The generated telemetry file is unavailable.",
        ),
        (
            "get_comparison_telemetry_pdf",
            "/get-telemetry-compare"
            "?year=2026&trackName=Monza&session=Q&driverA=HAM&driverB=LEC",
            FileNotFoundError("private/generated/path.pdf"),
            500,
            "TELEMETRY_FILE_UNAVAILABLE",
            "The generated telemetry file is unavailable.",
        ),
        (
            "get_fl_telemetry",
            "/get-telemetry"
            "?year=2026&trackName=Monza&session=Q&driverName=XXX",
            DriverTelemetryUnavailableError("No laps found for driver XXX"),
            404,
            "DRIVER_TELEMETRY_UNAVAILABLE",
            "Telemetry is not available for the requested driver.",
        ),
        (
            "get_comparison_telemetry_pdf",
            "/get-telemetry-compare"
            "?year=2026&trackName=Monza&session=Q&driverA=HAM&driverB=XXX",
            DriverTelemetryUnavailableError("No laps found for driver XXX"),
            404,
            "DRIVER_TELEMETRY_UNAVAILABLE",
            "Telemetry is not available for the requested driver.",
        ),
        (
            "get_fl_telemetry",
            "/get-telemetry"
            "?year=2026&trackName=Monza&session=Q&driverName=HAM",
            TelemetryProviderError("provider connection failed"),
            502,
            "TELEMETRY_PROVIDER_UNAVAILABLE",
            "The telemetry data provider is temporarily unavailable.",
        ),
        (
            "get_fl_telemetry",
            "/get-telemetry"
            "?year=2026&trackName=Monza&session=Q&driverName=HAM",
            TelemetryGenerationError("matplotlib failed"),
            500,
            "TELEMETRY_GENERATION_FAILED",
            "An internal error occurred while generating telemetry.",
        ),
        (
            "get_fl_telemetry",
            "/get-telemetry"
            "?year=2026&trackName=Monza&session=Q&driverName=HAM",
            TelemetryArtifactError("private/generated/path.pdf"),
            500,
            "TELEMETRY_FILE_UNAVAILABLE",
            "The generated telemetry file is unavailable.",
        ),
        (
            "get_fl_telemetry",
            "/get-telemetry"
            "?year=2026&trackName=Monza&session=Q&driverName=HAM",
            TelemetryError("unclassified telemetry failure"),
            400,
            "TELEMETRY_DATA_UNAVAILABLE",
            "Could not process telemetry data. Please check the provided parameters.",
        ),
        (
            "get_fl_telemetry",
            "/get-telemetry"
            "?year=2026&trackName=Monza&session=Q&driverName=HAM",
            RuntimeError("private implementation detail"),
            500,
            "INTERNAL_SERVER_ERROR",
            "An internal server error occurred.",
        ),
        (
            "get_comparison_telemetry_pdf",
            "/get-telemetry-compare"
            "?year=2026&trackName=Monza&session=Q&driverA=HAM&driverB=LEC",
            RuntimeError("private implementation detail"),
            500,
            "INTERNAL_SERVER_ERROR",
            "An internal server error occurred.",
        ),
    ],
)
def test_telemetry_routes_translate_failures_without_leaking_details(
    monkeypatch,
    tmp_path,
    method_name,
    url,
    error,
    expected_status,
    expected_code,
    expected_detail,
):
    _configure_cache(monkeypatch, tmp_path)

    def fail_generation(self, *args):
        raise error

    monkeypatch.setattr(Telemetry, method_name, fail_generation)
    app = create_app(settings=AppSettings(allowed_origins=["*"]))

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(url)

    assert response.status_code == expected_status
    assert response.json() == {
        "code": expected_code,
        "detail": expected_detail,
    }
    assert str(error) not in response.text
