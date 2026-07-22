# Technical Documentation

## Runtime scope

The application is a telemetry-only FastAPI service. Startup performs local
configuration and cache initialization only. There are no background tasks,
provider warmups, SignalR connections, OpenF1 authentication calls, periodic
polling loops, or SSE streams.

FastF1 is invoked only by:

- catalog requests under `/legacy/catalog/*`
- uncached requests to `/get-telemetry`
- uncached requests to `/get-telemetry-compare`

## Components

- `src/server.py` — FastAPI routes, authentication, concurrency coordination
- `src/app_settings.py` — API key and CORS settings
- `src/legacy_catalog.py` — FastF1 event/session/driver discovery
- `src/telemetry.py` — telemetry loading and PDF chart generation
- `src/telemetry_cache.py` — deterministic names, atomic publication, LRU limits
- `src/telemetry_runtime_config.py` — TOML and environment configuration
- `src/fastf1_cache.py` — process-wide FastF1 cache coordination
- `src/send_telemetry_file.py` — PDF file responses
- `docker_entrypoint.py` — persistent-volume preparation and privilege drop

## Startup sequence

1. Read `AppSettings` from the environment.
2. Load `TelemetryRuntimeConfig` from TOML and environment overrides.
3. Create the PDF cache directory and enforce document/size limits.
4. Register HTTP middleware and telemetry/catalog routes.
5. Start one Uvicorn worker on the configured `PORT`.

No external HTTP or WebSocket connection occurs during startup or while the
service is idle.

## Public routes

### `GET /`

Renders a static telemetry usage page. It contains no JavaScript and performs no
API calls.

### `GET /health`

Returns:

```json
{"status": "ok"}
```

This endpoint is intentionally public for deployment healthchecks.

## Protected service routes

### `GET /status`

Returns local service information only:

```json
{
  "status": "ok",
  "service": "telemetry",
  "version": "1.2.0"
}
```

### `GET /telemetry/cache/status`

Example:

```json
{
  "documents": 24,
  "bytes": 128450304,
  "max_documents": 100,
  "max_bytes": 524288000
}
```

## Catalog routes

### `GET /legacy/catalog/years`

Returns seasons supported by the FastF1 schedule source.

### `GET /legacy/catalog/events?year=2024`

Returns events with round, location, date and available session codes.

### `GET /legacy/catalog/drivers`

Required query parameters:

- `year`
- `trackName`
- `session`

Returns driver code, number, name, team and telemetry availability.

Event and driver results are kept in an in-memory cache for `300` seconds to
avoid repeating FastF1 work during normal client selection flows. The year list
is computed from the available schedules on each `/legacy/catalog/years`
request and is not stored in that TTL cache.

## PDF routes

### `GET /get-telemetry`

Required query parameters:

- `year`
- `trackName`
- `session`
- `driverName`

### `GET /get-telemetry-compare`

Required query parameters:

- `year`
- `trackName`
- `session`
- `driverA`
- `driverB`

Both routes return `application/pdf` with an attachment filename.

## Cache and concurrency flow

1. Normalize request parameters into a deterministic filename.
2. Check the persistent PDF cache before acquiring a generation slot.
3. On a hit, touch the file for LRU ordering and return it immediately.
4. On a miss, acquire a per-document lock.
5. Check the cache again in case another request completed the same PDF.
6. Acquire the global telemetry semaphore only when generation is still needed.
7. Generate into a temporary staging path.
8. Verify the PDF header, reserve cache space and publish atomically.
9. Evict least-recently-used files until both configured limits are satisfied.

Consequences:

- cache hits do not consume FastF1 generation concurrency
- duplicate concurrent requests generate one PDF
- clients never receive partially generated files
- the cache respects both count and byte limits

The semaphore limits complete cache-miss generation tasks. FastF1 cache/session
setup is additionally protected by a process-wide lock because FastF1 cache
configuration is global. Session loads are therefore serialized, while plot
rendering can overlap up to `TELEMETRY_MAX_CONCURRENCY`.

## Configuration precedence

Defaults are defined in `config/telemetry.toml`. If
`TELEMETRY_CONFIG_FILE` points to another file, it is used instead. Environment
variables override values loaded from the file.

| Variable | Default | Valid input |
| --- | --- | --- |
| `API_REQUEST_KEY` | empty | Any string; a non-empty value enables authentication |
| `API_KEY_HEADER` | `X-API-Key` | Non-empty header name |
| `ALLOWED_ORIGINS` | `*` | `*` or comma-separated origins |
| `TELEMETRY_CONFIG_FILE` | `./config/telemetry.toml` | File path |
| `TELEMETRY_MAX_CONCURRENCY` | `2` | Integer `>= 1` |
| `TELEMETRY_MAX_PLOT_POINTS` | `1200` | Integer `>= 300` |
| `TELEMETRY_CACHE_DIR` | `./telemetry_files_cache` | Directory path |
| `TELEMETRY_CACHE_MAX_DOCS` | `100` | Integer `>= 1` |
| `TELEMETRY_CACHE_MAX_MB` | `500` | Integer `>= 1` |

Invalid integer values fall back to their defaults instead of preventing
startup. Docker Compose interpolates API, CORS and integer settings from the
local `.env` file. It fixes `TELEMETRY_CACHE_DIR` to
`/data/telemetry-pdfs` so the named Volume is always used.

## Authentication

When `API_REQUEST_KEY` is non-empty, protected routes accept either the header
configured by `API_KEY_HEADER` or `Authorization: Bearer <key>`. Key comparison
uses `secrets.compare_digest`.

Unauthorized requests receive `401` without exposing the expected key. Internal
exceptions are logged server-side and sanitized before being returned.

Missing application query parameters return `400`. A query parameter with an
invalid FastAPI type, such as a non-integer `year`, returns `422`. Telemetry data
that cannot be loaded returns `400`; an unexpected generation error returns
`500`. A generated file that disappears before it can be sent returns `404`.

## Container deployment

- Builder: Dockerfile
- Healthcheck: `/health`
- Worker count: `1`
- Persistent volume mount: `/data`
- PDF directory: `/data/telemetry-pdfs`
- Runtime user: `appuser` after volume ownership is prepared

The entrypoint prepares ownership of the mounted cache directory and then drops
privileges before starting Uvicorn. Keep one replica with a locally attached
cache volume so in-process per-document locks and LRU state remain coordinated.
The application itself enforces the `500 MiB` and `100` document defaults.

Only user-triggered catalog queries and cache misses create upstream FastF1
traffic. An idle deployment should produce no recurring provider errors or
outbound requests.
