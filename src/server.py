from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.background import BackgroundTask

from src.live import (
    AppSettings,
    LiveAggregator,
    LiveService,
    OpenF1Provider,
    SSEBroadcaster,
    UnofficialF1SignalRProvider,
)
from src.legacy_catalog import LegacyCatalogService
from src.send_telemetry_file import SendTelemetryFile
from src.telemetry import Telemetry, TelemetryError


def _default_provider_order(provider: str):
    mapping = {
        "signalr": ["signalr"],
        "openf1": ["openf1", "signalr"],
    }
    return mapping.get(provider, ["signalr"])


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

    base_dir = Path(__file__).resolve().parent.parent
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
        )
        send_manager = SendTelemetryFile()

        try:
            file_path = await asyncio.to_thread(telemetry.get_fl_telemetry)
            response = send_manager.send_file_from_path(file_path=file_path)
            response.background = BackgroundTask(send_manager.delete_file, file_path)
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
        )
        send_manager = SendTelemetryFile()

        try:
            file_path = await asyncio.to_thread(
                telemetry.get_comparison_telemetry_pdf,
                driver_a,
                driver_b,
            )
            response = send_manager.send_file_from_path(file_path=file_path)
            response.background = BackgroundTask(send_manager.delete_file, file_path)
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
