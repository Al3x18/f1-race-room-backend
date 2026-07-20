# F1 Race Room Backend

Python FastAPI backend for F1 PDF telemetry (legacy-compatible) and live timing, ready for app integration.

## What It Does

- Keeps legacy endpoints used by the existing client:
  - `GET /status`
  - `GET /health`
  - `GET /get-telemetry`
  - `GET /get-telemetry-compare`
  - `GET /legacy/catalog/years`
  - `GET /legacy/catalog/events`
  - `GET /legacy/catalog/drivers`
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
pip install -r requirements-dev.txt
```

## Environment Variables

```env
OPENF1_BASE_URL=https://api.openf1.org/v1
OPENF1_API_KEY=
OPENF1_USERNAME=
OPENF1_PASSWORD=
OPENF1_TOKEN_URL=https://api.openf1.org/token
OPENF1_TOKEN_REFRESH_SEC=120
LIVE_POLL_MS=800
LIVE_HEARTBEAT_SEC=10
ALLOWED_ORIGINS=*
TELEMETRY_CONFIG_FILE=./config/telemetry.toml
TELEMETRY_MAX_CONCURRENCY=2
TELEMETRY_MAX_PLOT_POINTS=1200
TELEMETRY_CACHE_DIR=./telemetry_files_cache
TELEMETRY_CACHE_MAX_DOCS=100
TELEMETRY_CACHE_MAX_MB=500
PROVIDER=signalr
PROVIDER_ORDER=signalr
SIGNALR_CONNECTION_URL=wss://livetiming.formula1.com/signalrcore
SIGNALR_NEGOTIATE_URL=https://livetiming.formula1.com/signalrcore/negotiate
SIGNALR_TIMEOUT_SEC=8
SIGNALR_NO_AUTH=true
SIGNALR_ACCESS_TOKEN=
SIGNALR_VERIFY_SSL=true
# If empty, API key is not required.
API_REQUEST_KEY=
# Header used to send API key when API_REQUEST_KEY is set.
API_KEY_HEADER=X-API-Key
```

You can start from `.env.example`.

Quick provider switching:

- `PROVIDER=signalr` for free testing without API key
- `PROVIDER=openf1` with either:
  - `OPENF1_API_KEY` (static bearer token), or
  - `OPENF1_USERNAME` + `OPENF1_PASSWORD` (server auto-fetches token from `OPENF1_TOKEN_URL`)
- `PROVIDER_ORDER` defines fallback chain order (left to right)
- If you want no fallback, use `PROVIDER_ORDER=signalr`
- OpenF1 access token is automatically refreshed before the 1-hour expiry window.
- API key protection (optional):
  - if `API_REQUEST_KEY` is empty, API key authentication is disabled
  - set `API_REQUEST_KEY` to enforce authentication on all endpoints
  - client must send key via header `X-API-Key` (or custom header from `API_KEY_HEADER`)
  - `Authorization: Bearer <key>` is also accepted

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

With API key enabled:

```bash
curl -s -H "X-API-Key: <YOUR_API_KEY>" http://localhost:5050/status | jq
curl -s -H "Authorization: Bearer <YOUR_API_KEY>" http://localhost:5050/live/timing/snapshot | jq
```

Legacy PDF endpoint example:

```bash
curl -v "http://localhost:5050/get-telemetry?year=2024&trackName=Monaco&session=Q&driverName=VER" -o telemetry.pdf
curl -v "http://localhost:5050/get-telemetry-compare?year=2024&trackName=Monaco&session=Q&driverA=VER&driverB=LEC" -o compare.pdf
```

## Telemetry PDF Cache

- Cached PDF files are stored in project root under `./telemetry_files_cache` (configurable via `cache_dir` in `config/telemetry.toml`).
- File naming is deterministic:
  - single driver: `ver_australian_grand_prix_race_2026.pdf`
  - compare: `ver_vs_lec_australian_grand_prix_race_2026.pdf`
- On request:
  - if cached file exists, server returns cache file (no FastF1 generation)
  - if missing, server generates via FastF1 and stores the file in cache
- PDFs are published atomically, so concurrent requests never see a partially-written document.
- Cache keeps at most `cache_max_docs` documents (default `100`) and at most
  `cache_max_mb` MiB (default `500`). It evicts least-recently-used files until
  both limits are satisfied.
- Logs explicitly show cache vs FastF1 path (`cache-hit`, `cache-miss generating-fastf1`).
- `GET /telemetry/cache/status` reports the current document count and byte usage.

## Railway Hobby deployment

The PDF cache must be on a Railway Volume. The normal container filesystem is
ephemeral and is replaced by a deploy.

1. Deploy the repository as one Railway service. `railway.toml` selects the
   Dockerfile and configures the public `/health` endpoint as the healthcheck.
2. Add one Volume to the service and mount it at `/data`.
3. The Docker image already contains these conservative defaults; add service
   variables only if you want to override them:

```env
TELEMETRY_CACHE_DIR=/data/telemetry-pdfs
TELEMETRY_CACHE_MAX_DOCS=100
TELEMETRY_CACHE_MAX_MB=500
TELEMETRY_MAX_CONCURRENCY=2
TELEMETRY_MAX_PLOT_POINTS=1200
```

4. Keep one replica. Railway Volumes cannot be attached to multiple replicas.
   The Docker entrypoint prepares the mounted directory as root and then runs
   Uvicorn as the unprivileged `appuser`, so `RAILWAY_RUN_UID=0` is not needed.
5. In Workspace Usage, configure an email alert below the included credit and
   a Compute hard limit if the service must never exceed the chosen budget.
6. Generate a public domain under Service > Settings > Networking.

Recommended production-only variables:

```env
API_REQUEST_KEY=<LONG_RANDOM_SECRET>
ALLOWED_ORIGINS=https://your-frontend.example
SIGNALR_VERIFY_SSL=true
```

Do not commit the production secret. `/health` remains public for Railway;
other API endpoints require the configured key. On Railway the container refuses
to start if `API_REQUEST_KEY` is missing, still set to the example placeholder,
or shorter than 32 characters. It also refuses `ALLOWED_ORIGINS=*`, an empty
origin list, and the example frontend origin.

For a bulk import, copy `railway.env.example`, replace its two placeholders,
and import that file into Railway Variables. Do not import the local
`.env.example`: its relative cache path is intentionally meant for local runs.

The Hobby plan currently supports a 5 GB persistent Volume, so a 500 MiB PDF
budget fits comfortably. Storage is billed by actual usage; CPU and RAM used by
FastF1/matplotlib are more likely to dominate the bill. Serverless sleeping is
not effective while the live provider keeps making outbound requests.

Legacy catalog endpoints (for dynamic app dropdowns):

```bash
curl -s "http://localhost:5050/legacy/catalog/years" | jq
curl -s "http://localhost:5050/legacy/catalog/events?year=2024" | jq
curl -s "http://localhost:5050/legacy/catalog/drivers?year=2024&trackName=Monaco&session=Q" | jq
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
- `lap.last_lap_duration` (latest completed lap time)
- `lap.best_lap_duration` (driver best lap time in session)
- `lap.sector_1`, `lap.sector_2`, `lap.sector_3`
- `lap.i1_speed`, `lap.i2_speed`, `lap.st_speed`
- `lap.microsectors_1`, `lap.microsectors_2`, `lap.microsectors_3`
- `lap.microsectors_1_labels`, `lap.microsectors_2_labels`, `lap.microsectors_3_labels`
- `tyre.compound`
- `tyre.laps_on_current_tyre`
- `is_in_pit`
- driver/team metadata (`driver.*`)
- `car.*` (speed, throttle, brake, rpm, gear, drs) when available from OpenF1
- `location.*` (x, y, z) when available from OpenF1

