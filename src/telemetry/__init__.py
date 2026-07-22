"""Expose the stable public interface of the telemetry domain.

Internal responsibilities are split across service, processing, reports,
cache, and configuration modules. Re-exporting the facade here preserves the
simple ``from src.telemetry import Telemetry, TelemetryError`` import.
"""

from src.telemetry.service import Telemetry, TelemetryError

__all__ = ["Telemetry", "TelemetryError"]
