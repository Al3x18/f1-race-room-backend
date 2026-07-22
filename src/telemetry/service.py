"""Orchestrate FastF1 session loading and telemetry report generation.

``Telemetry`` is the domain facade used by HTTP routes: it loads sessions,
selects drivers and fastest laps, obtains car data, and delegates rendering to
``TelemetryReportBuilder``. Compatibility aliases preserve previous helper
access while implementations live in focused domain modules.
"""

from __future__ import annotations

import gc
import os
from typing import Any

import fastf1 as ff1

from src.fastf1_cache import fastf1_cache_guard
from src.telemetry.processing import (
    calculate_delta,
    downsample_telemetry,
    downsample_with_delta,
    format_lap_time,
    format_metric,
    prepare_telemetry,
)
from src.telemetry.reports import TelemetryReportBuilder, close_all_figures


class TelemetryError(RuntimeError):
    pass


class Telemetry:
    """Load FastF1 data and delegate PDF rendering to a report builder."""

    def __init__(
        self,
        year: int,
        track_name: str,
        session: str,
        driver_name: str,
        max_plot_points: int | None = None,
    ) -> None:
        self.year = year
        self.track_name = track_name
        self.session = session
        self.driver_name = driver_name
        if max_plot_points is None:
            self.max_plot_points = self._env_int(
                "TELEMETRY_MAX_PLOT_POINTS",
                default=1200,
                minimum=300,
            )
        else:
            self.max_plot_points = max(300, int(max_plot_points))

        self._reports = TelemetryReportBuilder(
            year=self.year,
            track_name=self.track_name,
            session=self.session,
            driver_name=self.driver_name,
            max_plot_points=self.max_plot_points,
        )

    @staticmethod
    def _env_int(name: str, default: int, minimum: int = 1) -> int:
        raw_value = os.getenv(name, str(default))
        try:
            parsed = int(raw_value)
        except (TypeError, ValueError):
            return default
        return parsed if parsed >= minimum else default

    def load_session_data(self):
        try:
            with fastf1_cache_guard():
                loaded_session = ff1.get_session(
                    self.year,
                    self.track_name,
                    self.session,
                )
                loaded_session.load(
                    laps=True,
                    telemetry=True,
                    weather=False,
                    messages=False,
                )
            return loaded_session
        except Exception as exc:
            raise TelemetryError(f"Error loading session data: {exc}") from exc

    def get_fl_telemetry(self, output_path: str | None = None) -> str:
        session = None
        try:
            session = self.load_session_data()
            driver_laps = session.laps.pick_drivers(self.driver_name)
            if driver_laps.empty:
                raise TelemetryError(f"No laps found for driver {self.driver_name}")

            fastest_lap = driver_laps.pick_fastest()
            telemetry = fastest_lap.get_car_data(interpolate_edges=True).add_distance()
            return self.build_fastest_lap_plot(
                session,
                telemetry,
                fastest_lap,
                output_path=output_path,
            )
        finally:
            session = None
            close_all_figures()
            gc.collect()

    def get_comparison_telemetry_pdf(
        self,
        driver_a: str,
        driver_b: str,
        output_path: str | None = None,
    ) -> str:
        session = None
        try:
            session = self.load_session_data()
            laps_a = session.laps.pick_drivers(driver_a)
            laps_b = session.laps.pick_drivers(driver_b)
            if laps_a.empty:
                raise TelemetryError(f"No laps found for driver {driver_a}")
            if laps_b.empty:
                raise TelemetryError(f"No laps found for driver {driver_b}")

            lap_a = laps_a.pick_fastest()
            lap_b = laps_b.pick_fastest()
            telemetry_a = lap_a.get_car_data(interpolate_edges=True).add_distance()
            telemetry_b = lap_b.get_car_data(interpolate_edges=True).add_distance()

            return self.build_comparison_plot(
                session=session,
                driver_a=driver_a,
                driver_b=driver_b,
                lap_a=lap_a,
                lap_b=lap_b,
                telemetry_a=telemetry_a,
                telemetry_b=telemetry_b,
                output_path=output_path,
            )
        finally:
            session = None
            close_all_figures()
            gc.collect()

    def build_fastest_lap_plot(
        self,
        session: Any,
        telemetry: Any,
        fastest_lap: Any,
        output_path: str | None = None,
    ) -> str:
        """Keep the existing facade while delegating report rendering."""
        try:
            return self._reports.build_fastest_lap_plot(
                session,
                telemetry,
                fastest_lap,
                output_path,
            )
        except Exception as exc:
            raise TelemetryError(f"Error generating telemetry plot: {exc}") from exc

    def build_comparison_plot(
        self,
        session: Any,
        driver_a: str,
        driver_b: str,
        lap_a: Any,
        lap_b: Any,
        telemetry_a: Any,
        telemetry_b: Any,
        output_path: str | None = None,
    ) -> str:
        """Keep the existing facade while delegating report rendering."""
        try:
            return self._reports.build_comparison_plot(
                session,
                driver_a,
                driver_b,
                lap_a,
                lap_b,
                telemetry_a,
                telemetry_b,
                output_path,
            )
        except Exception as exc:
            raise TelemetryError(
                f"Error generating comparison telemetry plot: {exc}"
            ) from exc

    @staticmethod
    def _metric(series, op, default="N/A", decimals=1, suffix=""):
        return format_metric(series, op, default, decimals, suffix)

    # Compatibility aliases keep existing private helper call sites working
    # while their implementations live in focused modules.
    _format_lap_time = staticmethod(format_lap_time)
    _prepare_telemetry = staticmethod(prepare_telemetry)
    _downsample_telemetry = staticmethod(downsample_telemetry)
    _downsample_with_delta = staticmethod(downsample_with_delta)
    _calculate_delta = staticmethod(calculate_delta)
    _extract_corner_markers = staticmethod(
        TelemetryReportBuilder._extract_corner_markers
    )
    _add_corner_axis = staticmethod(TelemetryReportBuilder._add_corner_axis)
    _select_annotation_ticks = staticmethod(
        TelemetryReportBuilder._select_annotation_ticks
    )
    _annotate_speed_markers = staticmethod(
        TelemetryReportBuilder._annotate_speed_markers
    )
    _style_data_axis = staticmethod(TelemetryReportBuilder._style_data_axis)
    _draw_stat_card = staticmethod(TelemetryReportBuilder._draw_stat_card)