When `provider=openf1`, `timing` also includes:

- `openf1_extras.weather` (latest weather sample)
- `openf1_extras.race_control_messages` (recent messages)
- `openf1_extras.team_radio_messages` (recent radio entries)
- `openf1_extras.overtakes` (recent overtake entries)
- `openf1_extras.counts` (quick counters per source)

## Quick Troubleshooting

- Local SSL error (`CERTIFICATE_VERIFY_FAILED`):
  - set `SIGNALR_VERIFY_SSL=false` in `.env` (local dev only)
- `status=degraded` with `SignalR connected but no timing data received yet`:
  - feed is connected but no useful live payload is available yet
- In production:
  - keep `SIGNALR_VERIFY_SSL=true`
- If telemetry PDF requests hit memory limits on small instances:
  - with a 3 GB memory ceiling, `TELEMETRY_MAX_CONCURRENCY=2` allows at most
    two cache-miss generations; use `1` again if Railway reports memory pressure
  - keep `TELEMETRY_MAX_PLOT_POINTS=1200` or lower it to reduce chart memory usage
  - cache settings:
    - `TELEMETRY_CACHE_DIR` (default `./telemetry_files_cache`)
    - `TELEMETRY_CACHE_MAX_DOCS=100` (evicts least recently used PDF by mtime)
    - `TELEMETRY_CACHE_MAX_MB=500` (total PDF cache ceiling in MiB)
  - quick config file:
    - edit `config/telemetry.toml` (`max_concurrency`, `max_plot_points`, `cache_dir`, `cache_max_docs`, `cache_max_mb`)
    - optional override path with `TELEMETRY_CONFIG_FILE`

## Technical Documentation

Architecture details, payload notes, and integration flow:

- [`docs/TECHNICAL.md`](docs/TECHNICAL.md)
