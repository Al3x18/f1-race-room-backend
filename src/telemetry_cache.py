from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path
from typing import Optional


class TelemetryPdfCache:
    def __init__(self, cache_dir: str = "./telemetry_files_cache", max_docs: int = 20):
        self.cache_dir = Path(cache_dir)
        self.max_docs = max(1, int(max_docs))
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _slugify(value: str, default: str = "na") -> str:
        if value is None:
            return default
        normalized = unicodedata.normalize("NFKD", str(value))
        ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
        slug = re.sub(r"[^a-zA-Z0-9]+", "_", ascii_value.strip().lower())
        slug = re.sub(r"_+", "_", slug).strip("_")
        return slug or default

    @staticmethod
    def _session_slug(session: str) -> str:
        key = str(session or "").strip().lower()
        mapping = {
            "r": "race",
            "race": "race",
            "q": "qualifying",
            "qualifying": "qualifying",
            "sq": "sprint_qualifying",
            "sprint_qualifying": "sprint_qualifying",
            "ss": "sprint_shootout",
            "sprint_shootout": "sprint_shootout",
            "s": "sprint",
            "sprint": "sprint",
            "fp1": "fp1",
            "fp2": "fp2",
            "fp3": "fp3",
            "practice 1": "fp1",
            "practice 2": "fp2",
            "practice 3": "fp3",
        }
        return mapping.get(key, TelemetryPdfCache._slugify(key, default="session"))

    def single_filename(self, year: int, track_name: str, session: str, driver_name: str) -> str:
        driver = self._slugify(driver_name, default="driver")
        track = self._slugify(track_name, default="track")
        session_slug = self._session_slug(session)
        year_slug = self._slugify(str(year), default="year")
        return f"{driver}_{track}_{session_slug}_{year_slug}.pdf"

    def comparison_filename(
        self,
        year: int,
        track_name: str,
        session: str,
        driver_a: str,
        driver_b: str,
    ) -> str:
        first = self._slugify(driver_a, default="drivera")
        second = self._slugify(driver_b, default="driverb")
        track = self._slugify(track_name, default="track")
        session_slug = self._session_slug(session)
        year_slug = self._slugify(str(year), default="year")
        return f"{first}_vs_{second}_{track}_{session_slug}_{year_slug}.pdf"

    def _path_for(self, filename: str) -> Path:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        return self.cache_dir / filename

    def get_cached_path(self, filename: str) -> Optional[str]:
        path = self._path_for(filename)
        if not path.exists():
            return None
        self.touch(path)
        return str(path)

    def prepare_output_path(self, filename: str) -> str:
        path = self._path_for(filename)
        if not path.exists():
            files = sorted(
                (item for item in self.cache_dir.glob("*.pdf") if item.is_file()),
                key=lambda item: item.stat().st_mtime,
            )
            while len(files) >= self.max_docs:
                oldest = files.pop(0)
                try:
                    oldest.unlink()
                except FileNotFoundError:
                    pass
        return str(path)

    def touch(self, file_path: Path | str) -> None:
        path = Path(file_path)
        if path.exists():
            os.utime(path, None)

    def enforce_limit(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        files = sorted(
            (item for item in self.cache_dir.glob("*.pdf") if item.is_file()),
            key=lambda item: item.stat().st_mtime,
        )
        while len(files) > self.max_docs:
            oldest = files.pop(0)
            try:
                oldest.unlink()
            except FileNotFoundError:
                pass
