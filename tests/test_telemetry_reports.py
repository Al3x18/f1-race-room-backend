from types import SimpleNamespace

import pandas as pd

from src.telemetry.reports import TelemetryReportBuilder


class FakeSession:
    @staticmethod
    def get_circuit_info():
        return SimpleNamespace(corners=pd.DataFrame())


def _lap(lap_time):
    return SimpleNamespace(
        LapTime=pd.to_timedelta(lap_time, unit="s"),
        Sector1Time=pd.to_timedelta(30, unit="s"),
        Sector2Time=pd.to_timedelta(35, unit="s"),
        Sector3Time=pd.to_timedelta(lap_time - 65, unit="s"),
        Team="Test Team",
        Compound="SOFT",
        TyreLife=3,
        IsPersonalBest=True,
    )


def _telemetry(lap_time):
    return pd.DataFrame(
        {
            "Distance": [0.0, 1000.0, 2000.0, 3000.0],
            "Time": pd.to_timedelta(
                [0.0, lap_time / 3, 2 * lap_time / 3, lap_time],
                unit="s",
            ),
            "Speed": [100.0, 250.0, 180.0, 100.0],
            "Throttle": [50.0, 100.0, 75.0, 40.0],
            "Brake": [False, False, True, True],
        }
    )


def _builder():
    return TelemetryReportBuilder(
        year=2026,
        track_name="Test Track",
        session="Q",
        driver_name="AAA",
        max_plot_points=1200,
    )


def test_single_report_builder_creates_pdf(tmp_path):
    output_path = tmp_path / "single.pdf"

    result = _builder().build_fastest_lap_plot(
        FakeSession(),
        _telemetry(90.0),
        _lap(90.0),
        str(output_path),
    )

    assert result == str(output_path)
    assert output_path.read_bytes().startswith(b"%PDF-")


def test_comparison_report_builder_creates_pdf(tmp_path):
    output_path = tmp_path / "comparison.pdf"

    result = _builder().build_comparison_plot(
        FakeSession(),
        "AAA",
        "BBB",
        _lap(90.0),
        _lap(91.0),
        _telemetry(90.0),
        _telemetry(91.0),
        str(output_path),
    )

    assert result == str(output_path)
    assert output_path.read_bytes().startswith(b"%PDF-")
