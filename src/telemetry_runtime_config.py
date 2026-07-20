from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

import tomllib


@dataclass(frozen=True)
class TelemetryRuntimeConfig:
    max_concurrency: int = 2
    max_plot_points: int = 1200
    cache_dir: str = "./telemetry_files_cache"
    cache_max_docs: int = 100
    cache_max_mb: int = 500

    @staticmethod
    def _parse_int(value: Any, default: int, minimum: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return parsed if parsed >= minimum else default

    @staticmethod
    def _parse_str(value: Any, default: str) -> str:
        if value is None:
            return default
        result = str(value).strip()
        return result or default

    @classmethod
    def load(cls) -> "TelemetryRuntimeConfig":
        config_path = os.getenv("TELEMETRY_CONFIG_FILE", "./config/telemetry.toml")
        file_data: Dict[str, Any] = {}
        path = Path(config_path)
        if path.exists() and path.is_file():
            try:
                file_data = tomllib.loads(path.read_text(encoding="utf-8"))
            except Exception:
                file_data = {}

        # Environment variables override the file so Railway can configure the
        # mounted volume without modifying the image.
        max_concurrency = cls._parse_int(
            os.getenv("TELEMETRY_MAX_CONCURRENCY", file_data.get("max_concurrency", 2)),
            default=2,
            minimum=1,
        )
        max_plot_points = cls._parse_int(
            os.getenv("TELEMETRY_MAX_PLOT_POINTS", file_data.get("max_plot_points", 1200)),
            default=1200,
            minimum=300,
        )
        cache_dir = cls._parse_str(
            os.getenv(
                "TELEMETRY_CACHE_DIR",
                file_data.get("cache_dir", "./telemetry_files_cache"),
            ),
            default="./telemetry_files_cache",
        )
        cache_max_docs = cls._parse_int(
            os.getenv(
                "TELEMETRY_CACHE_MAX_DOCS",
                file_data.get("cache_max_docs", 100),
            ),
            default=100,
            minimum=1,
        )
        cache_max_mb = cls._parse_int(
            os.getenv(
                "TELEMETRY_CACHE_MAX_MB",
                file_data.get("cache_max_mb", 500),
            ),
            default=500,
            minimum=1,
        )

        return cls(
            max_concurrency=max_concurrency,
            max_plot_points=max_plot_points,
            cache_dir=cache_dir,
            cache_max_docs=cache_max_docs,
            cache_max_mb=cache_max_mb,
        )
