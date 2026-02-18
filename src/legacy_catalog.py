from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Tuple

import fastf1 as ff1


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    # NaN check that works without importing pandas.
    return isinstance(value, float) and value != value


def _clean(value: Any) -> Any:
    if _is_missing(value):
        return None
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    return value


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def _session_code(session_name: str) -> str:
    key = _norm(session_name)
    mapping = {
        "practice 1": "FP1",
        "practice 2": "FP2",
        "practice 3": "FP3",
        "qualifying": "Q",
        "race": "R",
        "sprint": "S",
        "sprint qualifying": "SQ",
        "sprint shootout": "SS",
    }
    return mapping.get(key, session_name)


@dataclass
class _CacheEntry:
    ts: float
    value: Any


class LegacyCatalogService:
    """FastF1-backed discovery endpoints for year -> events -> drivers."""

    def __init__(self, ttl_sec: int = 300) -> None:
        self._ttl_sec = ttl_sec
        self._lock = threading.Lock()
        self._events_cache: Dict[int, _CacheEntry] = {}
        self._drivers_cache: Dict[Tuple[int, str, str], _CacheEntry] = {}

    def _get_cache(self, cache: Dict[Any, _CacheEntry], key: Any) -> Any:
        now = time.monotonic()
        with self._lock:
            entry = cache.get(key)
            if entry and (now - entry.ts) < self._ttl_sec:
                return entry.value
        return None

    def _set_cache(self, cache: Dict[Any, _CacheEntry], key: Any, value: Any) -> None:
        with self._lock:
            cache[key] = _CacheEntry(ts=time.monotonic(), value=value)

    def get_events(self, year: int) -> List[Dict[str, Any]]:
        cached = self._get_cache(self._events_cache, year)
        if cached is not None:
            return cached

        schedule = ff1.get_event_schedule(year)
        if schedule is None or schedule.empty:
            return []

        rows: List[Dict[str, Any]] = []
        for _, row in schedule.iterrows():
            sessions = []
            for idx in range(1, 6):
                session_name = _clean(row.get(f"Session{idx}"))
                session_date = _clean(row.get(f"Session{idx}Date"))
                if not session_name:
                    continue
                sessions.append(
                    {
                        "name": session_name,
                        "code": _session_code(str(session_name)),
                        "date": session_date,
                    }
                )

            rows.append(
                {
                    "round_number": _clean(row.get("RoundNumber")),
                    "event_name": _clean(row.get("EventName")),
                    "official_event_name": _clean(row.get("OfficialEventName")),
                    "country": _clean(row.get("Country")),
                    "location": _clean(row.get("Location")),
                    "event_format": _clean(row.get("EventFormat")),
                    "event_date": _clean(row.get("EventDate")),
                    "sessions": sessions,
                }
            )

        rows.sort(key=lambda item: (item.get("round_number") or 999, item.get("event_name") or ""))
        self._set_cache(self._events_cache, year, rows)
        return rows

    def get_years(self, start_year: int = 2018) -> List[int]:
        current_year = self.current_season()
        years: List[int] = []
        for year in range(start_year, current_year + 1):
            try:
                schedule = ff1.get_event_schedule(year)
            except Exception:
                continue
            if schedule is not None and not schedule.empty:
                years.append(year)
        return years

    def get_drivers(self, year: int, track_name: str, session: str) -> List[Dict[str, Any]]:
        key = (year, _norm(track_name), _norm(session))
        cached = self._get_cache(self._drivers_cache, key)
        if cached is not None:
            return cached

        loaded = ff1.get_session(year, track_name, session)
        loaded.load(telemetry=False, weather=False, messages=False)

        from_laps = set()
        laps = getattr(loaded, "laps", None)
        if laps is not None and not laps.empty and "Driver" in laps.columns:
            for value in laps["Driver"].dropna().tolist():
                from_laps.add(str(value).upper())

        results_rows: List[Dict[str, Any]] = []
        results = getattr(loaded, "results", None)
        if results is not None and not results.empty:
            for _, row in results.iterrows():
                abbr = str(_clean(row.get("Abbreviation")) or "").upper()
                if not abbr:
                    continue
                results_rows.append(
                    {
                        "driver_code": abbr,
                        "driver_number": _clean(row.get("DriverNumber")),
                        "full_name": _clean(row.get("FullName")),
                        "team_name": _clean(row.get("TeamName")),
                        "available_telemetry": abbr in from_laps,
                    }
                )

        if not results_rows:
            results_rows = [
                {
                    "driver_code": abbr,
                    "driver_number": None,
                    "full_name": None,
                    "team_name": None,
                    "available_telemetry": True,
                }
                for abbr in sorted(from_laps)
            ]

        # Keep telemetry-available drivers first.
        results_rows.sort(
            key=lambda item: (
                not bool(item.get("available_telemetry")),
                str(item.get("driver_code") or ""),
            )
        )
        self._set_cache(self._drivers_cache, key, results_rows)
        return results_rows

    def current_season(self) -> int:
        return datetime.utcnow().year
