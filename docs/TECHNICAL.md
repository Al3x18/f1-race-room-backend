# Technical Documentation - F1 Live Timing Server

## Overview

This backend exposes two groups of APIs:

- Legacy APIs used by the existing client (`/status`, `/get-telemetry`)
- Live timing APIs for real-time integration (`/live/*`)

Stack:

- FastAPI (ASGI)
- Provider architecture (`UnofficialF1SignalRProvider`, `OpenF1Provider`)
- In-memory async-safe state (`LiveAggregator`) with incremental `version`
- Server-Sent Events (SSE) broadcaster with heartbeat

## Runtime Architecture

### Main components

- `src/server.py`
  - App creation, routing, lifespan startup/shutdown
  - Starts polling service on startup
- `src/live/settings.py`
  - Loads environment configuration
- `src/live/providers.py`
  - `OpenF1Provider`: source from OpenF1 (API key required for live)
- `src/live/signalr_provider.py`
  - `UnofficialF1SignalRProvider`: unofficial live source via SignalR stream
- `src/live/service.py`
  - Polling orchestration and fallback logic
- `src/live/aggregator.py`
  - Canonical in-memory state + version management
- `src/live/sse.py`
  - SSE stream encoder and publisher (`update`, `heartbeat`)

### Data flow

1. `LiveService` polls provider chain every `LIVE_POLL_MS`.
2. It tries providers in `PROVIDER_ORDER` until one returns valid data.
3. New payload is merged into `LiveAggregator`.
4. If payload changed, `version` increments and listeners are notified.
5. `/live/timing/stream` emits:
   - `event: update` only when `version` changes
   - `event: heartbeat` every `LIVE_HEARTBEAT_SEC` when no changes
6. If first provider fails but a fallback works:
   - response provider changes
   - status becomes `degraded`

## Environment Variables

- `OPENF1_BASE_URL` (default `https://api.openf1.org/v1`)
- `OPENF1_API_KEY` (optional)
- `LIVE_POLL_MS` (default `800`)
- `LIVE_HEARTBEAT_SEC` (default `10`)
- `ALLOWED_ORIGINS` (default `*`, comma-separated)
- `PROVIDER` (default `signalr`)
- `PROVIDER_ORDER` (comma-separated chain, example `signalr` or `signalr,openf1`)
- `SIGNALR_CONNECTION_URL` (default `wss://livetiming.formula1.com/signalrcore`)
- `SIGNALR_NEGOTIATE_URL` (default `https://livetiming.formula1.com/signalrcore/negotiate`)
- `SIGNALR_TIMEOUT_SEC` (default `8`)
- `SIGNALR_NO_AUTH` (default `true`)
- `SIGNALR_ACCESS_TOKEN` (optional, for authenticated SignalR usage)
- `SIGNALR_VERIFY_SSL` (default `true`; set `false` only for local SSL troubleshooting)

## API Reference

## `GET /status`

Health snapshot used by legacy clients.

Example response:

```json
{
  "status": "online",
  "provider": "signalr",
  "version": 12
}
```

Possible `status` values:

- `starting`
- `online`
- `degraded`

## `GET /get-telemetry`

Legacy endpoint for PDF telemetry generation.

Query params:

- `year` (int)
- `trackName` (string)
- `session` (string)
- `driverName` (string)

Returns: PDF attachment (`application/pdf`).

## `GET /live/session/current`

Returns session metadata currently cached in memory.

Example response:

```json
{
  "version": 12,
  "provider": "signalr",
  "status": "online",
  "session": {
    "session_key": 11467,
    "session_name": "Day 3",
    "meeting_key": 1304,
    "meeting_name": null,
    "country_name": "Bahrain",
    "date_start": "2026-02-13T07:00:00+00:00",
    "date_end": "2026-02-13T16:00:00+00:00"
  }
}
```

## `GET /live/timing/snapshot`

Full in-memory snapshot.

Example response:

