from types import SimpleNamespace

import pytest
from fastf1.exceptions import (
    DataNotLoadedError,
    InvalidSessionError,
    NoLapDataError,
)

from src.telemetry import (
    DriverTelemetryUnavailableError,
    SessionUnavailableError,
    Telemetry,
    TelemetryGenerationError,
    TelemetryProviderError,
)
from src.telemetry import service as telemetry_service


@pytest.mark.parametrize(
    "method_name,args",
    [
        ("get_fl_telemetry", ()),
        ("get_comparison_telemetry_pdf", ("HAM", "LEC")),
    ],
)
def test_missing_fastf1_lap_data_is_an_unavailable_session(
    monkeypatch,
    method_name,
    args,
):
    class SessionWithoutLoadedLaps:
        @property
        def laps(self):
            raise DataNotLoadedError("laps")

    telemetry = Telemetry(2026, "Abu Dhabi", "Q", "HAM")
    monkeypatch.setattr(
        telemetry,
        "load_session_data",
        lambda: SessionWithoutLoadedLaps(),
    )

    with pytest.raises(
        SessionUnavailableError,
        match="Session unavailable: 2026 Abu Dhabi Q",
    ):
        getattr(telemetry, method_name)(*args)


def test_empty_fastf1_laps_are_an_unavailable_session(monkeypatch):
    telemetry = Telemetry(2026, "Abu Dhabi", "Q", "HAM")
    session = SimpleNamespace(laps=SimpleNamespace(empty=True))
    monkeypatch.setattr(telemetry, "load_session_data", lambda: session)

    with pytest.raises(SessionUnavailableError):
        telemetry.get_fl_telemetry()


@pytest.mark.parametrize(
    "fastf1_error",
    [
        DataNotLoadedError("laps"),
        InvalidSessionError("qualifying"),
        NoLapDataError("laps"),
    ],
)
def test_fastf1_session_errors_are_normalized(monkeypatch, fastf1_error):
    telemetry = Telemetry(2026, "Abu Dhabi", "Q", "HAM")

    def fail_session_lookup(*args):
        raise fastf1_error

    monkeypatch.setattr(telemetry_service.ff1, "get_session", fail_session_lookup)

    with pytest.raises(SessionUnavailableError) as caught:
        telemetry.load_session_data()

    assert caught.value.__cause__ is fastf1_error


def test_unexpected_session_load_error_is_a_provider_error(monkeypatch):
    telemetry = Telemetry(2026, "Monza", "Q", "HAM")

    def fail_session_lookup(*args):
        raise RuntimeError("provider connection failed")

    monkeypatch.setattr(telemetry_service.ff1, "get_session", fail_session_lookup)

    with pytest.raises(
        TelemetryProviderError,
        match="Error loading session data",
    ) as caught:
        telemetry.load_session_data()

    assert isinstance(caught.value.__cause__, RuntimeError)


@pytest.mark.parametrize(
    ("method_name", "args", "missing_driver"),
    [
        ("get_fl_telemetry", (), "HAM"),
        ("get_comparison_telemetry_pdf", ("HAM", "LEC"), "HAM"),
        ("get_comparison_telemetry_pdf", ("HAM", "LEC"), "LEC"),
    ],
)
def test_missing_driver_laps_are_a_driver_unavailable_error(
    monkeypatch,
    method_name,
    args,
    missing_driver,
):
    class LoadedLaps:
        empty = False

        @staticmethod
        def pick_drivers(driver):
            return SimpleNamespace(empty=driver == missing_driver)

    telemetry = Telemetry(2026, "Monza", "Q", "HAM")
    monkeypatch.setattr(
        telemetry,
        "load_session_data",
        lambda: SimpleNamespace(laps=LoadedLaps()),
    )

    with pytest.raises(
        DriverTelemetryUnavailableError,
        match=f"No laps found for driver {missing_driver}",
    ):
        getattr(telemetry, method_name)(*args)


@pytest.mark.parametrize(
    ("method_name", "report_method", "args", "expected_message"),
    [
        (
            "build_fastest_lap_plot",
            "build_fastest_lap_plot",
            (None, None, None),
            "Error generating telemetry plot",
        ),
        (
            "build_comparison_plot",
            "build_comparison_plot",
            (None, "HAM", "LEC", None, None, None, None),
            "Error generating comparison telemetry plot",
        ),
    ],
)
def test_report_generation_errors_are_normalized(
    monkeypatch,
    method_name,
    report_method,
    args,
    expected_message,
):
    telemetry = Telemetry(2026, "Monza", "Q", "HAM")

    def fail_report(*args):
        raise RuntimeError("matplotlib failed")

    monkeypatch.setattr(telemetry._reports, report_method, fail_report)

    with pytest.raises(TelemetryGenerationError, match=expected_message) as caught:
        getattr(telemetry, method_name)(*args)

    assert isinstance(caught.value.__cause__, RuntimeError)
