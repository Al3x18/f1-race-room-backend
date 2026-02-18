import asyncio
import json

from fastapi.testclient import TestClient

from src.live.aggregator import LiveAggregator
from src.live.sse import SSEBroadcaster
from src.live.settings import AppSettings
from src.server import create_app


class SequenceProvider:
    def __init__(self, session_payload, timing_sequence, name="openf1"):
        self.name = name
        self._session_payload = session_payload
        self._timing_sequence = list(timing_sequence)
        self._index = 0

    async def fetch_current_session(self):
        return dict(self._session_payload)

    async def fetch_timing_snapshot(self, session_key=None):
        if self._index < len(self._timing_sequence):
            payload = self._timing_sequence[self._index]
            self._index += 1
        else:
            payload = self._timing_sequence[-1]

        result = dict(payload)
        if session_key is not None and "session_key" not in result:
            result["session_key"] = session_key
        return result


class FailingProvider:
    def __init__(self, name="openf1"):
        self.name = name

    async def fetch_current_session(self):
        raise RuntimeError("provider unavailable")

    async def fetch_timing_snapshot(self, session_key=None):
        raise RuntimeError("provider unavailable")


def build_settings(heartbeat=1):
    return AppSettings(
        openf1_base_url="https://api.openf1.org/v1",
        openf1_api_key="",
        live_poll_ms=100000,
        live_heartbeat_sec=heartbeat,
        allowed_origins=["*"],
        provider="openf1",
    )


def test_snapshot_non_empty_when_provider_responds():
    primary = SequenceProvider(
        session_payload={"session_key": 1001, "session_name": "Race"},
        timing_sequence=[
            {
                "rows": [
                    {
                        "driver_number": 1,
                        "position": 1,
                        "lap": {
                            "lap_duration": 91.456,
                            "last_lap_duration": 91.456,
                            "best_lap_duration": 90.999,
                        },
                    }
                ]
            }
        ],
    )
    fallback = SequenceProvider(session_payload={}, timing_sequence=[{"rows": []}], name="fastf1")

    app = create_app(settings=build_settings(), primary_provider=primary, fallback_provider=fallback)

    with TestClient(app) as client:
        snapshot = client.get("/live/timing/snapshot")
        assert snapshot.status_code == 200

        body = snapshot.json()
        assert body["provider"] == "openf1"
        assert body["timing"]["rows"]
        lap = body["timing"]["rows"][0]["lap"]
        assert lap["last_lap_duration"] == 91.456
        assert lap["best_lap_duration"] == 90.999


def test_sse_emits_update_on_version_change():
    class FakeRequest:
        async def is_disconnected(self):
            return False

    async def run_case():
        aggregator = LiveAggregator()
        broadcaster = SSEBroadcaster(aggregator=aggregator, heartbeat_sec=10)
        stream = broadcaster.stream(FakeRequest())

        await aggregator.update(
            provider_name="openf1",
            current_session={"session_key": 1002, "session_name": "Race"},
            timing={"rows": [{"driver_number": 1, "position": 1}]},
            status="online",
        )

        pending = asyncio.create_task(anext(stream))

        async def push_next_update():
            await asyncio.sleep(0.01)
            await aggregator.update(
                provider_name="openf1",
                current_session={"session_key": 1002, "session_name": "Race"},
                timing={"rows": [{"driver_number": 1, "position": 1}, {"driver_number": 4, "position": 2}]},
                status="online",
            )

        updater = asyncio.create_task(push_next_update())
        raw_event = await asyncio.wait_for(pending, timeout=2.0)
        await updater
        await stream.aclose()

        lines = [line for line in raw_event.strip().splitlines() if line]
        event_line = next((line for line in lines if line.startswith("event:")), "")
        data_line = next((line for line in lines if line.startswith("data:")), "")
        assert event_line and data_line, f"Invalid SSE payload: {raw_event!r}"

        event_name = event_line.split(":", 1)[1].strip()
        event_data = data_line.split(":", 1)[1].strip()
        payload = json.loads(event_data)

        assert event_name == "update"
        assert payload["version"] > 0
        assert len(payload["timing"]["rows"]) == 2

    asyncio.run(run_case())


def test_status_returns_degraded_when_provider_fails():
    primary = FailingProvider(name="openf1")
    fallback = FailingProvider(name="fastf1")

    app = create_app(settings=build_settings(), primary_provider=primary, fallback_provider=fallback)

    with TestClient(app) as client:
        response = client.get("/status")
        assert response.status_code == 200
        assert response.json()["status"] == "degraded"
