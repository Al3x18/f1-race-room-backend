# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.2.0] - 2026-07-22

### Changed

- Converted the application to a telemetry-only service.
- Changed `/status` to report local telemetry service state only.
- Simplified application settings to API-key and CORS configuration.
- Corrected the static usage page and telemetry documentation to match the
  implemented report fields, session codes, and generation limits.
- Updated Docker Compose environment interpolation while keeping the PDF cache
  on persistent storage.
- Updated catalog and API tests for the telemetry-only route set.

### Removed

- Removed the SignalR and OpenF1 live timing providers.
- Removed background polling, live state aggregation, SSE streaming, and all
  `/live/*` routes.
- Removed obsolete live-provider settings, tests, and direct runtime
  dependencies.
- Removed the obsolete uWSGI configuration.

## [1.1.1] - 2026-07-20

### Changed

- Redesigned the telemetry landing page and its responsive styling.
- Added dynamic display of application version, cache limits, concurrency, and
  API-key header configuration.
- Documented individual and comparison telemetry requests without triggering
  calls from the page.

## [1.1.0] - 2026-07-20

### Added

- Added cache-hit fast paths and per-document coordination around cache misses.
- Added environment overrides for cache size, document count, plotting, and
  telemetry generation concurrency.
- Added a container entrypoint that prepares mounted storage, drops privileges,
  and starts one Uvicorn worker.
- Added configuration, cache, catalog, and entrypoint tests.

### Changed

- Hardened the persistent PDF cache with deterministic names, LRU eviction,
  byte and document limits, validation, and atomic publication.
- Raised the default cache limits to `100` documents and `500 MiB`.
- Split runtime and development dependencies.
- Kept wildcard CORS support for clients that require it.

## [1.0.9] - 2026-03-11

### Added

- Added optional API-key protection for application routes.
- Accepted credentials through a configurable header or
  `Authorization: Bearer`.
- Added authentication tests and updated environment examples.

### Changed

- Centralized API-key and CORS configuration in `AppSettings`.

### Security

- Added constant-time API-key comparison.
- Added explicit `401` responses for missing or invalid credentials.

## [1.0.8] - 2026-03-10

### Added

- Added `TelemetryRuntimeConfig` with TOML and environment loading.
- Added configurable telemetry downsampling and cache-miss concurrency.
- Added `TelemetryPdfCache` with deterministic filenames and LRU eviction; the
  initial document limit was `20`.
- Added cache-hit logging.
- Added unit tests for runtime configuration, filename generation, and cache
  eviction.

### Removed

- Removed an obsolete committed FastF1 cache file.

## [1.0.7] - 2026-03-10

### Changed

- Updated release metadata only; Git history contains no feature commit between
  `1.0.6` and this version bump.

## [1.0.6] - 2026-03-06

### Fixed

- Refined telemetry PDF dimensions, spacing, and text positioning for improved
  readability.

## [1.0.5] - 2026-03-06

### Added

- Added reusable telemetry processing utilities.
- Added richer plot annotations and summary statistic cards.

### Changed

- Improved the telemetry report layout.

## [1.0.4] - 2026-03-06

### Added

- Loaded the application version from `version.json`.
- Displayed the current version on the home page.

## [1.0.3] - 2026-03-06

### Added

- Added `version.json` and explicit application versioning.
- Added process-wide FastF1 cache coordination around a temporary runtime cache
  directory.
