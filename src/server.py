from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from src.app_settings import AppSettings
from src.live import (
    LiveAggregator,
    LiveService,
    OpenF1Provider,
    SSEBroadcaster,
    UnofficialF1SignalRProvider,
)
from src.legacy_catalog import LegacyCatalogService
from src.telemetry_cache import TelemetryPdfCache
from src.telemetry_runtime_config import TelemetryRuntimeConfig
from src.send_telemetry_file import SendTelemetryFile
from src.telemetry import Telemetry, TelemetryError

logger = logging.getLogger(__name__)
_PUBLIC_PATHS = {"/", "/favicon.ico"}
_PUBLIC_PREFIXES = ("/static/",)


def _default_provider_order(provider: str):
    mapping = {
        "signalr": ["signalr"],
        "openf1": ["openf1", "signalr"],
    }
    return mapping.get(provider, ["signalr"])


def _read_app_version(base_dir: Path) -> str:
    version_file = base_dir / "version.json"
    try:
        payload = json.loads(version_file.read_text(encoding="utf-8"))
        version = str(payload.get("version", "")).strip()
        return version or "0.0.0"
    except Exception:
        return "0.0.0"


def _extract_request_api_key(request: Request, header_name: str) -> str:
    header_value = request.headers.get(header_name, "").strip()
    if header_value:
        return header_value

    auth_value = request.headers.get("Authorization", "").strip()
    if auth_value.lower().startswith("bearer "):
        return auth_value[7:].strip()
    return ""


def _build_providers(settings: AppSettings):
    openf1_provider = OpenF1Provider(
        base_url=settings.openf1_base_url,
        api_key=settings.openf1_api_key,
        username=settings.openf1_username,
        password=settings.openf1_password,
        token_url=settings.openf1_token_url,
        token_refresh_sec=settings.openf1_token_refresh_sec,
        verify_ssl=True,
    )
    signalr_provider = UnofficialF1SignalRProvider(
        connection_url=settings.signalr_connection_url,
        negotiate_url=settings.signalr_negotiate_url,
        timeout_sec=settings.signalr_timeout_sec,
        no_auth=settings.signalr_no_auth,
        access_token=settings.signalr_access_token,
        verify_ssl=settings.signalr_verify_ssl,
    )

    registry = {
        "openf1": openf1_provider,
        "signalr": signalr_provider,
    }

    order = settings.provider_order or _default_provider_order(settings.provider)
    resolved = []
    seen = set()
    for name in order:
        if name == "openf1" and not (
            settings.openf1_api_key
            or (settings.openf1_username and settings.openf1_password)
        ):
            continue
        provider = registry.get(name)
        if provider and name not in seen:
            resolved.append(provider)
            seen.add(name)

    if not resolved:
        resolved = [signalr_provider]

    return resolved


