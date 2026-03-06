from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Protocol

import fastf1 as ff1
import httpx

from src.fastf1_cache import disable_fastf1_cache, fastf1_cache_guard


class ProviderError(RuntimeError):
    pass


_MICROSECTOR_STATUS_MAP = {
    0: "no_data",
    2048: "slower",
    2049: "improved",
    2050: "unknown",
    2051: "best_overall",
    2052: "unknown",
    2064: "pitlane",
    2068: "unknown",
}


def microsector_status_label(code: Any) -> str:
    try:
        value = int(code)
    except (TypeError, ValueError):
        return "unknown"
    return _MICROSECTOR_STATUS_MAP.get(value, "unknown")


class LiveProvider(Protocol):
    name: str

    async def fetch_current_session(self) -> Dict[str, Any]:
        ...

    async def fetch_timing_snapshot(self, session_key: Optional[int] = None) -> Dict[str, Any]:
        ...


class OpenF1Provider:
    name = "openf1"

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        username: str = "",
        password: str = "",
        token_url: str = "https://api.openf1.org/token",
        token_refresh_sec: int = 120,
        verify_ssl: bool = True,
        timeout_sec: float = 8.0,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._username = username
        self._password = password
        self._token_url = token_url
        self._token_refresh_sec = max(30, token_refresh_sec)
        self._verify_ssl = verify_ssl
        self._timeout_sec = timeout_sec
        self._client = client
        self._last_session_key: Optional[int] = None
        self._cache: Dict[str, List[Dict[str, Any]]] = {}
        self._cache_ts: Dict[str, float] = {}
        self._oauth_token: str = ""
        self._oauth_token_expiry_monotonic: float = 0.0
        self._oauth_lock = asyncio.Lock()

    async def _get_bearer_token(self) -> str:
        if self._api_key:
            return self._api_key

        if not self._username or not self._password:
            return ""

        now = time.monotonic()
        if self._oauth_token and now < self._oauth_token_expiry_monotonic:
            return self._oauth_token

        async with self._oauth_lock:
            now = time.monotonic()
            if self._oauth_token and now < self._oauth_token_expiry_monotonic:
                return self._oauth_token

            client = self._client
            owns_client = client is None
            if client is None:
                client = httpx.AsyncClient(timeout=self._timeout_sec, verify=self._verify_ssl)

            try:
                response = await client.post(
                    self._token_url,
                    data={
                        "username": self._username,
                        "password": self._password,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                response.raise_for_status()
                payload = response.json()
                access_token = payload.get("access_token")
                if not access_token:
                    raise ProviderError("OpenF1 auth response missing access_token")

                expires_in = self._safe_int(payload.get("expires_in"), default=3600)
                valid_for = max(30, expires_in - self._token_refresh_sec)
                self._oauth_token = str(access_token)
                self._oauth_token_expiry_monotonic = time.monotonic() + valid_for
                return self._oauth_token
            except httpx.HTTPError as exc:
                raise ProviderError(f"OpenF1 auth token request failed: {exc}") from exc
            finally:
                if owns_client:
                    await client.aclose()

    async def warmup(self) -> None:
        """Eagerly fetch auth token on startup when using username/password auth."""
        if self._api_key:
            return
        if not self._username or not self._password:
            return
        await self._get_bearer_token()

    async def _get(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Any:
        client = self._client
        owns_client = client is None
        if client is None:
            client = httpx.AsyncClient(timeout=self._timeout_sec, verify=self._verify_ssl)

        try:
            url = f"{self._base_url}/{endpoint.lstrip('/')}"
            for attempt in range(2):
                headers = {}
                token = await self._get_bearer_token()
                if token:
                    headers["Authorization"] = f"Bearer {token}"

                response = await client.get(url, params=params, headers=headers)
                if (
                    response.status_code == 401
                    and attempt == 0
                    and not self._api_key
                    and self._username
                    and self._password
                ):
                    # Token may be expired or revoked; force refresh and retry once.
                    self._oauth_token = ""
                    self._oauth_token_expiry_monotonic = 0.0
                    continue

                response.raise_for_status()
                return response.json()

            raise ProviderError(f"OpenF1 request failed for {endpoint}: unauthorized")
        except httpx.HTTPError as exc:
            raise ProviderError(f"OpenF1 request failed for {endpoint}: {exc}") from exc
        finally:
            if owns_client:
                await client.aclose()

    @staticmethod
    def _select_latest_session(sessions: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not sessions:
            raise ProviderError("OpenF1 returned no sessions")

        def _parse_date(raw: Any) -> datetime:
            if not raw:
                return datetime.min.replace(tzinfo=timezone.utc)
            value = str(raw).replace("Z", "+00:00")
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return datetime.min.replace(tzinfo=timezone.utc)

        return max(sessions, key=lambda item: (_parse_date(item.get("date_start")), item.get("session_key", 0)))

    @staticmethod
    def _safe_int(value: Any, default: int = 999) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _parse_dt(value: Any) -> datetime:
        if not value:
            return datetime.min.replace(tzinfo=timezone.utc)
        raw = str(value).replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            return datetime.min.replace(tzinfo=timezone.utc)

    @staticmethod
    def _driver_number(value: Any) -> Optional[int]:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _recent_iso_utc(window_sec: int = 25) -> str:
        return (datetime.now(timezone.utc) - timedelta(seconds=max(1, window_sec))).isoformat()

    def _latest_row(self, rows: List[Dict[str, Any]], date_field: str = "date") -> Dict[str, Any]:
        if not rows:
            return {}
        return max(rows, key=lambda row: self._parse_dt(row.get(date_field)))

    def _reset_session_cache_if_needed(self, session_key: Optional[int]) -> None:
        if session_key is None:
            return
        if self._last_session_key == session_key:
            return
        self._last_session_key = session_key
        self._cache.clear()
        self._cache_ts.clear()

    async def _get_cached(
        self,
        endpoint: str,
        params: Dict[str, Any],
        ttl_sec: float,
        required: bool = False,
    ) -> List[Dict[str, Any]]:
        now = time.monotonic()
        cached = self._cache.get(endpoint)
        cached_ts = self._cache_ts.get(endpoint, 0.0)
        if cached is not None and (now - cached_ts) < ttl_sec:
            return cached

        try:
            payload = await self._get(endpoint, params=params)
            if not isinstance(payload, list):
                raise ProviderError(f"OpenF1 {endpoint} response is invalid")
            self._cache[endpoint] = payload
            self._cache_ts[endpoint] = now
            return payload
        except Exception as exc:
            if cached is not None:
                return cached
            if required:
                raise ProviderError(f"OpenF1 {endpoint} unavailable: {exc}") from exc
            return []

    def _latest_by_driver(
        self,
        rows: List[Dict[str, Any]],
        sort_fn,
    ) -> Dict[int, Dict[str, Any]]:
        latest: Dict[int, Dict[str, Any]] = {}
        for row in rows:
            driver_number = self._driver_number(row.get("driver_number"))
            if driver_number is None:
                continue
            current = latest.get(driver_number)
            if current is None or sort_fn(row) > sort_fn(current):
                latest[driver_number] = row
        return latest

    @staticmethod
    def _lap_time_seconds(value: Any) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            result = float(value)
            return result if result > 0 else None
        raw = str(value).strip()
        if not raw:
            return None
        try:
            return float(raw)
        except ValueError:
            pass
        if ":" in raw:
            try:
                minutes, seconds = raw.split(":", 1)
                return (int(minutes) * 60.0) + float(seconds)
            except (TypeError, ValueError):
                return None
        return None

    def _best_lap_by_driver(self, laps: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
        best: Dict[int, Dict[str, Any]] = {}
        for row in laps:
            driver_number = self._driver_number(row.get("driver_number"))
            if driver_number is None:
                continue
            duration = self._lap_time_seconds(row.get("lap_duration"))
            if duration is None:
                continue
            current = best.get(driver_number)
            if current is None:
                best[driver_number] = row
                continue
            current_duration = self._lap_time_seconds(current.get("lap_duration"))
            if current_duration is None or duration < current_duration:
                best[driver_number] = row
        return best

    def _calculate_laps_on_tyre(
        self,
        active_stint: Dict[str, Any],
        latest_lap: Dict[str, Any],
    ) -> Optional[int]:
        if not active_stint:
            return None

        lap_start = self._safe_int(active_stint.get("lap_start"), default=-1)
        tyre_age_start = self._safe_int(active_stint.get("tyre_age_at_start"), default=0)
        latest_lap_number = self._safe_int(latest_lap.get("lap_number"), default=-1)

        if lap_start < 1 or latest_lap_number < 1:
            return tyre_age_start if tyre_age_start >= 0 else None

        laps_since_stint_start = max(0, latest_lap_number - lap_start + 1)
        return max(0, tyre_age_start + laps_since_stint_start)

    def _estimate_in_pit(
        self,
        latest_lap: Dict[str, Any],
        latest_pit: Dict[str, Any],
    ) -> bool:
        if not latest_pit:
            return False

        if bool(latest_lap.get("is_pit_out_lap")):
            return False

        pit_dt = self._parse_dt(latest_pit.get("date"))
        lap_dt = self._parse_dt(latest_lap.get("date_start"))
        now = datetime.now(timezone.utc)

        # Best-effort heuristic: very recent pit event with no newer lap start.
        if pit_dt >= lap_dt and (now - pit_dt).total_seconds() <= 45:
            return True

        pit_lap = self._safe_int(latest_pit.get("lap_number"), default=-1)
        current_lap = self._safe_int(latest_lap.get("lap_number"), default=-1)
        return pit_lap > 0 and pit_lap == current_lap

    async def fetch_current_session(self) -> Dict[str, Any]:
        sessions = await self._get("sessions", params={"session_key": "latest"})
        if not isinstance(sessions, list) or not sessions:
            sessions = await self._get("sessions")

        latest = self._select_latest_session(sessions)
        return {
            "session_key": latest.get("session_key"),
            "session_name": latest.get("session_name"),
            "meeting_key": latest.get("meeting_key"),
            "meeting_name": latest.get("meeting_name"),
            "country_name": latest.get("country_name"),
            "date_start": latest.get("date_start"),
            "date_end": latest.get("date_end"),
        }

    async def fetch_timing_snapshot(self, session_key: Optional[int] = None) -> Dict[str, Any]:
        if session_key is None:
            current = await self.fetch_current_session()
            session_key = current.get("session_key")

        self._reset_session_cache_if_needed(session_key)
        params = {"session_key": session_key} if session_key is not None else {"session_key": "latest"}
        recent_params = dict(params)
        recent_params["date>"] = self._recent_iso_utc(25)

        (
            drivers,
            positions,
            intervals,
            laps,
            stints,
            pit_events,
            car_data,
            locations,
            weather,
            race_control,
            team_radio,
            overtakes,
        ) = await asyncio.gather(
            self._get_cached("drivers", params=params, ttl_sec=1800, required=False),
            self._get_cached("position", params=params, ttl_sec=0.6, required=False),
            self._get_cached("intervals", params=params, ttl_sec=0.6, required=False),
            self._get_cached("laps", params=params, ttl_sec=1.5, required=False),
            self._get_cached("stints", params=params, ttl_sec=4.0, required=False),
            self._get_cached("pit", params=params, ttl_sec=1.5, required=False),
            self._get_cached("car_data", params=recent_params, ttl_sec=0.7, required=False),
            self._get_cached("location", params=recent_params, ttl_sec=0.8, required=False),
            self._get_cached("weather", params=recent_params, ttl_sec=2.0, required=False),
            self._get_cached("race_control", params=recent_params, ttl_sec=1.2, required=False),
            self._get_cached("team_radio", params=recent_params, ttl_sec=1.2, required=False),
            self._get_cached("overtakes", params=recent_params, ttl_sec=1.5, required=False),
        )

        position_by_driver = self._latest_by_driver(
            positions,
            sort_fn=lambda row: self._parse_dt(row.get("date")),
        )
        intervals_by_driver = self._latest_by_driver(
            intervals,
            sort_fn=lambda row: self._parse_dt(row.get("date")),
        )
        laps_by_driver = self._latest_by_driver(
            laps,
            sort_fn=lambda row: (
                self._safe_int(row.get("lap_number"), default=-1),
                self._parse_dt(row.get("date_start")),
            ),
        )
        best_laps_by_driver = self._best_lap_by_driver(laps)
        stints_by_driver = self._latest_by_driver(
            stints,
            sort_fn=lambda row: (
                self._safe_int(row.get("stint_number"), default=-1),
                self._safe_int(row.get("lap_start"), default=-1),
            ),
        )
        pit_by_driver = self._latest_by_driver(
            pit_events,
            sort_fn=lambda row: (
                self._parse_dt(row.get("date")),
                self._safe_int(row.get("lap_number"), default=-1),
            ),
        )
        drivers_by_driver = self._latest_by_driver(
            drivers,
            sort_fn=lambda row: (
                self._safe_int(row.get("session_key"), default=-1),
                self._safe_int(row.get("meeting_key"), default=-1),
            ),
        )
        car_by_driver = self._latest_by_driver(
            car_data,
            sort_fn=lambda row: self._parse_dt(row.get("date")),
        )
        location_by_driver = self._latest_by_driver(
            locations,
            sort_fn=lambda row: self._parse_dt(row.get("date")),
        )

        if not any([drivers_by_driver, position_by_driver, intervals_by_driver, laps_by_driver]):
            raise ProviderError("OpenF1 returned empty live timing sources")

        driver_numbers = sorted(
            set(drivers_by_driver.keys())
            | set(position_by_driver.keys())
            | set(intervals_by_driver.keys())
            | set(laps_by_driver.keys())
            | set(stints_by_driver.keys())
            | set(pit_by_driver.keys())
            | set(car_by_driver.keys())
            | set(location_by_driver.keys())
        )

        normalized: List[Dict[str, Any]] = []
        for driver_number in driver_numbers:
            driver_meta = drivers_by_driver.get(driver_number, {})
            position = position_by_driver.get(driver_number, {})
            interval = intervals_by_driver.get(driver_number, {})
            latest_lap = laps_by_driver.get(driver_number, {})
            best_lap = best_laps_by_driver.get(driver_number, {})
            active_stint = stints_by_driver.get(driver_number, {})
            latest_pit = pit_by_driver.get(driver_number, {})
            latest_car = car_by_driver.get(driver_number, {})
            latest_location = location_by_driver.get(driver_number, {})

            row = {
                "driver_number": driver_number,
                "driver": {
                    "name_acronym": driver_meta.get("name_acronym"),
                    "broadcast_name": driver_meta.get("broadcast_name"),
                    "full_name": driver_meta.get("full_name"),
                    "first_name": driver_meta.get("first_name"),
                    "last_name": driver_meta.get("last_name"),
                    "country_code": driver_meta.get("country_code"),
                    "team_name": driver_meta.get("team_name"),
                    "team_colour": driver_meta.get("team_colour"),
                    "headshot_url": driver_meta.get("headshot_url"),
                },
                "position": position.get("position"),
                "gap_to_leader": interval.get("gap_to_leader"),
                "interval": interval.get("interval"),
                "is_in_pit": self._estimate_in_pit(latest_lap=latest_lap, latest_pit=latest_pit),
                "lap": {
                    "lap_number": latest_lap.get("lap_number"),
                    "lap_duration": latest_lap.get("lap_duration"),
                    "last_lap_duration": latest_lap.get("lap_duration"),
                    "best_lap_duration": best_lap.get("lap_duration"),
                    "best_lap_number": best_lap.get("lap_number"),
                    "best_lap_date_start": best_lap.get("date_start"),
                    "sector_1": latest_lap.get("duration_sector_1"),
                    "sector_2": latest_lap.get("duration_sector_2"),
                    "sector_3": latest_lap.get("duration_sector_3"),
                    "i1_speed": latest_lap.get("i1_speed"),
                    "i2_speed": latest_lap.get("i2_speed"),
                    "st_speed": latest_lap.get("st_speed"),
                    "is_personal_best": latest_lap.get("is_personal_best"),
                    "microsectors_1": latest_lap.get("segments_sector_1") or [],
                    "microsectors_1_labels": [
                        microsector_status_label(code)
                        for code in (latest_lap.get("segments_sector_1") or [])
                    ],
                    "microsectors_2": latest_lap.get("segments_sector_2") or [],
                    "microsectors_2_labels": [
                        microsector_status_label(code)
                        for code in (latest_lap.get("segments_sector_2") or [])
                    ],
                    "microsectors_3": latest_lap.get("segments_sector_3") or [],
                    "microsectors_3_labels": [
                        microsector_status_label(code)
                        for code in (latest_lap.get("segments_sector_3") or [])
                    ],
                    "is_pit_out_lap": latest_lap.get("is_pit_out_lap"),
                    "date_start": latest_lap.get("date_start"),
                },
                "tyre": {
                    "compound": active_stint.get("compound"),
                    "stint_number": active_stint.get("stint_number"),
                    "lap_start": active_stint.get("lap_start"),
                    "lap_end": active_stint.get("lap_end"),
                    "tyre_age_at_start": active_stint.get("tyre_age_at_start"),
                    "laps_on_current_tyre": self._calculate_laps_on_tyre(
                        active_stint=active_stint,
                        latest_lap=latest_lap,
                    ),
                },
                "pit": {
                    "last_pit_lap": latest_pit.get("lap_number"),
                    "last_pit_date": latest_pit.get("date"),
                    "lane_duration": latest_pit.get("lane_duration"),
                    "stop_duration": latest_pit.get("stop_duration"),
                },
                "car": {
                    "speed": latest_car.get("speed"),
                    "throttle": latest_car.get("throttle"),
                    "brake": latest_car.get("brake"),
                    "rpm": latest_car.get("rpm"),
                    "n_gear": latest_car.get("n_gear"),
                    "drs": latest_car.get("drs"),
                    "date": latest_car.get("date"),
                },
                "location": {
                    "x": latest_location.get("x"),
                    "y": latest_location.get("y"),
                    "z": latest_location.get("z"),
                    "date": latest_location.get("date"),
                },
                "date": (
                    interval.get("date")
                    or position.get("date")
                    or latest_lap.get("date_start")
                    or latest_car.get("date")
                    or latest_location.get("date")
                ),
            }
            normalized.append(row)

        normalized.sort(
            key=lambda row: (
                self._safe_int(row.get("position"), default=999),
                self._safe_int(row.get("driver_number"), default=999),
            )
        )

        latest_weather = self._latest_row(weather, date_field="date")
        recent_race_control = sorted(
            race_control,
            key=lambda row: self._parse_dt(row.get("date")),
            reverse=True,
        )[:50]
        recent_team_radio = sorted(
            team_radio,
            key=lambda row: self._parse_dt(row.get("date")),
            reverse=True,
        )[:30]
        recent_overtakes = sorted(
            overtakes,
            key=lambda row: self._parse_dt(row.get("date")),
            reverse=True,
        )[:30]

        return {
            "session_key": session_key,
            "rows": normalized,
            "openf1_extras": {
                "weather": latest_weather or None,
                "race_control_messages": recent_race_control,
                "team_radio_messages": recent_team_radio,
                "overtakes": recent_overtakes,
                "counts": {
                    "drivers": len(drivers_by_driver),
                    "positions": len(position_by_driver),
                    "intervals": len(intervals_by_driver),
                    "laps": len(laps_by_driver),
                    "stints": len(stints_by_driver),
                    "pit_events": len(pit_by_driver),
                    "car_data": len(car_by_driver),
                    "locations": len(location_by_driver),
                    "race_control_messages": len(recent_race_control),
                    "team_radio_messages": len(recent_team_radio),
                    "overtakes": len(recent_overtakes),
                },
            },
        }


class FastF1Provider:
    name = "fastf1"

    def __init__(self) -> None:
        disable_fastf1_cache()

    async def fetch_current_session(self) -> Dict[str, Any]:
        year = datetime.now(timezone.utc).year

        try:
            with fastf1_cache_guard():
                schedule = ff1.get_event_schedule(year)
            if schedule is None or schedule.empty:
                raise ProviderError("FastF1 returned an empty event schedule")

            now = datetime.now(timezone.utc)
            schedule = schedule.copy()
            event_dates = schedule["EventDate"]
            if getattr(event_dates.dt, "tz", None) is None:
                schedule["EventDate"] = event_dates.dt.tz_localize("UTC")
            else:
                schedule["EventDate"] = event_dates.dt.tz_convert("UTC")
            past_events = schedule[schedule["EventDate"] <= now]
            latest = (past_events if not past_events.empty else schedule).iloc[-1]

            return {
                "session_key": None,
                "session_name": "offline-fallback",
                "meeting_name": latest.get("EventName"),
                "country_name": latest.get("Country"),
                "date_start": latest.get("EventDate").isoformat() if latest.get("EventDate") is not None else None,
            }
        except Exception as exc:
            raise ProviderError(f"FastF1 session lookup failed: {exc}") from exc

    async def fetch_timing_snapshot(self, session_key: Optional[int] = None) -> Dict[str, Any]:
        return {
            "session_key": session_key,
            "rows": [],
            "mode": "offline",
            "note": "FastF1 fallback does not provide real-time timing snapshots.",
        }
