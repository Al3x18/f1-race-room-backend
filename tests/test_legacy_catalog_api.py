from fastapi.testclient import TestClient

from src.live.settings import AppSettings
from src.server import create_app


class FakeLegacyCatalogService:
    def get_years(self):
        return [2023, 2024, 2025, 2026]

    def get_events(self, year: int):
        return [
            {
                "round_number": 8,
                "event_name": "Monaco Grand Prix",
                "official_event_name": "FORMULA 1 GRAND PRIX DE MONACO 2024",
                "country": "Monaco",
                "location": "Monte Carlo",
                "event_format": "conventional",
                "event_date": "2024-05-26T00:00:00+00:00",
                "sessions": [
                    {"name": "Practice 1", "code": "FP1", "date": "2024-05-24T11:30:00+00:00"},
                    {"name": "Qualifying", "code": "Q", "date": "2024-05-25T15:00:00+00:00"},
                    {"name": "Race", "code": "R", "date": "2024-05-26T13:00:00+00:00"},
                ],
            }
        ]

    def get_drivers(self, year: int, track_name: str, session: str):
        return [
            {
                "driver_code": "VER",
                "driver_number": "1",
                "full_name": "Max Verstappen",
                "team_name": "Red Bull Racing",
                "available_telemetry": True,
            },
            {
                "driver_code": "LEC",
                "driver_number": "16",
                "full_name": "Charles Leclerc",
                "team_name": "Ferrari",
                "available_telemetry": True,
            },
        ]


class DummyProvider:
    name = "dummy"

    async def fetch_current_session(self):
        return {"session_key": None, "session_name": "offline"}

    async def fetch_timing_snapshot(self, session_key=None):
        return {"session_key": session_key, "rows": []}


def build_settings():
    return AppSettings(
        openf1_base_url="https://api.openf1.org/v1",
        openf1_api_key="",
        live_poll_ms=100000,
        live_heartbeat_sec=10,
        allowed_origins=["*"],
        provider="signalr",
    )


def test_legacy_catalog_events_returns_event_list():
    app = create_app(
        settings=build_settings(),
        primary_provider=DummyProvider(),
        legacy_catalog_service=FakeLegacyCatalogService(),
    )

    with TestClient(app) as client:
        response = client.get("/legacy/catalog/events?year=2024")
        assert response.status_code == 200
        body = response.json()
        assert body["year"] == 2024
        assert len(body["events"]) == 1
        assert body["events"][0]["event_name"] == "Monaco Grand Prix"
        assert body["events"][0]["sessions"][1]["code"] == "Q"


def test_legacy_catalog_years_returns_year_list():
    app = create_app(
        settings=build_settings(),
        primary_provider=DummyProvider(),
        legacy_catalog_service=FakeLegacyCatalogService(),
    )

    with TestClient(app) as client:
        response = client.get("/legacy/catalog/years")
        assert response.status_code == 200
        body = response.json()
        assert body["years"] == [2023, 2024, 2025, 2026]


def test_legacy_catalog_drivers_returns_driver_list():
    app = create_app(
        settings=build_settings(),
        primary_provider=DummyProvider(),
        legacy_catalog_service=FakeLegacyCatalogService(),
    )

    with TestClient(app) as client:
        response = client.get("/legacy/catalog/drivers?year=2024&trackName=Monaco&session=Q")
        assert response.status_code == 200
        body = response.json()
        assert body["year"] == 2024
        assert body["track_name"] == "Monaco"
        assert body["session"] == "Q"
        assert body["drivers"][0]["driver_code"] == "VER"
        assert body["drivers"][0]["available_telemetry"] is True
