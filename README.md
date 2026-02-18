# F1 Race Room Backend

Python FastAPI backend for F1 PDF telemetry (legacy-compatible) and live timing, ready for app integration.

## What It Does

- Keeps legacy endpoints used by the existing client:
  - `GET /status`
  - `GET /get-telemetry`
- Exposes live endpoints:
  - `GET /live/session/current`
  - `GET /live/timing/snapshot`
  - `GET /live/timing/stream` (SSE)
  - `POST /live/reload`
- Uses provider architecture with fallback support:
  - `UnofficialF1SignalRProvider` (default for free live testing)
  - `OpenF1Provider` (optional, API key required for live)

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Environment Variables

```env
OPENF1_BASE_URL=https://api.openf1.org/v1
OPENF1_API_KEY=
LIVE_POLL_MS=800
LIVE_HEARTBEAT_SEC=10
ALLOWED_ORIGINS=*
PROVIDER=signalr
PROVIDER_ORDER=signalr
SIGNALR_CONNECTION_URL=wss://livetiming.formula1.com/signalrcore
SIGNALR_NEGOTIATE_URL=https://livetiming.formula1.com/signalrcore/negotiate
SIGNALR_TIMEOUT_SEC=8
SIGNALR_NO_AUTH=true
SIGNALR_ACCESS_TOKEN=
SIGNALR_VERIFY_SSL=true
```

You can start from `.env.example`.

Quick provider switching:

- `PROVIDER=signalr` for free testing without API key
- `PROVIDER=openf1` only if you have an OpenF1 API key
- `PROVIDER_ORDER` defines fallback chain order (left to right)
- If you want no fallback, use `PROVIDER_ORDER=signalr`

## Run Locally

```bash
uvicorn src.server:server --host 0.0.0.0 --port 5050 --env-file .env
```

## Run with Docker

```bash
docker compose up --build
```

## cURL Examples

```bash
curl -s http://localhost:5050/status | jq
curl -s http://localhost:5050/live/session/current | jq
curl -s http://localhost:5050/live/timing/snapshot | jq
curl -N http://localhost:5050/live/timing/stream
curl -s -X POST http://localhost:5050/live/reload | jq
```

Legacy PDF endpoint example:

```bash
curl -v "http://localhost:5050/get-telemetry?year=2024&trackName=Monaco&session=Q&driverName=VER" -o telemetry.pdf
```

## Expected Runtime Behavior

- If live provider is healthy, `/status` returns `online`.
- If provider fails, `/status` becomes `degraded`.
- SSE stream emits:
  - `event: update` only when `version` changes
  - `event: heartbeat` every `LIVE_HEARTBEAT_SEC` when there are no changes
- During inactive sessions, `timing.rows` may be empty.

## Live Driver Data Available

In `timing.rows[]` you can expect (best-effort based on active provider, default SignalR feed):

- `position`
- `gap_to_leader` and `interval`
- `lap.lap_duration`
- `lap.sector_1`, `lap.sector_2`, `lap.sector_3`
- `lap.microsectors_1`, `lap.microsectors_2`, `lap.microsectors_3`
- `lap.microsectors_1_labels`, `lap.microsectors_2_labels`, `lap.microsectors_3_labels`
- `tyre.compound`
- `tyre.laps_on_current_tyre`
- `is_in_pit`
- driver/team metadata (`driver.*`)

## Quick Troubleshooting

- Local SSL error (`CERTIFICATE_VERIFY_FAILED`):
  - set `SIGNALR_VERIFY_SSL=false` in `.env` (local dev only)
- `status=degraded` with `SignalR connected but no timing data received yet`:
  - feed is connected but no useful live payload is available yet
- In production:
  - keep `SIGNALR_VERIFY_SSL=true`

## Technical Documentation

Architecture details, payload notes, and integration flow:

- [`docs/TECHNICAL.md`](docs/TECHNICAL.md)
