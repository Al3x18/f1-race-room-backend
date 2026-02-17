# F1 Race Room Backend

Backend Python con FastAPI per telemetry PDF (retrocompatibile) e live timing F1 pronto per integrazione Flutter.

## Cosa fa

- Mantiene endpoint legacy già usati dal client:
  - `GET /status`
  - `GET /get-telemetry`
- Espone endpoint live:
  - `GET /live/session/current`
  - `GET /live/timing/snapshot`
  - `GET /live/timing/stream` (SSE)
  - `POST /live/reload`
- Usa provider architecture con fallback automatico:
  - `UnofficialF1SignalRProvider` (primario consigliato per test senza API key)
  - `OpenF1Provider` (opzionale, solo con API key)

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Variabili ambiente

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

Puoi partire da `.env.example`.

Switch rapido provider:

- `PROVIDER=signalr` per test senza API key
- `PROVIDER=openf1` solo se hai API key
- `PROVIDER_ORDER` definisce la chain di fallback (ordine sinistra -> destra)
- Se non vuoi fallback, usa `PROVIDER_ORDER=signalr`

## Run locale

```bash
uvicorn src.server:server --host 0.0.0.0 --port 5050 --env-file .env
```

## Run con Docker

```bash
docker compose up --build
```

## Esempi curl

```bash
curl -s http://localhost:5050/status | jq
curl -s http://localhost:5050/live/session/current | jq
curl -s http://localhost:5050/live/timing/snapshot | jq
curl -N http://localhost:5050/live/timing/stream
curl -s -X POST http://localhost:5050/live/reload | jq
```

Endpoint legacy PDF:

```bash
curl -v "http://localhost:5050/get-telemetry?year=2024&trackName=Monaco&session=Q&driverName=VER" -o telemetry.pdf
```

## Stato e comportamento atteso

- Se il provider live è raggiungibile, `/status` ritorna `online`.
- Se il provider fallisce, `/status` passa a `degraded`.
- Lo stream SSE invia:
  - `event: update` solo quando cambia `version`
  - `event: heartbeat` ogni `LIVE_HEARTBEAT_SEC` se non ci sono cambi
- In sessioni non attive `timing.rows` può essere vuoto: è normale.

## Dati live disponibili per pilota

Nel payload `timing.rows[]` trovi (best-effort in base al provider attivo, default SignalR feed):

- `position`
- `gap_to_leader` e `interval`
- `lap.lap_duration`
- `lap.sector_1`, `lap.sector_2`, `lap.sector_3`
- `lap.microsectors_1`, `lap.microsectors_2`, `lap.microsectors_3`
- `lap.microsectors_1_labels`, `lap.microsectors_2_labels`, `lap.microsectors_3_labels`
- `tyre.compound`
- `tyre.laps_on_current_tyre`
- `is_in_pit`
- metadati pilota/team (`driver.*`)

## Troubleshooting rapido

- Errore SSL (`CERTIFICATE_VERIFY_FAILED`) in locale:
  - imposta `SIGNALR_VERIFY_SSL=false` in `.env` (solo sviluppo locale)
- `status=degraded` con `SignalR connected but no timing data received yet`:
  - feed agganciato ma nessun dato utile ancora disponibile per la sessione
- In produzione:
  - mantieni `SIGNALR_VERIFY_SSL=true`

## Documentazione tecnica

Dettagli architetturali, payload e flusso integrazione Flutter:

- [`docs/TECHNICAL.md`](docs/TECHNICAL.md)
