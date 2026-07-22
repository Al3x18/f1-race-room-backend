from types import SimpleNamespace

import pandas as pd
import pytest

from src.telemetry.processing import format_lap_time
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


def test_format_lap_time_preserves_gap_sign_when_drivers_are_swapped():
    antonelli = pd.to_timedelta(104.361, unit="s")
    hamilton = pd.to_timedelta(104.895, unit="s")

    assert format_lap_time(antonelli - hamilton) == "-0:00.534"
    assert format_lap_time(hamilton - antonelli) == "0:00.534"


def test_format_lap_time_does_not_wrap_negative_gap_to_previous_minute():
    gap = pd.to_timedelta(-0.534, unit="s")

    assert format_lap_time(gap) != "-1:59.466"


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (10.0, "0:10.000"),
        (-10.0, "-0:10.000"),
        (59.999, "0:59.999"),
        (-59.999, "-0:59.999"),
        (70.250, "1:10.250"),
        (-70.250, "-1:10.250"),
        (600.0, "10:00.000"),
        (-600.0, "-10:00.000"),
    ],
)
def test_format_lap_time_supports_large_positive_and_negative_gaps(seconds, expected):
    assert format_lap_time(pd.to_timedelta(seconds, unit="s")) == expected


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
