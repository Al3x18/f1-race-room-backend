"""Manage the persistent cache of generated telemetry PDFs.

The cache creates deterministic filenames, validates completed PDFs, publishes
staged files atomically, updates LRU timestamps, and enforces both document and
byte limits. It does not manage FastF1's separate upstream download cache.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import threading
import unicodedata
import uuid
from pathlib import Path
from typing import Optional


MIB = 1024 * 1024


class TelemetryCacheError(RuntimeError):
    pass


class TelemetryPdfCache:
    def __init__(
        self,
        cache_dir: str = "./telemetry_files_cache",
        max_docs: int = 100,
        max_bytes: int = 500 * MIB,
    ):
        self.cache_dir = Path(cache_dir)
        self.max_docs = max(1, int(max_docs))
        self.max_bytes = max(1, int(max_bytes))
        self._lock = threading.RLock()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._remove_orphaned_parts()
        self.enforce_limit()

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
        if Path(filename).name != filename or not filename.lower().endswith(".pdf"):
            raise TelemetryCacheError(f"Invalid cache filename: {filename}")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        return self.cache_dir / filename

    def _pdf_files(self) -> list[tuple[Path, os.stat_result]]:
        files = []
        for item in self.cache_dir.glob("*.pdf"):
            try:
                if item.is_file():
                    files.append((item, item.stat()))
            except FileNotFoundError:
                continue
        return sorted(files, key=lambda entry: entry[1].st_mtime_ns)

    @staticmethod
    def _is_complete_pdf(path: Path) -> bool:
        try:
            if path.stat().st_size < 5:
                return False
            with path.open("rb") as handle:
                return handle.read(5) == b"%PDF-"
        except (FileNotFoundError, OSError):
            return False

    def _remove_orphaned_parts(self) -> None:
        for part in self.cache_dir.glob(".*.part"):
            try:
                part.unlink()
            except FileNotFoundError:
                pass

    def get_cached_path(self, filename: str) -> Optional[str]:
        with self._lock:
            path = self._path_for(filename)
            if not path.exists():
                return None
            if not self._is_complete_pdf(path):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
                return None
            self.touch(path)
            return str(path)

    def prepare_output_path(self, filename: str) -> str:
        """Return an ephemeral path used while matplotlib generates the PDF."""
        self._path_for(filename)
        staging_dir = Path(tempfile.gettempdir()) / "f1-telemetry-pdf-staging"
        staging_dir.mkdir(parents=True, exist_ok=True)
        fd, output_path = tempfile.mkstemp(
            prefix=f"{Path(filename).stem}-",
            suffix=".pdf",
            dir=staging_dir,
        )
        os.close(fd)
        return output_path

    def commit_output(self, filename: str, generated_path: Path | str) -> str:
        """Atomically publish a complete PDF after reserving cache capacity."""
        source = Path(generated_path)
        target = self._path_for(filename)
        part_path = self.cache_dir / f".{filename}.{uuid.uuid4().hex}.part"

        try:
            if not self._is_complete_pdf(source):
                raise TelemetryCacheError(f"Generated telemetry PDF is incomplete: {source}")
            source_size = source.stat().st_size
            if source_size > self.max_bytes:
                raise TelemetryCacheError(
                    f"Generated PDF is {source_size} bytes, above cache limit {self.max_bytes}"
                )

            with self._lock:
                # Another process may have published the same deterministic file.
                if target.exists() and self._is_complete_pdf(target):
                    self.touch(target)
                    return str(target)

                self._evict_to_fit(incoming_size=source_size)
                shutil.copyfile(source, part_path)
                os.replace(part_path, target)
                self.touch(target)
                self.enforce_limit()
                return str(target)
        finally:
            try:
                source.unlink()
            except FileNotFoundError:
                pass
            try:
                part_path.unlink()
            except FileNotFoundError:
                pass

    @staticmethod
    def discard_output(generated_path: Path | str) -> None:
        try:
            Path(generated_path).unlink()
        except FileNotFoundError:
            pass

    def touch(self, file_path: Path | str) -> None:
        path = Path(file_path)
        try:
            os.utime(path, None)
        except FileNotFoundError:
            pass

    def _evict_to_fit(self, incoming_size: int = 0) -> None:
        files = self._pdf_files()
        total_bytes = sum(entry.st_size for _, entry in files)
        while files and (
            len(files) + (1 if incoming_size else 0) > self.max_docs
            or total_bytes + incoming_size > self.max_bytes
        ):
            oldest, oldest_stat = files.pop(0)
            try:
                oldest.unlink()
                total_bytes -= oldest_stat.st_size
            except FileNotFoundError:
                pass

        if incoming_size and (
            len(files) + 1 > self.max_docs or total_bytes + incoming_size > self.max_bytes
        ):
            raise TelemetryCacheError("Unable to reserve enough telemetry cache capacity")

    def enforce_limit(self) -> None:
        with self._lock:
            self._evict_to_fit()

    def stats(self) -> dict[str, int]:
        with self._lock:
            files = self._pdf_files()
            return {
                "documents": len(files),
                "bytes": sum(entry.st_size for _, entry in files),
                "max_documents": self.max_docs,
                "max_bytes": self.max_bytes,
            }