```json
{
  "version": 12,
  "provider": "signalr",
  "status": "online",
  "current_session": {"session_key": 11467},
  "timing": {"session_key": 11467, "rows": []},
  "last_error": null,
  "last_updated": "2026-02-17T21:40:48.028728+00:00"
}
```

Each `timing.rows[]` item contains consolidated per-driver data:

```json
{
  "driver_number": 1,
  "driver": {
    "name_acronym": "VER",
    "broadcast_name": "M VERSTAPPEN",
    "full_name": "Max Verstappen",
    "team_name": "Red Bull Racing",
    "team_colour": "3671C6"
  },
  "position": 1,
  "gap_to_leader": 0,
  "interval": 0,
  "is_in_pit": false,
  "lap": {
    "lap_number": 14,
    "lap_duration": 92.123,
    "sector_1": 30.101,
    "sector_2": 31.222,
    "sector_3": 30.800,
    "microsectors_1": [2048, 2048, 2049],
    "microsectors_1_labels": ["slower", "slower", "improved"],
    "microsectors_2": [2051, 2048, 2048],
    "microsectors_2_labels": ["best_overall", "slower", "slower"],
    "microsectors_3": [2048, 2048, 2050],
    "microsectors_3_labels": ["slower", "slower", "unknown"],
    "is_pit_out_lap": false,
    "date_start": "2026-02-18T12:20:01+00:00"
  },
  "tyre": {
    "compound": "SOFT",
    "stint_number": 2,
    "lap_start": 11,
    "lap_end": null,
    "tyre_age_at_start": 0,
    "laps_on_current_tyre": 4
  },
  "pit": {
    "last_pit_lap": 10,
    "last_pit_date": "2026-02-18T12:18:00+00:00",
    "lane_duration": 18.3,
    "stop_duration": 2.4
  },
  "date": "2026-02-18T12:20:40+00:00"
}
```

Notes:

- `is_in_pit` is heuristic (derived from latest pit/lap updates).
- Some fields can be `null` when upstream source is missing that metric.

## `GET /live/timing/stream` (SSE)

Content type: `text/event-stream`

Events:

- `update`: emitted only on version changes
- `heartbeat`: emitted every heartbeat interval when there are no changes

Example stream:

```text
event: heartbeat
data: {"version":12,"ts":"2026-02-17T21:41:55.731256+00:00"}

event: update
data: {"version":13,"provider":"signalr",...}
```

## `POST /live/reload`

Triggers one immediate poll cycle and returns latest snapshot.

Use case:

- manual refresh from client
- diagnostics during development

## Local Development

## Run with virtualenv

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn src.server:server --host 0.0.0.0 --port 5050 --env-file .env
```

## Run with Docker

```bash
docker compose up --build
```

## Smoke test

```bash
curl -s http://localhost:5050/status | jq
curl -s http://localhost:5050/live/session/current | jq
curl -s http://localhost:5050/live/timing/snapshot | jq
curl -N http://localhost:5050/live/timing/stream
curl -s -X POST http://localhost:5050/live/reload | jq
```

## Flutter Integration Notes

Recommended client strategy:

1. Call `/live/timing/snapshot` on app start to seed UI.
2. Open SSE on `/live/timing/stream`.
3. On `event: update`, parse payload and refresh state.
4. On `heartbeat`, keep connection alive (no UI update required).
5. If connection drops, reconnect with exponential backoff.
6. Optionally call `/live/reload` on resume/foreground.

State handling tip:

- Track last `version` in Flutter state.
- Ignore updates with version `<=` current version.

## Known Behavior

- During inactive sessions, `rows` may be empty and SSE may emit only heartbeats.
- This is expected if upstream provider has no new live updates for the current session.
- In provider failures, `/status` becomes `degraded` and `last_error` is populated.
- With SignalR provider, malformed/truncated frames are skipped using a lenient parser to keep stream continuity.
- If local SSL trust store is incomplete, SignalR can fail handshake unless `SIGNALR_VERIFY_SSL=false` is set for local development.
