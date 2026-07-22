"""Render single-driver and comparison telemetry reports with Matplotlib.

``TelemetryReportBuilder`` owns the shared visual language, annotations, plot
layouts, and PDF output for both report types. It consumes already-loaded data
and delegates numerical transformations to ``telemetry.processing``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib
import numpy as np

matplotlib.use("Agg")

import matplotlib.pyplot as plt

from src.telemetry.processing import (
    calculate_delta,
    downsample_telemetry,
    downsample_with_delta,
    format_lap_time,
    format_metric,
    prepare_telemetry,
)


def close_all_figures() -> None:
    plt.close("all")


class TelemetryReportBuilder:
    """Render telemetry data that has already been loaded from FastF1."""

    def __init__(
        self,
        year: int,
        track_name: str,
        session: str,
        driver_name: str,
        max_plot_points: int,
    ) -> None:
        self.year = year
        self.track_name = track_name
        self.session = session
        self.driver_name = driver_name
        self.max_plot_points = max_plot_points

    @staticmethod
    def _extract_corner_markers(session: Any, telemetry: Any, distance: Any):
        corner_ticks = []
        corner_labels = []
        try:
            circuit = session.get_circuit_info()
            corners = getattr(circuit, "corners", None)
            if corners is None or corners.empty:
                return [], []

            if "Distance" in corners.columns:
                for _, corner in corners.iterrows():
                    number = corner.get("Number")
                    corner_distance = corner.get("Distance")
                    if number is None or corner_distance is None:
                        continue
                    corner_ticks.append(float(corner_distance))
                    corner_labels.append(str(int(number)))
            else:
                x = telemetry.get("X")
                y = telemetry.get("Y")
                if x is None or y is None:
                    return [], []
                x_vals = np.asarray(x, dtype=float)
                y_vals = np.asarray(y, dtype=float)
                d_vals = np.asarray(distance, dtype=float)
                finite_mask = np.isfinite(x_vals) & np.isfinite(y_vals) & np.isfinite(d_vals)
                x_vals = x_vals[finite_mask]
                y_vals = y_vals[finite_mask]
                d_vals = d_vals[finite_mask]
                if len(x_vals) == 0:
                    return [], []

                for _, corner in corners.iterrows():
                    cx = corner.get("X")
                    cy = corner.get("Y")
                    number = corner.get("Number")
                    if cx is None or cy is None or number is None:
                        continue
                    distances = (x_vals - float(cx)) ** 2 + (y_vals - float(cy)) ** 2
                    nearest_idx = int(np.argmin(distances))
                    corner_ticks.append(float(d_vals[nearest_idx]))
                    corner_labels.append(str(int(number)))
        except Exception:
            return [], []

        dedup_ticks = []
        dedup_labels = []
        for tick, label in sorted(zip(corner_ticks, corner_labels), key=lambda item: item[0]):
            if dedup_ticks and abs(tick - dedup_ticks[-1]) < 8:
                continue
            dedup_ticks.append(tick)
            dedup_labels.append(label)
        return dedup_ticks, dedup_labels

    @staticmethod
    def _add_corner_axis(axis: Any, corner_ticks: list, corner_labels: list, offset=20):
        if not corner_ticks:
            return
        corner_axis = axis.secondary_xaxis("bottom")
        corner_axis.spines["bottom"].set_position(("outward", offset))
        corner_axis.spines["bottom"].set_color("#2e4358")
        corner_axis.set_xticks(corner_ticks)
        corner_axis.set_xticklabels(corner_labels)
        corner_axis.tick_params(axis="x", colors="#d8e5f6", labelsize=8, pad=1)
        corner_axis.set_xlabel("Corner #", color="#a9bdd2", labelpad=8)

    @staticmethod
    def _select_annotation_ticks(corner_ticks, min_gap=220.0, max_labels=10):
        selected = []
        for tick in corner_ticks:
            if selected and abs(float(tick) - float(selected[-1])) < min_gap:
                continue
            selected.append(float(tick))
            if len(selected) >= max_labels:
                break
        return selected

    @staticmethod
    def _annotate_speed_markers(
        axis,
        distance,
        speed,
        ticks,
        color,
        vertical="above",
        with_unit=False,
    ):
        if distance is None or speed is None or not ticks:
            return
        d_vals = np.asarray(distance, dtype=float)
        s_vals = np.asarray(speed, dtype=float)
        if len(d_vals) == 0 or len(s_vals) == 0:
            return

        finite_mask = np.isfinite(d_vals) & np.isfinite(s_vals)
        d_vals = d_vals[finite_mask]
        s_vals = s_vals[finite_mask]
        if len(d_vals) == 0:
            return

        for idx_tick, tick in enumerate(ticks):
            nearest_idx = int(np.argmin(np.abs(d_vals - tick)))
            speed_value = float(s_vals[nearest_idx])
            direction = 1.0 if vertical == "above" else -1.0
            y_offset = 8.0 + (idx_tick % 2) * 7.0
            label = f"{int(round(speed_value))}"
            if with_unit:
                label = f"{label} km/h"
            axis.text(
                float(d_vals[nearest_idx]),
                speed_value + direction * y_offset,
                label,
                color=color,
                fontsize=6.5,
                ha="center",
                va="bottom" if direction > 0 else "top",
                bbox={
                    "boxstyle": "round,pad=0.18",
                    "fc": "#0f1720",
                    "ec": color,
                    "lw": 0.7,
                    "alpha": 0.92,
                },
                clip_on=True,
                zorder=5,
            )

    @staticmethod
    def _style_data_axis(axis):
        axis.set_facecolor("#131d29")
        axis.tick_params(colors="#b8c6d8")
        for spine in axis.spines.values():
            spine.set_color("#31475d")

    @staticmethod
    def _draw_stat_card(axis, label, value, edge_color):
        axis.axis("off")
        axis.text(
            0.03,
            0.80,
            label,
            transform=axis.transAxes,
            ha="left",
            va="top",
            fontsize=9,
            color="#d8e5f6",
        )
        axis.text(
            0.03,
            0.18,
            value,
            transform=axis.transAxes,
            ha="left",
            va="bottom",
            fontsize=14,
            fontweight="bold",
            color="#f8fbff",
            bbox={
                "boxstyle": "round,pad=0.42",
                "fc": "#172435",
                "ec": edge_color,
                "lw": 1.1,
            },
        )

    @staticmethod
    def _resolve_output_path(output_path: str | None, default_filename: str) -> str:
        file_path = Path(output_path) if output_path else Path("telemetry_files") / default_filename
        file_path.parent.mkdir(parents=True, exist_ok=True)
        return str(file_path)

    def build_fastest_lap_plot(
        self,
        session,
        telemetry,
        fastest_lap,
        output_path: str | None = None,
    ) -> str:
        figure = None
        try:
            telemetry = prepare_telemetry(telemetry)
            speed = telemetry.get("Speed")
            throttle = telemetry.get("Throttle")
            brake = telemetry.get("Brake")

            lap_time_label = format_lap_time(getattr(fastest_lap, "LapTime", None))
            sector_1 = format_lap_time(getattr(fastest_lap, "Sector1Time", None))
            sector_2 = format_lap_time(getattr(fastest_lap, "Sector2Time", None))
            sector_3 = format_lap_time(getattr(fastest_lap, "Sector3Time", None))

            top_speed = format_metric(speed, lambda values: values.max(), suffix=" km/h")
            avg_speed = format_metric(speed, lambda values: values.mean(), suffix=" km/h")
            full_throttle = format_metric(
                throttle,
                lambda values: (values >= 98).mean() * 100.0,
                suffix="%",
            )
            brake_usage = format_metric(
                brake,
                lambda values: (values > 0).mean() * 100.0,
                suffix="%",
            )

            telemetry = downsample_telemetry(telemetry, self.max_plot_points)
            distance = telemetry.get("Distance")
            speed = telemetry.get("Speed")
            throttle = telemetry.get("Throttle")
            brake_pct = telemetry.get("Brake")
            if brake_pct is not None:
                brake_pct = brake_pct * 100.0

            figure = plt.figure(figsize=(16, 11), facecolor="#0f1720")
            grid = figure.add_gridspec(
                4,
                1,
                height_ratios=[0.85, 2.2, 1.45, 1.45],
                hspace=0.18,
            )

            ax_header = figure.add_subplot(grid[0, 0])
            ax_speed = figure.add_subplot(grid[1, 0])
            ax_throttle = figure.add_subplot(grid[2, 0], sharex=ax_speed)
            ax_brake = figure.add_subplot(grid[3, 0], sharex=ax_speed)

            for axis in (ax_speed, ax_throttle, ax_brake):
                self._style_data_axis(axis)

            ax_header.axis("off")
            title = (
                f"{self.driver_name} | {self.track_name} {self.year} {self.session} | "
                f"Fastest Lap {lap_time_label}"
            )
            ax_header.text(
                0.01,
                0.78,
                "F1 Telemetry Report",
                fontsize=21,
                fontweight="bold",
                color="#f5f8ff",
            )
            ax_header.text(0.01, 0.43, title, fontsize=11.5, color="#b8c6d8")

            metadata_line = (
                f"Team: {getattr(fastest_lap, 'Team', 'N/A')}   "
                f"Compound: {getattr(fastest_lap, 'Compound', 'N/A')}   "
                f"Tyre life: {getattr(fastest_lap, 'TyreLife', 'N/A')} laps   "
                f"Personal best: "
                f"{'Yes' if bool(getattr(fastest_lap, 'IsPersonalBest', False)) else 'No'}"
            )
            ax_header.text(0.01, 0.14, metadata_line, fontsize=10, color="#9bb0c7")

            kpis = [
                ("Top Speed", top_speed),
                ("Avg Speed", avg_speed),
                ("Full Throttle", full_throttle),
                ("Brake Usage", brake_usage),
                ("Sectors", f"S1 {sector_1} | S2 {sector_2} | S3 {sector_3}"),
            ]
            x_positions = [0.56, 0.69, 0.82, 0.56, 0.69]
            y_positions = [0.70, 0.70, 0.70, 0.24, 0.24]
            for idx, (label, value) in enumerate(kpis):
                ax_header.text(
                    x_positions[idx],
                    y_positions[idx],
                    f"{label}\n{value}",
                    ha="left",
                    va="center",
                    fontsize=10,
                    color="#f2f7ff",
                    bbox={
                        "boxstyle": "round,pad=0.42",
                        "fc": "#1c2a3a",
                        "ec": "#36516b",
                        "lw": 1.0,
                    },
                )

            if speed is not None:
                ax_speed.plot(distance, speed, color="#4ea8ff", linewidth=2.2, label="Speed")
            ax_speed.set_title("Speed Profile", color="#eff5ff", fontsize=12, pad=10)
            ax_speed.set_ylabel("km/h", color="#c8d5e5")
            ax_speed.grid(color="#203144", alpha=0.5, linewidth=0.7)
            if speed is not None:
                ax_speed.legend(loc="upper right", frameon=False, labelcolor="#d8e5f6")

            corner_ticks, corner_labels = self._extract_corner_markers(
                session,
                telemetry,
                distance,
            )

            if throttle is not None:
                ax_throttle.plot(
                    distance,
                    throttle,
                    color="#34d399",
                    linewidth=1.8,
                    label="Throttle %",
                )
            ax_throttle.set_title("Throttle", color="#eff5ff", fontsize=12, pad=8)
            ax_throttle.set_ylabel("%", color="#c8d5e5")
            ax_throttle.set_ylim(-2, 104)
            ax_throttle.grid(color="#203144", alpha=0.5, linewidth=0.7)
            if throttle is not None:
                ax_throttle.legend(loc="upper right", frameon=False, labelcolor="#d8e5f6")

            if brake_pct is not None:
                ax_brake.plot(
                    distance,
                    brake_pct,
                    color="#f97316",
                    linewidth=1.7,
                    label="Brake %",
                )
            ax_brake.set_title("Brake", color="#eff5ff", fontsize=12, pad=8)
            ax_brake.set_xlabel("Distance (m)", color="#c8d5e5")
            ax_brake.set_ylabel("%", color="#c8d5e5")
            ax_brake.set_ylim(-2, 104)
            ax_brake.grid(color="#203144", alpha=0.5, linewidth=0.7)
            if brake_pct is not None:
                ax_brake.legend(loc="upper right", frameon=False, labelcolor="#d8e5f6")

            if corner_ticks:
                self._add_corner_axis(ax_speed, corner_ticks, corner_labels, offset=20)
                self._add_corner_axis(ax_throttle, corner_ticks, corner_labels, offset=20)
                self._add_corner_axis(ax_brake, corner_ticks, corner_labels, offset=22)
                self._annotate_speed_markers(
                    ax_speed,
                    distance,
                    speed,
                    self._select_annotation_ticks(corner_ticks, min_gap=260.0, max_labels=8),
                    color="#9ed4ff",
                    vertical="above",
                    with_unit=True,
                )

            file_path = self._resolve_output_path(
                output_path,
                f"{self.driver_name}_{self.session}_{self.track_name}_{self.year}.pdf",
            )
            figure.savefig(file_path, bbox_inches="tight", facecolor=figure.get_facecolor())
            return file_path
        finally:
            if figure is not None:
                plt.close(figure)

    def build_comparison_plot(
        self,
        session,
        driver_a,
        driver_b,
        lap_a,
        lap_b,
        telemetry_a,
        telemetry_b,
        output_path: str | None = None,
    ) -> str:
        figure = None
        try:
            telemetry_a = prepare_telemetry(telemetry_a)
            telemetry_b = prepare_telemetry(telemetry_b)
            delta_time, telemetry_a, telemetry_b = calculate_delta(
                lap_a,
                lap_b,
                telemetry_a,
                telemetry_b,
            )
            telemetry_a, delta_time = downsample_with_delta(
                prepare_telemetry(telemetry_a),
                delta_time,
                self.max_plot_points,
            )
            telemetry_b = downsample_telemetry(
                prepare_telemetry(telemetry_b),
                self.max_plot_points,
            )

            distance_a = telemetry_a.get("Distance")
            distance_b = telemetry_b.get("Distance")
            speed_a = telemetry_a.get("Speed")
            speed_b = telemetry_b.get("Speed")
            throttle_a = telemetry_a.get("Throttle")
            throttle_b = telemetry_b.get("Throttle")
            brake_a = telemetry_a.get("Brake")
            brake_b = telemetry_b.get("Brake")
            brake_a_pct = brake_a * 100.0 if brake_a is not None else None
            brake_b_pct = brake_b * 100.0 if brake_b is not None else None

            lap_time_a = format_lap_time(getattr(lap_a, "LapTime", None))
            lap_time_b = format_lap_time(getattr(lap_b, "LapTime", None))
            # Keep the total gap consistent with the delta graph: it is always
            # shown from the first selected driver's point of view. A positive
            # value means driver A is slower; a negative value means A is ahead.
            lap_time_delta = getattr(lap_a, "LapTime", None) - getattr(lap_b, "LapTime", None)
            delta_total = format_lap_time(lap_time_delta)

            figure = plt.figure(figsize=(16, 14.4), facecolor="#0f1720")
            grid = figure.add_gridspec(
                5,
                1,
                height_ratios=[2.15, 2.05, 1.2, 1.35, 1.35],
                hspace=0.22,
            )
            header_grid = grid[0, 0].subgridspec(
                2,
                4,
                height_ratios=[1.35, 1.0],
                hspace=0.52,
                wspace=0.28,
            )
            ax_header = figure.add_subplot(header_grid[0, :])
            stat_axes = [figure.add_subplot(header_grid[1, index]) for index in range(4)]
            ax_speed = figure.add_subplot(grid[1, 0])
            ax_delta = figure.add_subplot(grid[2, 0], sharex=ax_speed)
            ax_throttle = figure.add_subplot(grid[3, 0], sharex=ax_speed)
            ax_brake = figure.add_subplot(grid[4, 0], sharex=ax_speed)

            for axis in (ax_speed, ax_delta, ax_throttle, ax_brake):
                self._style_data_axis(axis)

            color_a = "#38bdf8"
            color_b = "#f59e0b"
            ax_header.axis("off")
            ax_header.text(
                0.01,
                0.97,
                "F1 Telemetry Comparison",
                fontsize=23,
                fontweight="bold",
                color="#f5f8ff",
                ha="left",
                va="top",
            )
            ax_header.text(
                0.01,
                0.42,
                f"{self.track_name} {self.year} {self.session} | {driver_a} vs {driver_b}",
                fontsize=12,
                color="#b8c6d8",
                ha="left",
                va="center",
            )
            ax_header.text(
                0.01,
                0.12,
                f"{driver_a}: {lap_time_a}    {driver_b}: {lap_time_b}    gap: {delta_total}",
                fontsize=10.5,
                color="#9bb0c7",
                ha="left",
                va="center",
            )

            stat_cards = (
                (f"{driver_a} top speed", format_metric(speed_a, lambda s: s.max(), suffix=" km/h"), color_a),
                (f"{driver_b} top speed", format_metric(speed_b, lambda s: s.max(), suffix=" km/h"), color_b),
                (f"{driver_a} avg speed", format_metric(speed_a, lambda s: s.mean(), suffix=" km/h"), color_a),
                (f"{driver_b} avg speed", format_metric(speed_b, lambda s: s.mean(), suffix=" km/h"), color_b),
            )
            for axis, (label, value, color) in zip(stat_axes, stat_cards):
                self._draw_stat_card(axis, label, value, color)

            if speed_a is not None:
                ax_speed.plot(
                    distance_a,
                    speed_a,
                    color=color_a,
                    linewidth=2.0,
                    label=f"{driver_a} speed",
                )
            if speed_b is not None:
                ax_speed.plot(
                    distance_b,
                    speed_b,
                    color=color_b,
                    linewidth=2.0,
                    label=f"{driver_b} speed",
                )
            ax_speed.set_title("Speed Overlay", color="#eff5ff", fontsize=12, pad=14)
            ax_speed.set_ylabel("km/h", color="#c8d5e5")
            ax_speed.grid(color="#203144", alpha=0.5, linewidth=0.7)
            ax_speed.legend(loc="upper right", frameon=False, labelcolor="#d8e5f6")

            if delta_time is not None and len(delta_time) == len(distance_a):
                ax_delta.axhline(
                    0.0,
                    color="#9bb0c7",
                    linewidth=0.9,
                    alpha=0.6,
                    linestyle="--",
                )
                ax_delta.plot(distance_a, delta_time, color="#f8fafc", linewidth=1.5)
                positive = np.where(delta_time >= 0.0, delta_time, np.nan)
                negative = np.where(delta_time < 0.0, delta_time, np.nan)
                ax_delta.fill_between(distance_a, 0.0, positive, color=color_b, alpha=0.18)
                ax_delta.fill_between(distance_a, 0.0, negative, color=color_a, alpha=0.18)
                ax_delta.text(
                    0.01,
                    0.90,
                    f"+ = {driver_a} slower vs {driver_b}",
                    transform=ax_delta.transAxes,
                    color=color_b,
                    fontsize=8,
                )
                ax_delta.text(
                    0.01,
                    0.78,
                    f"- = {driver_a} ahead of {driver_b}",
                    transform=ax_delta.transAxes,
                    color=color_a,
                    fontsize=8,
                )
                ax_delta.grid(color="#203144", alpha=0.5, linewidth=0.7)
            else:
                ax_delta.text(
                    0.5,
                    0.5,
                    "Delta time unavailable",
                    color="#9bb0c7",
                    fontsize=10,
                    ha="center",
                    va="center",
                )
            ax_delta.set_title("Delta Time", color="#eff5ff", fontsize=12, pad=14)
            ax_delta.set_ylabel("sec", color="#c8d5e5")

            if throttle_a is not None:
                ax_throttle.plot(
                    distance_a,
                    throttle_a,
                    color=color_a,
                    linewidth=1.8,
                    label=f"{driver_a} throttle",
                )
            if throttle_b is not None:
                ax_throttle.plot(
                    distance_b,
                    throttle_b,
                    color=color_b,
                    linewidth=1.8,
                    label=f"{driver_b} throttle",
                )
            ax_throttle.set_title("Throttle Overlay", color="#eff5ff", fontsize=12, pad=14)
            ax_throttle.set_ylabel("%", color="#c8d5e5")
            ax_throttle.set_ylim(-2, 104)
            ax_throttle.grid(color="#203144", alpha=0.5, linewidth=0.7)
            ax_throttle.legend(loc="upper right", frameon=False, labelcolor="#d8e5f6")

            if brake_a_pct is not None:
                ax_brake.plot(
                    distance_a,
                    brake_a_pct,
                    color=color_a,
                    linewidth=1.7,
                    label=f"{driver_a} brake",
                )
            if brake_b_pct is not None:
                ax_brake.plot(
                    distance_b,
                    brake_b_pct,
                    color=color_b,
                    linewidth=1.7,
                    label=f"{driver_b} brake",
                )
            ax_brake.set_title("Brake Overlay", color="#eff5ff", fontsize=12, pad=14)
            ax_brake.set_xlabel("Distance (m)", color="#c8d5e5")
            ax_brake.set_ylabel("%", color="#c8d5e5")
            ax_brake.set_ylim(-2, 104)
            ax_brake.grid(color="#203144", alpha=0.5, linewidth=0.7)
            ax_brake.legend(loc="upper right", frameon=False, labelcolor="#d8e5f6")

            for axis in (ax_speed, ax_delta, ax_throttle):
                axis.tick_params(labelbottom=False)

            corner_ticks, _ = self._extract_corner_markers(
                session,
                telemetry_a,
                distance_a,
            )
            if corner_ticks:
                selected_ticks = self._select_annotation_ticks(
                    corner_ticks,
                    min_gap=340.0,
                    max_labels=6,
                )
                self._annotate_speed_markers(
                    ax_speed,
                    distance_a,
                    speed_a,
                    selected_ticks,
                    color=color_a,
                    vertical="above",
                )
                self._annotate_speed_markers(
                    ax_speed,
                    distance_b,
                    speed_b,
                    selected_ticks,
                    color=color_b,
                    vertical="below",
                )

            file_path = self._resolve_output_path(
                output_path,
                (
                    f"{driver_a}_{driver_b}_{self.session}_{self.track_name}_"
                    f"{self.year}_comparison.pdf"
                ),
            )
            figure.savefig(file_path, bbox_inches="tight", facecolor=figure.get_facecolor())
            return file_path
        finally:
            if figure is not None:
                plt.close(figure)
