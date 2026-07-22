# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [2.0.0] - 2026-07-22

### Added

- Added typed telemetry-domain errors for unavailable sessions and drivers,
  upstream provider failures, report generation failures, and missing PDF
  artifacts.
- Added centralized FastAPI error definitions and handlers with stable machine
  codes, public English messages, HTTP statuses, and server-side logging.
- Added error-path coverage for both telemetry routes, FastF1 exceptions,
  missing driver laps, renderer failures, invalid parameters, and sanitized
  unexpected errors.

### Changed

- **Breaking:** telemetry error responses now use the consistent
  `{"code": "...", "detail": "..."}` JSON schema. Missing-parameter responses
  previously used an `error` field, while other failures returned only
  `detail`.
- **Breaking:** unavailable sessions and driver telemetry now return `404`,
  upstream FastF1 provider failures return `502`, and report or generated-file
  failures return `500`.
- Moved telemetry error response strings and status mappings out of route
  handlers into a centralized API error catalog.

### Fixed

- Prevented future or unloaded FastF1 sessions from falling through as
  unclassified internal errors when lap data is unavailable.
- Prevented internal provider, renderer, path, and exception details from being
  exposed in API responses.

## [1.2.1] - 2026-07-22

### Changed

- Refactored the oversized telemetry module into a FastF1 facade, pure data
  processing helpers, and a cohesive PDF report builder.
- Grouped telemetry service, processing, reports, cache, and configuration
  under the `src/telemetry` domain package while preserving its public import.
- Extracted telemetry and catalog routes from the FastAPI application factory
  and centralized the shared cached-report generation workflow.
- Added integration coverage for telemetry routes, cache hits, comparison
  arguments, and both PDF report renderers.
- Added explicit module-level documentation across `src` and expanded the
  technical code map with every module's responsibilities, APIs, delegations,
  and side effects.

### Fixed

- Replaced the deprecated FastF1 `utils.delta_time` call with a local,
  distance-normalized interpolation.
- Expressed the total gap and continuous delta from the first selected
  driver's point of view: positive when the first driver is slower and
  negative when the first driver is ahead.
- Fixed negative sub-minute gaps such as `-0.534 s` being incorrectly rendered
  as `-1:59.466`, and made signed formatting reliable for gaps ranging from
  milliseconds to multiple minutes.
- Aligned the delta graph legend and colors with the corrected sign convention.
- Added regression tests for swapped drivers and positive or negative gaps of
  10 seconds, more than one minute, and up to 10 minutes.
- Configured pytest to include the repository root on its import path so the
  direct `pytest` command can collect application modules.

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