def create_app(
    settings: Optional[AppSettings] = None,
    primary_provider=None,
    fallback_provider=None,
    legacy_catalog_service: Optional[LegacyCatalogService] = None,
) -> FastAPI:
    app_settings = settings or AppSettings.from_env()
    aggregator = LiveAggregator()
    telemetry_config = TelemetryRuntimeConfig.load()
    telemetry_cache = TelemetryPdfCache(
        cache_dir=telemetry_config.cache_dir,
        max_docs=telemetry_config.cache_max_docs,
    )

    if primary_provider is None and fallback_provider is None:
        providers = _build_providers(app_settings)
    else:
        providers = []
        if primary_provider is not None:
            providers.append(primary_provider)
        if fallback_provider is not None:
            providers.append(fallback_provider)

    live_service = LiveService(
        aggregator=aggregator,
        providers=providers,
        poll_ms=app_settings.live_poll_ms,
    )
    sse_broadcaster = SSEBroadcaster(
        aggregator=aggregator,
        heartbeat_sec=app_settings.live_heartbeat_sec,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        for provider in providers:
            warmup = getattr(provider, "warmup", None)
            if callable(warmup):
                try:
                    await warmup()
                except Exception:
                    # Fallback providers are handled by LiveService polling logic.
                    pass
        await live_service.start()
        await live_service.reload()
        yield
        await live_service.stop()

    server = FastAPI(title="F1 Race Room Backend", lifespan=lifespan)
    server.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

    base_dir = Path(__file__).resolve().parent.parent
    app_version = _read_app_version(base_dir)
    templates = Jinja2Templates(directory=str(base_dir / "templates"))
    server.mount("/static", StaticFiles(directory=str(base_dir / "static")), name="static")

    server.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    server.state.settings = app_settings
    server.state.aggregator = aggregator
    server.state.live_service = live_service
    server.state.sse_broadcaster = sse_broadcaster
    server.state.legacy_catalog_service = legacy_catalog_service or LegacyCatalogService()
    server.state.app_version = app_version
    server.state.telemetry_config = telemetry_config
    server.state.telemetry_semaphore = asyncio.Semaphore(telemetry_config.max_concurrency)
    server.state.telemetry_pdf_cache = telemetry_cache
    server.state.telemetry_cache_locks = {}

    @server.middleware("http")
    async def api_key_guard(request: Request, call_next):
        expected_api_key = server.state.settings.api_request_key
        request_path = request.url.path
        is_public_path = request_path in _PUBLIC_PATHS or any(
            request_path.startswith(prefix) for prefix in _PUBLIC_PREFIXES
        )
        if not expected_api_key or request.method == "OPTIONS" or is_public_path:
            return await call_next(request)

        provided_api_key = _extract_request_api_key(
            request,
            server.state.settings.api_key_header,
        )
        if provided_api_key and secrets.compare_digest(provided_api_key, expected_api_key):
            return await call_next(request)

        client_host = request.client.host if request.client else "unknown"
        logger.warning(
            "[auth] unauthorized request path=%s client=%s",
            request.url.path,
            client_host,
        )
        return JSONResponse(
            {"detail": "Unauthorized: invalid or missing API key"},
            status_code=401,
        )

    @server.get("/")
    async def index(request: Request):
        settings = server.state.settings
        provider_order = settings.provider_order or _default_provider_order(settings.provider)
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "provider": settings.provider,
                "provider_order": ",".join(provider_order),
                "live_poll_ms": settings.live_poll_ms,
                "live_heartbeat_sec": settings.live_heartbeat_sec,
                "app_version": server.state.app_version,
            },
        )

    @server.get("/status")
    async def status():
        snapshot = server.state.aggregator.get_snapshot()
        return {
            "status": snapshot["status"],
            "provider": snapshot["provider"],
            "version": snapshot["version"],
        }

    @server.get("/get-telemetry")
    async def get_telemetry(
        year: Optional[int] = Query(default=None),
        track_name: Optional[str] = Query(default=None, alias="trackName"),
        session: Optional[str] = Query(default=None),
        driver_name: Optional[str] = Query(default=None, alias="driverName"),
    ):
        if year is None or not track_name or not session or not driver_name:
            return JSONResponse(
                {
                    "error": (
                        "Missing required parameters: year, trackName, session, driverName"
                    )
                },
                status_code=400,
            )

        telemetry = Telemetry(
            year=year,
            track_name=track_name,
            session=session,
            driver_name=driver_name,
            max_plot_points=server.state.telemetry_config.max_plot_points,
        )
        send_manager = SendTelemetryFile()
        cache_manager = server.state.telemetry_pdf_cache
        cache_filename = cache_manager.single_filename(year, track_name, session, driver_name)

        cached_file_path = cache_manager.get_cached_path(cache_filename)
        if cached_file_path:
            logger.info(
                "[telemetry] cache-hit single file=%s year=%s track=%s session=%s driver=%s",
                cache_filename,
                year,
                track_name,
                session,
                driver_name,
            )
            return send_manager.send_file_from_path(file_path=cached_file_path)

        cache_lock = server.state.telemetry_cache_locks.setdefault(cache_filename, asyncio.Lock())

        try:
            async with cache_lock:
                cached_file_path = cache_manager.get_cached_path(cache_filename)
                if cached_file_path:
                    logger.info(
                        "[telemetry] cache-hit-after-lock single file=%s year=%s track=%s session=%s driver=%s",
                        cache_filename,
                        year,
                        track_name,
                        session,
                        driver_name,
                    )
                    return send_manager.send_file_from_path(file_path=cached_file_path)

                async with server.state.telemetry_semaphore:
                    output_path = cache_manager.prepare_output_path(cache_filename)
                    logger.info(
                        "[telemetry] cache-miss generating-fastf1 single file=%s year=%s track=%s session=%s driver=%s",
                        cache_filename,
                        year,
                        track_name,
                        session,
                        driver_name,
                    )
                    file_path = await asyncio.to_thread(telemetry.get_fl_telemetry, output_path)
                    cache_manager.touch(file_path)
                    cache_manager.enforce_limit()
                    logger.info(
                        "[telemetry] generated-fastf1 single file=%s path=%s",
                        cache_filename,
                        file_path,
                    )
            response = send_manager.send_file_from_path(file_path=file_path)
            return response
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except TelemetryError as exc:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Data not found. Could not process telemetry data. "
                    "Please check the provided parameters."
                ),
            ) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"An error occurred: {exc}") from exc

    @server.get("/get-telemetry-compare")
    async def get_telemetry_compare(
        year: Optional[int] = Query(default=None),
        track_name: Optional[str] = Query(default=None, alias="trackName"),
        session: Optional[str] = Query(default=None),
        driver_a: Optional[str] = Query(default=None, alias="driverA"),
        driver_b: Optional[str] = Query(default=None, alias="driverB"),
    ):
        if year is None or not track_name or not session or not driver_a or not driver_b:
            return JSONResponse(
                {
                    "error": (
                        "Missing required parameters: year, trackName, session, driverA, driverB"
                    )
                },
                status_code=400,
            )

        telemetry = Telemetry(
            year=year,
            track_name=track_name,
            session=session,
            driver_name=driver_a,
            max_plot_points=server.state.telemetry_config.max_plot_points,
        )
        send_manager = SendTelemetryFile()
        cache_manager = server.state.telemetry_pdf_cache
        cache_filename = cache_manager.comparison_filename(
            year=year,
            track_name=track_name,
            session=session,
            driver_a=driver_a,
            driver_b=driver_b,
        )

        cached_file_path = cache_manager.get_cached_path(cache_filename)
        if cached_file_path:
            logger.info(
                "[telemetry] cache-hit compare file=%s year=%s track=%s session=%s driver_a=%s driver_b=%s",
                cache_filename,
                year,
                track_name,
                session,
                driver_a,
                driver_b,
            )
            return send_manager.send_file_from_path(file_path=cached_file_path)

        cache_lock = server.state.telemetry_cache_locks.setdefault(cache_filename, asyncio.Lock())

        try:
            async with cache_lock:
                cached_file_path = cache_manager.get_cached_path(cache_filename)
                if cached_file_path:
                    logger.info(
                        "[telemetry] cache-hit-after-lock compare file=%s year=%s track=%s session=%s driver_a=%s driver_b=%s",
                        cache_filename,
                        year,
                        track_name,
                        session,
                        driver_a,
                        driver_b,
                    )
                    return send_manager.send_file_from_path(file_path=cached_file_path)

                async with server.state.telemetry_semaphore:
                    output_path = cache_manager.prepare_output_path(cache_filename)
                    logger.info(
                        "[telemetry] cache-miss generating-fastf1 compare file=%s year=%s track=%s session=%s driver_a=%s driver_b=%s",
                        cache_filename,
                        year,
                        track_name,
                        session,
                        driver_a,
                        driver_b,
                    )
                    file_path = await asyncio.to_thread(
                        telemetry.get_comparison_telemetry_pdf,
                        driver_a,
                        driver_b,
                        output_path,
                    )
                    cache_manager.touch(file_path)
                    cache_manager.enforce_limit()
                    logger.info(
                        "[telemetry] generated-fastf1 compare file=%s path=%s",
                        cache_filename,
                        file_path,
                    )
            response = send_manager.send_file_from_path(file_path=file_path)
            return response
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except TelemetryError as exc:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Data not found. Could not process comparison telemetry data. "
                    "Please check the provided parameters."
                ),
            ) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"An error occurred: {exc}") from exc

    @server.get("/legacy/catalog/events")
    async def legacy_catalog_events(
        year: Optional[int] = Query(default=None),
    ):
        if year is None:
            raise HTTPException(status_code=400, detail="Missing required parameter: year")

        try:
            events = await asyncio.to_thread(
                server.state.legacy_catalog_service.get_events,
                year,
            )
            return {
                "year": year,
                "events": events,
            }
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Could not load events for year {year}: {exc}") from exc

    @server.get("/legacy/catalog/years")
    async def legacy_catalog_years():
        try:
            years = await asyncio.to_thread(server.state.legacy_catalog_service.get_years)
            return {"years": years}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Could not load available years: {exc}") from exc

    @server.get("/legacy/catalog/drivers")
    async def legacy_catalog_drivers(
        year: Optional[int] = Query(default=None),
        track_name: Optional[str] = Query(default=None, alias="trackName"),
        session: Optional[str] = Query(default=None),
    ):
        if year is None or not track_name or not session:
            raise HTTPException(
                status_code=400,
                detail="Missing required parameters: year, trackName, session",
            )

        try:
            drivers = await asyncio.to_thread(
                server.state.legacy_catalog_service.get_drivers,
                year,
                track_name,
                session,
            )
            return {
                "year": year,
                "track_name": track_name,
                "session": session,
                "drivers": drivers,
            }
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Could not load driver catalog. "
                    f"Please verify year/trackName/session values. Details: {exc}"
                ),
            ) from exc

    @server.get("/live/session/current")
    async def live_session_current():
        snapshot = server.state.aggregator.get_snapshot()
        return {
            "version": snapshot["version"],
            "provider": snapshot["provider"],
            "status": snapshot["status"],
            "session": snapshot["current_session"],
        }

    @server.get("/live/timing/snapshot")
    async def live_timing_snapshot():
        return server.state.aggregator.get_snapshot()

    @server.get("/live/timing/stream")
    async def live_timing_stream(request: Request):
        return StreamingResponse(
            server.state.sse_broadcaster.stream(request),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @server.post("/live/reload")
    async def live_reload():
        snapshot = await server.state.live_service.reload()
        return snapshot

    return server


server = create_app()


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5050"))
    uvicorn.run("src.server:server", host="0.0.0.0", port=port, reload=False)
