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

- `src/server.py` — FastAPI application setup, state, middleware, and core routes
- `src/api_routes.py` — telemetry and catalog HTTP routes plus cached generation flow
- `src/app_settings.py` — API key and CORS settings
- `src/legacy_catalog.py` — FastF1 event/session/driver discovery
- `src/telemetry/__init__.py` — stable public exports for the telemetry domain
- `src/telemetry/service.py` — FastF1 loading and backwards-compatible facade
- `src/telemetry/processing.py` — pure preparation, sampling, and delta calculation
- `src/telemetry/reports.py` — cohesive Matplotlib rendering for both PDF report types
- `src/telemetry/cache.py` — deterministic names, atomic publication, LRU limits
- `src/telemetry/config.py` — TOML and environment configuration
- `src/fastf1_cache.py` — process-wide FastF1 cache coordination
- `src/send_telemetry_file.py` — PDF file responses
- `docker_entrypoint.py` — persistent-volume preparation and privilege drop

## Detailed code map

This section describes the responsibility, main entry points, delegation, and
side effects of every Python module under `src`.

### Application and HTTP layer

#### `src/__init__.py`

- Marks `src` as the application package and documents its high-level scope.
- Exposes no runtime API and intentionally performs no initialization or I/O.

#### `src/server.py`

- Acts as the application composition root.
- `create_app()` reads application and telemetry settings, creates the
  persistent PDF cache, initializes shared FastAPI state, and installs proxy,
  CORS, and API-key middleware.
- Defines only the core routes `/`, `/health`, and `/status`.
- Imports and registers the telemetry and catalog routers from
  `src/api_routes.py`; their endpoint implementations do not live here.
- Creates the module-level `server` object used by Uvicorn and provides the
  direct `python -m src.server`/script startup path.
- Local startup side effects are limited to reading configuration, preparing
  and enforcing the PDF cache directory, and importing plotting dependencies
  (Matplotlib may initialize local font/cache metadata). It performs no FastF1
  request.

#### `src/api_routes.py`

- Declares `telemetry_router` and the `/legacy/catalog`-prefixed
  `catalog_router`.
- Owns `/get-telemetry`, `/get-telemetry-compare`,
  `/telemetry/cache/status`, and all three catalog endpoints.
- `_serve_cached_pdf()` centralizes cache lookup, per-document locking,
  concurrency limiting, temporary generation, atomic publication, and file
  response creation for both PDF routes.
- `_telemetry_for_request()` constructs the `Telemetry` facade with the runtime
  plot-point limit stored in `request.app.state`.
- Translates domain, missing-file, and unexpected exceptions into sanitized
  `400`, `404`, and `500` responses. Authentication is intentionally delegated
  to the middleware in `src/server.py`.
- FastF1/network work occurs only when a catalog route or uncached PDF route
  invokes its underlying service.

#### `src/app_settings.py`

- Defines the immutable `AppSettings` dataclass for API-key and CORS options.
- `from_env()` reads `API_REQUEST_KEY`, `API_KEY_HEADER`, and
  `ALLOWED_ORIGINS`, normalizing empty headers and comma-separated origins.
- Contains no telemetry limits, filesystem operations, or external calls.

#### `src/send_telemetry_file.py`

- `SendTelemetryFile.send_file_from_path()` validates file existence and
  creates a FastAPI `FileResponse` with `application/pdf` and a download name.
- `delete_file()` provides a defensive deletion helper and returns a status
  string; normal cache lifecycle and eviction are handled by
  `TelemetryPdfCache`, not by this module.

### Catalog and shared FastF1 coordination

#### `src/legacy_catalog.py`

- Normalizes FastF1/pandas values into JSON-safe event, session, and driver
  dictionaries.
- `LegacyCatalogService.get_events()` returns schedule metadata and normalized
  session codes; `get_drivers()` loads a session without telemetry and marks
  which result drivers have lap data.
- `get_years()` probes schedules from 2018 through the current UTC year and
  returns only seasons with data; this result is not TTL-cached.
- Event and driver results use separate, thread-safe in-memory TTL caches
  (default `300` seconds). Driver cache keys normalize year, track, and session.
- All FastF1 calls run inside `fastf1_cache_guard()`.

#### `src/fastf1_cache.py`

- Coordinates FastF1's process-global upstream/download cache with one process
  lock so concurrent session and catalog loads cannot reconfigure it together.
- Routes FastF1 cache data to `/tmp/fastf1-cache` while the guarded operation is
  running, then purges known cache locations and disables FastF1 caching.
- `fastf1_cache_guard()` is the public context manager used by telemetry and
  catalog services. It serializes only FastF1 loading; later PDF rendering can
  still run concurrently.
- This is separate from `src/telemetry/cache.py`, which stores completed PDFs.

### Telemetry domain package

