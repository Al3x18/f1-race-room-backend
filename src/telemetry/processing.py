"""Provide reusable, side-effect-free telemetry transformations.

The functions prepare and downsample FastF1 data, format report values, and
calculate the distance-normalized comparison delta. No session loading, HTTP
handling, filesystem writes, or Matplotlib rendering occurs in this module.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np


def format_lap_time(lap_time: Any) -> str:
    """Format lap times and signed gaps without wrapping negative values.

    ``timedelta`` values use floor division semantics. Formatting ``-0.534``
    seconds directly with ``// 60`` and ``% 60`` would therefore produce the
    misleading ``-1:59.466``. Convert the complete value to milliseconds
    first, split its absolute magnitude, and add the sign only at the end.
    """
    if lap_time is None:
        return "N/A"
    try:
        total_seconds = float(lap_time.total_seconds())
        if not np.isfinite(total_seconds):
            return "N/A"
    except Exception:
        return "N/A"

    total_milliseconds = int(round(total_seconds * 1000.0))
    sign = "-" if total_milliseconds < 0 else ""
    minutes, remaining_milliseconds = divmod(abs(total_milliseconds), 60_000)
    seconds = remaining_milliseconds / 1000.0
    return f"{sign}{minutes}:{seconds:06.3f}"


def format_metric(
    series: Any,
    operation: Callable[[Any], Any],
    default: str = "N/A",
    decimals: int = 1,
    suffix: str = "",
) -> str:
    if series is None:
        return default
    try:
        if len(series) == 0:
            return default
        value = operation(series)
        if value is None:
            return default
        return f"{float(value):.{decimals}f}{suffix}"
    except Exception:
        return default


def prepare_telemetry(telemetry: Any) -> Any:
    if telemetry is None:
        return telemetry
    if "Distance" not in telemetry.columns:
        telemetry = telemetry.copy()
        telemetry["Distance"] = np.arange(len(telemetry), dtype=float)
    return telemetry


def downsample_telemetry(telemetry: Any, max_points: int) -> Any:
    if telemetry is None or max_points <= 0:
        return telemetry
    total_rows = len(telemetry.index)
    if total_rows <= max_points:
        return telemetry
    step = max(1, int(np.ceil(total_rows / max_points)))
    return telemetry.iloc[::step].reset_index(drop=True)


def downsample_with_delta(
    telemetry: Any,
    delta_time: Any,
    max_points: int,
) -> tuple[Any, Any]:
    if telemetry is None or max_points <= 0:
        return telemetry, delta_time
    if len(telemetry.index) <= max_points:
        return telemetry, delta_time

    sampled = downsample_telemetry(telemetry, max_points)
    if delta_time is None or len(delta_time) != len(telemetry):
        return sampled, delta_time

    payload = telemetry.copy()
    payload["_delta_time"] = np.asarray(delta_time, dtype=float)
    sampled_payload = downsample_telemetry(payload, max_points)
    sampled_delta = np.asarray(sampled_payload.pop("_delta_time"), dtype=float)
    return sampled_payload, sampled_delta


def calculate_delta(
    lap_a: Any,
    lap_b: Any,
    telemetry_a: Any,
    telemetry_b: Any,
) -> tuple[Any, Any, Any]:
    """Calculate the lap-time delta without FastF1's deprecated helper.

    FastF1 deprecated ``utils.delta_time`` without providing an official
    replacement. Suppressing its warning would leave this endpoint tied to an
    API that may be removed, so the small interpolation is owned here.

    FastF1 recommends validating an interpolated delta against the recorded
    sector-time differences (or another independent source), because the
    continuous telemetry-derived curve is only an approximation. Sector times
    provide reliable checkpoints rather than a continuous curve, so they
    cannot directly replace the delta plot produced by this endpoint.

    FUTURE ACCURACY CHECK: validation with real Belgian GP 2026 race data
    produced an exact finish-line gap but deviations of up to about 0.15 s at
    intermediate sector checkpoints. This is acceptable for the current
    comparison plot and preserves the deprecated helper's behavior. If the
    endpoint is later used for analytical timing, consider anchoring the
    interpolated curve to the official cumulative S1, S2 and lap-time gaps.

    Lap A is the reference and lap B is interpolated on lap A's distance axis.
    The sign is expressed from the first selected driver's point of view:
    positive means that lap A reached the point later than lap B (A is behind),
    while negative means that lap A reached it earlier (A is ahead).

    ``lap_a`` and ``lap_b`` are intentionally retained in the signature so
    callers of the previous internal helper do not need to change.
    """
    del lap_a, lap_b

    try:
        reference_distance = np.asarray(telemetry_a["Distance"], dtype=float)
        comparison_distance = np.asarray(telemetry_b["Distance"], dtype=float)
        reference_time = telemetry_a["Time"].dt.total_seconds().to_numpy(dtype=float)
        comparison_time = telemetry_b["Time"].dt.total_seconds().to_numpy(dtype=float)

        if len(reference_distance) < 2 or len(comparison_distance) < 2:
            raise ValueError("not enough telemetry samples")

        # FastF1 can return usable laps while warning that their car data is
        # incomplete. Exclude invalid samples instead of rejecting the report.
        reference_mask = np.isfinite(reference_distance) & np.isfinite(reference_time)
        comparison_mask = np.isfinite(comparison_distance) & np.isfinite(comparison_time)
        if reference_mask.sum() < 2 or comparison_mask.sum() < 2:
            raise ValueError("not enough finite telemetry samples")

        valid_reference_distance = reference_distance[reference_mask]
        valid_reference_time = reference_time[reference_mask]
        valid_comparison_distance = comparison_distance[comparison_mask]
        valid_comparison_time = comparison_time[comparison_mask]

        # np.interp requires an increasing x-axis. Repeated distance samples
        # can occur in incomplete telemetry, so discard duplicates/backtracking.
        previous_maximum = np.maximum.accumulate(
            np.concatenate(([-np.inf], valid_comparison_distance[:-1]))
        )
        increasing = valid_comparison_distance > previous_maximum
        valid_comparison_distance = valid_comparison_distance[increasing]
        valid_comparison_time = valid_comparison_time[increasing]
        if len(valid_comparison_distance) < 2:
            raise ValueError("comparison distance is not increasing")

        comparison_length = valid_comparison_distance[-1]
        reference_length = valid_reference_distance[-1]
        if comparison_length <= 0.0 or reference_length <= 0.0:
            raise ValueError("invalid telemetry distance")

        # ``Distance`` is integrated independently from each driver's sampled
        # speed. Normalize lap B before comparing both at the same track point.
        scaled_comparison_distance = (
            valid_comparison_distance * reference_length / comparison_length
        )

        # Extrapolate one sample at both ends to avoid flat clipping when the
        # streams start or finish a sample apart.
        distance_start_step = (
            scaled_comparison_distance[1] - scaled_comparison_distance[0]
        )
        distance_end_step = (
            scaled_comparison_distance[-1] - scaled_comparison_distance[-2]
        )
        time_start_step = valid_comparison_time[1] - valid_comparison_time[0]
        time_end_step = valid_comparison_time[-1] - valid_comparison_time[-2]
        interpolation_distance = np.concatenate(
            (
                [scaled_comparison_distance[0] - distance_start_step],
                scaled_comparison_distance,
                [scaled_comparison_distance[-1] + distance_end_step],
            )
        )
        interpolation_time = np.concatenate(
            (
                [valid_comparison_time[0] - time_start_step],
                valid_comparison_time,
                [valid_comparison_time[-1] + time_end_step],
            )
        )

        delta_time = np.full(len(reference_distance), np.nan, dtype=float)
        comparison_time_on_reference = np.interp(
            valid_reference_distance,
            interpolation_distance,
            interpolation_time,
        )
        # Report the gap from the first selected driver's point of view.
        # Positive: A is slower/behind B. Negative: A is faster/ahead of B.
        delta_time[reference_mask] = valid_reference_time - comparison_time_on_reference
        return delta_time, telemetry_a, telemetry_b
    except Exception:
        return None, telemetry_a, telemetry_b
