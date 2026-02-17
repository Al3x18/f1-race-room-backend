from __future__ import annotations

import asyncio
import json
import struct
import threading
import time
import ssl
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .providers import ProviderError, microsector_status_label


class UnofficialF1SignalRProvider:
    """Unofficial provider based on F1 SignalR Core live feed.

    This provider runs an internal SignalR client and maintains a merged
    in-memory state from incremental stream updates.
    """

    name = "signalr"

    _default_topics = [
        "Heartbeat",
        "DriverList",
        "SessionInfo",
        "SessionStatus",
        "TrackStatus",
        "TimingData",
        "TimingAppData",
        "TimingStats",
        "RaceControlMessages",
        "LapCount",
        "SessionData",
        "TopThree",
        "Position.z",
    ]

    def __init__(
        self,
        connection_url: str,
        negotiate_url: str,
        timeout_sec: int = 8,
        no_auth: bool = True,
        access_token: str = "",
        verify_ssl: bool = True,
        topics: Optional[List[str]] = None,
    ) -> None:
        self._connection_url = connection_url
        self._negotiate_url = negotiate_url
        self._timeout_sec = max(3, timeout_sec)
        self._no_auth = no_auth
        self._access_token = access_token
        self._verify_ssl = verify_ssl
        self._topics = topics[:] if topics else self._default_topics[:]

        self._state_lock = threading.RLock()
        self._connected_event = threading.Event()
        self._started = False

        self._connection = None
        self._last_message_monotonic = 0.0
        self._last_event_iso: Optional[str] = None

        self._session_info: Dict[str, Any] = {}
        self._session_data: Dict[str, Any] = {}
        self._driver_list: Dict[str, Dict[str, Any]] = {}
        self._timing_lines: Dict[str, Dict[str, Any]] = {}
        self._timing_app_lines: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def _utc_now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _to_int(value: Any, default: int = -1) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _deep_merge(target: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
        for key, value in patch.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                UnofficialF1SignalRProvider._deep_merge(target[key], value)
            else:
                target[key] = value
        return target

    @staticmethod
    def _decode_jsonish(value: Any) -> Any:
        if isinstance(value, (dict, list)):
            return value
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="ignore")
        if not isinstance(value, str):
            return value

        raw = value.strip()
        if not raw:
            return {}

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            fixed = (
                raw.replace("'", '"')
                .replace("True", "true")
                .replace("False", "false")
                .replace("None", "null")
            )
            try:
                return json.loads(fixed)
            except json.JSONDecodeError:
                return raw

    def _extract_updates(self, msg: Any) -> List[Tuple[str, Any, str]]:
        updates: List[Tuple[str, Any, str]] = []

        if hasattr(msg, "result") and isinstance(getattr(msg, "result", None), dict):
            for topic, payload in msg.result.items():
                updates.append((str(topic), payload, ""))
            return updates

        if isinstance(msg, list):
            if len(msg) >= 2 and isinstance(msg[0], str):
                updates.append((msg[0], msg[1], msg[2] if len(msg) > 2 else ""))
                return updates

            for item in msg:
                if isinstance(item, list) and len(item) >= 2 and isinstance(item[0], str):
                    updates.append((item[0], item[1], item[2] if len(item) > 2 else ""))
            return updates

        if isinstance(msg, dict) and isinstance(msg.get("M"), list):
            for inner in msg["M"]:
                args = inner.get("A") if isinstance(inner, dict) else None
                if isinstance(args, list) and len(args) >= 2 and isinstance(args[0], str):
                    updates.append((args[0], args[1], args[2] if len(args) > 2 else ""))

        return updates

    def _message_has_data(self) -> bool:
        return bool(self._timing_lines or self._driver_list or self._session_info)

    def _apply_update(self, topic: str, payload: Any) -> None:
        decoded = self._decode_jsonish(payload)

        if topic == "SessionInfo" and isinstance(decoded, dict):
            self._deep_merge(self._session_info, decoded)
            return

        if topic == "SessionData" and isinstance(decoded, dict):
            self._deep_merge(self._session_data, decoded)
            return

        if topic == "DriverList" and isinstance(decoded, dict):
            for driver_number, driver_data in decoded.items():
                if not isinstance(driver_data, dict):
                    continue
                key = str(driver_number)
                current = self._driver_list.get(key, {})
                self._driver_list[key] = self._deep_merge(current, driver_data)
            return

        if topic == "TimingData" and isinstance(decoded, dict):
            lines = decoded.get("Lines") if isinstance(decoded.get("Lines"), dict) else {}
            for driver_number, line_data in lines.items():
                if not isinstance(line_data, dict):
                    continue
                key = str(driver_number)
                current = self._timing_lines.get(key, {})
                self._timing_lines[key] = self._deep_merge(current, line_data)
            return

        if topic == "TimingAppData" and isinstance(decoded, dict):
            lines = decoded.get("Lines") if isinstance(decoded.get("Lines"), dict) else {}
            for driver_number, line_data in lines.items():
                if not isinstance(line_data, dict):
                    continue
                key = str(driver_number)
                current = self._timing_app_lines.get(key, {})
                self._timing_app_lines[key] = self._deep_merge(current, line_data)
            return

    def _on_feed(self, msg: Any) -> None:
        updates = self._extract_updates(msg)
        if not updates:
            return

        with self._state_lock:
            for topic, payload, _ in updates:
                self._apply_update(topic=topic, payload=payload)
            self._last_message_monotonic = time.monotonic()
            self._last_event_iso = self._utc_now_iso()

    def _on_open(self) -> None:
        self._connected_event.set()
        try:
            if self._connection is not None:
                self._connection.send("Subscribe", [self._topics], on_invocation=self._on_feed)
        except Exception:
            # The polling loop will surface this via missing updates.
            pass

    def _on_close(self) -> None:
        self._connected_event.clear()

    def _build_signalr_connection(self):
        try:
            from signalrcore.hub_connection_builder import HubConnectionBuilder
            from signalrcore.protocol.json_hub_protocol import JsonHubProtocol
            from signalrcore.transport.websockets.websocket_client import WebSocketClient
            from signalrcore.transport.sockets.errors import NoHeaderException, SocketClosedError
            from signalrcore.types import DEFAULT_ENCODING
        except Exception as exc:
            raise ProviderError(
                "signalrcore is not available. Install dependencies to use provider=signalr"
            ) from exc

        def _patch_websocket_client() -> None:
            if getattr(WebSocketClient, "_f1_lenient_patch", False):
                return

            def _recv_exact(sock, n: int) -> bytes:
                data = bytearray()
                while len(data) < n:
                    chunk = sock.recv(n - len(data))
                    if not chunk:
                        break
                    data.extend(chunk)
                return bytes(data)

            def _prepare_data(self, data):
                if self.is_binary:
                    return data
                try:
                    return data.decode(DEFAULT_ENCODING)
                except UnicodeDecodeError:
                    # Feed sometimes contains truncated/invalid utf-8 chunks.
                    return data.decode(DEFAULT_ENCODING, errors="ignore")

            def _recv_frame(self):
                try:
                    header = _recv_exact(self.sock, 2)
                except ssl.SSLError as ex:
                    self.logger.error(ex)
                    header = None

                if header is None or len(header) < 2:
                    raise NoHeaderException()

                fin_opcode = header[0]
                masked_len = header[1]

                if fin_opcode == 8:
                    raise SocketClosedError(header)

                payload_len = masked_len & 0x7F
                if payload_len == 126:
                    extended = _recv_exact(self.sock, 2)
                    if len(extended) < 2:
                        raise NoHeaderException()
                    payload_len = struct.unpack(">H", extended)[0]
                elif payload_len == 127:
                    extended = _recv_exact(self.sock, 8)
                    if len(extended) < 8:
                        raise NoHeaderException()
                    payload_len = struct.unpack(">Q", extended)[0]

                if masked_len & 0x80:
                    masking_key = _recv_exact(self.sock, 4)
                    masked_data = _recv_exact(self.sock, payload_len)
                    if len(masking_key) < 4 or len(masked_data) < payload_len:
                        raise NoHeaderException()
                    data = bytes(
                        b ^ masking_key[i % 4]
                        for i, b in enumerate(masked_data)
                    )
                else:
                    data = _recv_exact(self.sock, payload_len)
                    if len(data) < payload_len:
                        raise NoHeaderException()

                if self.is_trace_enabled():
                    self.logger.debug(f"[TRACE] - {data}")

                return self.prepare_data(data)

            WebSocketClient.prepare_data = _prepare_data
            WebSocketClient._recv_frame = _recv_frame
            WebSocketClient._f1_lenient_patch = True

        _patch_websocket_client()

        class _LenientJsonHubProtocol(JsonHubProtocol):
            """JSON protocol that drops malformed frames instead of raising."""

            @staticmethod
            def _parse_json_safe(raw_message: str) -> Optional[Dict[str, Any]]:
                try:
                    parsed = json.loads(raw_message)
                    return parsed if isinstance(parsed, dict) else None
                except json.JSONDecodeError:
                    fixed = (
                        raw_message.replace("'", '"')
                        .replace("True", "true")
                        .replace("False", "false")
                        .replace("None", "null")
                    )
                    try:
                        parsed = json.loads(fixed)
                        return parsed if isinstance(parsed, dict) else None
                    except json.JSONDecodeError:
                        return None

            def parse_messages(self, raw: str):
                raw_messages = [
                    record.replace(self.record_separator, "")
                    for record in raw.split(self.record_separator)
                    if record is not None and record != "" and record != self.record_separator
                ]

                result = []
                for raw_message in raw_messages:
                    dict_message = self._parse_json_safe(raw_message)
                    if not dict_message:
                        continue
                    if len(dict_message.keys()) > 0:
                        parsed_message = self.get_message(dict_message)
                        if parsed_message is not None:
                            result.append(parsed_message)
                return result

        headers: Dict[str, str] = {}
        try:
            with httpx.Client(
                timeout=self._timeout_sec,
                follow_redirects=True,
                verify=self._verify_ssl,
            ) as client:
                response = client.options(self._negotiate_url)
                cookie = response.cookies.get("AWSALBCORS")
                if cookie:
                    headers["Cookie"] = f"AWSALBCORS={cookie}"
        except Exception:
            # Pre-negotiation is best-effort.
            pass

        options: Dict[str, Any] = {
            "verify_ssl": self._verify_ssl,
            "headers": headers,
        }
        if not self._no_auth and self._access_token:
            token = self._access_token
            options["access_token_factory"] = lambda: token

        connection = (
            HubConnectionBuilder()
            .with_url(self._connection_url, options=options)
            .with_hub_protocol(_LenientJsonHubProtocol())
            .build()
        )
        connection.on_open(self._on_open)
        connection.on_close(self._on_close)
        connection.on("feed", self._on_feed)
        return connection

    def _ensure_started(self) -> None:
        with self._state_lock:
            if self._started:
                return
            self._started = True

        self._connection = self._build_signalr_connection()
        try:
            self._connection.start()
        except Exception as exc:
            with self._state_lock:
                self._started = False
            raise ProviderError(f"SignalR start failed: {exc}") from exc

        if not self._connected_event.wait(timeout=self._timeout_sec):
            raise ProviderError("SignalR connection timeout")

    async def _ensure_ready(self) -> None:
        await asyncio.to_thread(self._ensure_started)

        deadline = time.monotonic() + self._timeout_sec
        while time.monotonic() < deadline:
            with self._state_lock:
                if self._message_has_data():
                    return
            await asyncio.sleep(0.1)

        raise ProviderError("SignalR connected but no timing data received yet")

    @staticmethod
    def _pick_sector(line: Dict[str, Any], index: int) -> Tuple[Optional[Any], List[Any]]:
        sectors = line.get("Sectors") if isinstance(line.get("Sectors"), dict) else {}
        key = str(index)
        sector = sectors.get(key, sectors.get(index, {}))
        if not isinstance(sector, dict):
            return None, []

        segments = sector.get("Segments") if isinstance(sector.get("Segments"), dict) else {}
        ordered_keys = sorted(segments.keys(), key=lambda item: UnofficialF1SignalRProvider._to_int(item, 999))
        micro = []
        for segment_key in ordered_keys:
            segment = segments.get(segment_key)
            if isinstance(segment, dict):
                micro.append(segment.get("Status"))

        return sector.get("Value"), micro

    @staticmethod
    def _stints_as_list(line: Dict[str, Any]) -> List[Dict[str, Any]]:
        stints = line.get("Stints")
        if isinstance(stints, list):
            return [item for item in stints if isinstance(item, dict)]
        if isinstance(stints, dict):
            ordered = sorted(stints.keys(), key=lambda key: UnofficialF1SignalRProvider._to_int(key, 999))
            return [stints[key] for key in ordered if isinstance(stints.get(key), dict)]
        return []

    def _build_session_payload(self) -> Dict[str, Any]:
        session_info = self._session_info
        meeting = session_info.get("Meeting") if isinstance(session_info.get("Meeting"), dict) else {}
        country = meeting.get("Country") if isinstance(meeting.get("Country"), dict) else {}

        return {
            "session_key": session_info.get("Key") or session_info.get("SessionKey"),
            "session_name": session_info.get("Name") or session_info.get("Type"),
            "meeting_key": meeting.get("Key"),
            "meeting_name": meeting.get("Name") or meeting.get("OfficialName"),
            "country_name": country.get("Name") or country.get("Code"),
            "date_start": session_info.get("StartDate"),
            "date_end": session_info.get("EndDate"),
        }

    def _build_rows_payload(self) -> List[Dict[str, Any]]:
        driver_ids = (
            set(self._driver_list.keys())
            | set(self._timing_lines.keys())
            | set(self._timing_app_lines.keys())
        )

        rows: List[Dict[str, Any]] = []
        for driver_id in driver_ids:
            timing_line = self._timing_lines.get(driver_id, {})
            app_line = self._timing_app_lines.get(driver_id, {})
            driver_line = self._driver_list.get(driver_id, {})
            if not isinstance(timing_line, dict):
                timing_line = {}
            if not isinstance(app_line, dict):
                app_line = {}
            if not isinstance(driver_line, dict):
                driver_line = {}

            sector_1, micro_1 = self._pick_sector(timing_line, 0)
            sector_2, micro_2 = self._pick_sector(timing_line, 1)
            sector_3, micro_3 = self._pick_sector(timing_line, 2)

            interval_ahead = timing_line.get("IntervalToPositionAhead")
            if isinstance(interval_ahead, dict):
                interval_value = interval_ahead.get("Value")
            else:
                interval_value = interval_ahead

            stints = self._stints_as_list(app_line)
            current_stint = stints[-1] if stints else {}

            rows.append(
                {
                    "driver_number": self._to_int(driver_id, 0) or driver_id,
                    "driver": {
                        "name_acronym": driver_line.get("Tla") or driver_line.get("RacingNumber"),
                        "broadcast_name": driver_line.get("BroadcastName"),
                        "full_name": driver_line.get("FullName"),
                        "team_name": driver_line.get("TeamName"),
                        "team_colour": driver_line.get("TeamColour"),
                    },
                    "position": timing_line.get("Position"),
                    "gap_to_leader": timing_line.get("GapToLeader"),
                    "interval": interval_value,
                    "is_in_pit": bool(timing_line.get("InPit")),
                    "lap": {
                        "lap_number": timing_line.get("NumberOfLaps"),
                        "lap_duration": (
                            timing_line.get("LastLapTime", {}).get("Value")
                            if isinstance(timing_line.get("LastLapTime"), dict)
                            else None
                        ),
                        "sector_1": sector_1,
                        "sector_2": sector_2,
                        "sector_3": sector_3,
                        "microsectors_1": micro_1,
                        "microsectors_1_labels": [microsector_status_label(code) for code in micro_1],
                        "microsectors_2": micro_2,
                        "microsectors_2_labels": [microsector_status_label(code) for code in micro_2],
                        "microsectors_3": micro_3,
                        "microsectors_3_labels": [microsector_status_label(code) for code in micro_3],
                        "is_pit_out_lap": timing_line.get("PitOut"),
                        "date_start": (
                            timing_line.get("LastLapTime", {}).get("Utc")
                            if isinstance(timing_line.get("LastLapTime"), dict)
                            else None
                        ),
                    },
                    "tyre": {
                        "compound": current_stint.get("Compound"),
                        "stint_number": len(stints) if stints else None,
                        "lap_start": current_stint.get("StartLaps"),
                        "lap_end": current_stint.get("EndLaps"),
                        "tyre_age_at_start": current_stint.get("StartLaps"),
                        "laps_on_current_tyre": current_stint.get("TotalLaps"),
                    },
                    "pit": {
                        "last_pit_lap": None,
                        "last_pit_date": None,
                        "lane_duration": None,
                        "stop_duration": None,
                    },
                    "date": self._last_event_iso,
                }
            )

        rows.sort(key=lambda row: (self._to_int(row.get("position"), 999), self._to_int(row.get("driver_number"), 999)))
        return rows

    async def fetch_current_session(self) -> Dict[str, Any]:
        await self._ensure_ready()
        with self._state_lock:
            session = self._build_session_payload()
            if not any(session.values()):
                raise ProviderError("SignalR session metadata not available yet")
            return session

    async def fetch_timing_snapshot(self, session_key: Optional[int] = None) -> Dict[str, Any]:
        await self._ensure_ready()
        with self._state_lock:
            rows = self._build_rows_payload()
            if not rows:
                raise ProviderError("SignalR timing rows are empty")

            session = self._build_session_payload()
            effective_session_key = session_key if session_key is not None else session.get("session_key")
            return {
                "session_key": effective_session_key,
                "rows": rows,
                "mode": "unofficial-signalr",
                "last_event": self._last_event_iso,
            }