#### `src/telemetry/__init__.py`

- Defines the stable public import surface of the domain.
- Re-exports `Telemetry` and `TelemetryError` from `service.py`, preserving
  `from src.telemetry import Telemetry, TelemetryError` while internal modules
  remain replaceable.

#### `src/telemetry/service.py`

- Contains the `Telemetry` facade consumed by the HTTP layer.
- Stores request identity and plotting limits, creates one
  `TelemetryReportBuilder`, and loads FastF1 sessions through
  `fastf1_cache_guard()`.
- `get_fl_telemetry()` selects a driver's fastest lap and requests a
  single-driver report; `get_comparison_telemetry_pdf()` selects both fastest
  laps and requests a comparison report.
- `build_fastest_lap_plot()` and `build_comparison_plot()` preserve the previous
  facade methods while delegating rendering and wrapping failures in
  `TelemetryError`.
- Always closes Matplotlib figures and triggers garbage collection after a
  top-level report request.
- Compatibility aliases retain access to former private helper names while the
  implementations live in `processing.py` and `reports.py`.

#### `src/telemetry/processing.py`

- Contains side-effect-free numerical and formatting functions.
- `prepare_telemetry()` guarantees a distance axis; the two downsampling
  functions reduce plotting rows while keeping a delta array aligned.
- `format_lap_time()` and `format_metric()` provide defensive report labels.
- `calculate_delta()` replaces deprecated `FastF1.utils.delta_time`: it removes
  invalid/backtracking samples, normalizes the compared integrated lap distance,
  interpolates comparison time on the reference distance axis, and preserves
  the previous sign semantics.
- The continuous delta remains an approximation. Real Belgian GP 2026 checks
  produced an exact finish gap but intermediate sector deviations up to about
  `0.15 s`; the function returns `None` delta on unusable input rather than
  preventing the rest of the report.
- Performs no HTTP, FastF1 session loading, filesystem writing, or plotting.

#### `src/telemetry/reports.py`

- Configures Matplotlib's non-interactive `Agg` backend and contains
  `TelemetryReportBuilder`.
- Shares plot styling, KPI cards, corner lookup, secondary corner axes, speed
  annotations, output-path preparation, and sampling logic between report
  types.
- `build_fastest_lap_plot()` renders speed, throttle, brake, lap/sector timing,
  tyre metadata, and summary metrics for one driver.
- `build_comparison_plot()` renders speed, continuous delta, throttle, brake,
  and summary cards for two drivers.
- Writes a PDF to the explicit staging path supplied by the cache, or to
  `./telemetry_files` when invoked directly, and closes each figure in a
  `finally` block.
- Does not load FastF1 sessions or manage the persistent PDF cache.

#### `src/telemetry/cache.py`

- Defines `TelemetryPdfCache`, the persistent completed-report cache, and
  `TelemetryCacheError`.
- Produces sanitized deterministic filenames for single and comparison reports.
- Validates cache paths and the `%PDF-` header, removes invalid files and
  orphaned `.part` files, and touches hits for LRU ordering.
- Creates generation paths under the system temporary staging directory, then
  publishes completed files atomically through a uniquely named `.part` file.
- Enforces both maximum document count and maximum total bytes by evicting the
  oldest files; `stats()` supplies `/telemetry/cache/status`.
- Uses an in-process reentrant lock for filesystem consistency. Per-request
  async coordination remains in `src/api_routes.py`.

#### `src/telemetry/config.py`

- Defines immutable `TelemetryRuntimeConfig` values for generation concurrency,
  plot sampling, cache directory, document limit, and byte limit in MiB.
- `load()` reads TOML from `TELEMETRY_CONFIG_FILE` (default
  `./config/telemetry.toml`) and applies environment-variable overrides.
- Parsing helpers reject empty/invalid values and enforce documented minimums,
  falling back to safe defaults instead of aborting startup.
- Performs local configuration-file reads only; it does not initialize FastF1
  or the PDF cache itself.

## Startup sequence

1. Read `AppSettings` from the environment.
2. Load `TelemetryRuntimeConfig` from TOML and environment overrides.
3. Create the PDF cache directory and enforce document/size limits.
4. Register HTTP middleware and telemetry/catalog routes.
5. Start one Uvicorn worker on the configured `PORT`.

Telemetry requests flow through a deliberately small number of layers:

1. `api_routes` validates HTTP input and coordinates the persistent PDF cache.
2. `Telemetry` loads the requested FastF1 session and selects the relevant laps.
3. `telemetry.processing` performs reusable, side-effect-free transformations.
4. `TelemetryReportBuilder` renders the final single or comparison PDF.

The two report types remain together because they share styling and plotting
primitives. Smaller configuration, cache, and catalog modules remain separate
only where they already represent distinct responsibilities.

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
