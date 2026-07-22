# F1 Race Room Telemetry Backend

FastAPI service dedicated to generating and caching Formula 1 telemetry PDF
reports with FastF1. The runtime does not start live timing providers, background
polling, SignalR connections, or OpenF1 requests.

## Endpoints

- `GET /` — static telemetry usage page
- `GET /health` — public deployment healthcheck
- `GET /status` — authenticated telemetry service status
- `GET /telemetry/cache/status` — cache usage and configured limits
- `GET /legacy/catalog/years` — seasons available through FastF1
- `GET /legacy/catalog/events?year=2024` — events and sessions for a season
- `GET /legacy/catalog/drivers?...` — drivers with telemetry for a session
- `GET /get-telemetry?...` — single-driver PDF
- `GET /get-telemetry-compare?...` — two-driver comparison PDF

The application routes are protected by the configured API key except for `/`
and `/health`. Static assets under `/static/*` are public.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

Start locally:

```bash
uvicorn src.server:server --host 0.0.0.0 --port 5050 --env-file .env
```

Or use Docker:

```bash
docker compose up --build
```

## Configuration

Copy `.env.example` to `.env`. Available variables:

```env
API_REQUEST_KEY=
API_KEY_HEADER=X-API-Key
ALLOWED_ORIGINS=*

TELEMETRY_CONFIG_FILE=./config/telemetry.toml
TELEMETRY_MAX_CONCURRENCY=2
TELEMETRY_MAX_PLOT_POINTS=1200
TELEMETRY_CACHE_DIR=./telemetry_files_cache
TELEMETRY_CACHE_MAX_DOCS=100
TELEMETRY_CACHE_MAX_MB=500
```

`config/telemetry.toml` contains the same telemetry defaults. Environment
variables override the file, making deployment limits adjustable without
editing the source. Integer values below their supported minimum fall back to the
default: concurrency and cache limits require at least `1`, while plot sampling
requires at least `300` points. `ALLOWED_ORIGINS` accepts a comma-separated list
or `*`.

Docker Compose passes the configurable limits, API settings and CORS settings
from `.env` into the container. It intentionally fixes the container cache path
to the named Volume at `/data/telemetry-pdfs`; the non-container local default
remains `./telemetry_files_cache`.

## API authentication

When `API_REQUEST_KEY` is configured, clients can send either:

```http
X-API-Key: <API_KEY>
```

or:

```http
Authorization: Bearer <API_KEY>
```

`API_KEY_HEADER` changes the first header name. In managed production
environments recognized by the container entrypoint, startup is refused unless
`API_REQUEST_KEY` is a non-placeholder value containing at least 32 characters.

## Catalog flow

Use the catalog before requesting a PDF:

```bash
curl -H "X-API-Key: <API_KEY>" \
  "http://localhost:5050/legacy/catalog/years"

curl -H "X-API-Key: <API_KEY>" \
  "http://localhost:5050/legacy/catalog/events?year=2024"

curl -H "X-API-Key: <API_KEY>" \
  "http://localhost:5050/legacy/catalog/drivers?year=2024&trackName=Monaco&session=Q"
```

Generate a single-driver report:

```bash
curl -H "X-API-Key: <API_KEY>" \
  "http://localhost:5050/get-telemetry?year=2024&trackName=Monaco&session=Q&driverName=VER" \
  -o telemetry.pdf
```

Generate a comparison report:

```bash
curl -H "X-API-Key: <API_KEY>" \
  "http://localhost:5050/get-telemetry-compare?year=2024&trackName=Monaco&session=Q&driverA=VER&driverB=LEC" \
  -o comparison.pdf
```

## Telemetry errors

The two PDF routes return telemetry errors with a stable machine-readable code
and a public English message:

```json
{
  "code": "SESSION_UNAVAILABLE",
  "detail": "The requested session is not available."
}
```

- `400`: required parameters are missing or telemetry data cannot be processed
- `404`: the requested session or driver telemetry is unavailable
- `422`: FastAPI query type validation failed
- `500`: report generation, generated-file, or unexpected internal failure
- `502`: the upstream telemetry provider is unavailable

Version `2.0.0` changes the previous error response contract by adding `code`
and consistently using `detail` instead of the earlier `error` field.

## Persistent PDF cache

PDF names are deterministic. A repeated request for the same parameters is
served directly from disk and does not invoke FastF1.

- Single: `ver_australian_grand_prix_race_2026.pdf`
- Comparison: `ver_vs_lec_australian_grand_prix_race_2026.pdf`
- Maximum documents: `100`
- Maximum total size: `500 MiB`
- Eviction: least recently used first
- Publication: atomic, after a complete PDF has been generated
- Concurrent cache-miss generations: `2`

`TELEMETRY_MAX_CONCURRENCY` applies only to cache misses. Cache hits bypass the
FastF1 generation semaphore and are returned immediately. FastF1 session/cache
setup is process-global and therefore serialized for safety; PDF rendering can
still overlap up to the configured generation limit.

## Container deployment

Build the provided Dockerfile, expose the application through port `5050` or
the injected `PORT`, and mount persistent storage at `/data`. The image defaults
already point the PDF cache to `/data/telemetry-pdfs`.

Minimum production variables:

```env
API_REQUEST_KEY=<LONG_RANDOM_SECRET>
ALLOWED_ORIGINS=*
TELEMETRY_CACHE_DIR=/data/telemetry-pdfs
TELEMETRY_CACHE_MAX_DOCS=100
TELEMETRY_CACHE_MAX_MB=500
TELEMETRY_MAX_CONCURRENCY=2
TELEMETRY_MAX_PLOT_POINTS=1200
```

Use one replica with a locally attached cache volume so per-document locks and
LRU state remain coordinated in one process. The container starts as root only
to prepare the mounted directory, then runs Uvicorn as the unprivileged
`appuser` with one worker.

The service performs no provider warmup and no periodic outbound polling. FastF1
network and CPU work happens only when a catalog or uncached telemetry request
is made.

See [`docs/TECHNICAL.md`](docs/TECHNICAL.md) for implementation details.
See [`CHANGELOG.md`](CHANGELOG.md) for the release history.
