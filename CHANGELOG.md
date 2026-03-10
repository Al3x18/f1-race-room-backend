# Changelog

## 1.0.9 - 2026-03-11

- Added optional API key protection for all HTTP endpoints.
- API key can be sent securely via `X-API-Key` (or configured custom header) or `Authorization: Bearer <key>`.
- API key authentication is automatically disabled when `API_REQUEST_KEY` is empty.
- Added explicit unauthorized response handling (`401`) for missing/invalid API keys.
- Refactored app settings location from `src/live/settings.py` to `src/app_settings.py`.
- Reorganized `.env` and `.env.example` with a dedicated **API Security** section at the top.
- Updated README with API key behavior, usage examples, and configuration notes.

## 1.0.8 - 2026-03-10

- Optimized telemetry PDF generation to reduce RAM usage (lighter FastF1 loading + configurable plot downsampling).
- Added concurrency control for telemetry requests (`max_concurrency`, default 2).
- Introduced PDF caching with deterministic filenames (e.g. `ver_australian_grand_prix_race_2026.pdf`).
- Implemented automatic cache eviction with a document limit (`cache_max_docs`, default 20).
- Centralized telemetry runtime configuration in `config/telemetry.toml`.
- Added explicit logs to distinguish cache hits vs FastF1 generation.
- Moved the main cache folder to root as `telemetry_files_cache` and removed unnecessary legacy folders.
