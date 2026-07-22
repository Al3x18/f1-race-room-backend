from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from src.app_settings import AppSettings
from src.legacy_catalog import LegacyCatalogService
from src.telemetry_cache import MIB, TelemetryPdfCache
from src.telemetry_runtime_config import TelemetryRuntimeConfig
from src.send_telemetry_file import SendTelemetryFile
from src.telemetry import Telemetry, TelemetryError

logger = logging.getLogger(__name__)
_PUBLIC_PATHS = {"/", "/favicon.ico", "/health"}
_PUBLIC_PREFIXES = ("/static/",)


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


def create_app(
    settings: Optional[AppSettings] = None,
    legacy_catalog_service: Optional[LegacyCatalogService] = None,
) -> FastAPI:
    app_settings = settings or AppSettings.from_env()
    telemetry_config = TelemetryRuntimeConfig.load()
    telemetry_cache = TelemetryPdfCache(
        cache_dir=telemetry_config.cache_dir,
        max_docs=telemetry_config.cache_max_docs,
        max_bytes=telemetry_config.cache_max_mb * MIB,
    )

    server = FastAPI(title="F1 Race Room Telemetry Backend")
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
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "app_version": server.state.app_version,
                "api_key_header": settings.api_key_header,
                "cache_max_documents": telemetry_config.cache_max_docs,
                "cache_max_mb": telemetry_config.cache_max_mb,
                "max_concurrency": telemetry_config.max_concurrency,
            },
        )

    @server.get("/status")
    async def status():
        return {
            "status": "ok",
            "service": "telemetry",
            "version": server.state.app_version,
        }

    @server.get("/health")
    async def health():
        return {"status": "ok"}

    @server.get("/telemetry/cache/status")
    async def telemetry_cache_status():
        return server.state.telemetry_pdf_cache.stats()

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
                    try:
                        generated_path = await asyncio.to_thread(
                            telemetry.get_fl_telemetry,
                            output_path,
                        )
                        file_path = cache_manager.commit_output(
                            cache_filename,
                            generated_path,
                        )
                    except Exception:
                        cache_manager.discard_output(output_path)
                        raise
                    logger.info(
                        "[telemetry] generated-fastf1 single file=%s path=%s",
                        cache_filename,
                        file_path,
                    )
            response = send_manager.send_file_from_path(file_path=file_path)
            return response
        except FileNotFoundError as exc:
            logger.exception("[telemetry] generated single PDF was not found")
            raise HTTPException(
                status_code=404,
                detail="Generated telemetry file not found.",
            ) from exc
        except TelemetryError as exc:
            logger.exception("[telemetry] single telemetry generation failed")
            raise HTTPException(
                status_code=400,
                detail=(
                    "Data not found. Could not process telemetry data. "
                    "Please check the provided parameters."
                ),
            ) from exc
        except Exception as exc:
            logger.exception("[telemetry] unexpected single telemetry error")
            raise HTTPException(
                status_code=500,
                detail="An internal error occurred while generating telemetry.",
            ) from exc

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
                    try:
                        generated_path = await asyncio.to_thread(
                            telemetry.get_comparison_telemetry_pdf,
                            driver_a,
                            driver_b,
                            output_path,
                        )
                        file_path = cache_manager.commit_output(
                            cache_filename,
                            generated_path,
                        )
                    except Exception:
                        cache_manager.discard_output(output_path)
                        raise
                    logger.info(
                        "[telemetry] generated-fastf1 compare file=%s path=%s",
                        cache_filename,
                        file_path,
                    )
            response = send_manager.send_file_from_path(file_path=file_path)
            return response
        except FileNotFoundError as exc:
            logger.exception("[telemetry] generated comparison PDF was not found")
            raise HTTPException(
                status_code=404,
                detail="Generated telemetry file not found.",
            ) from exc
        except TelemetryError as exc:
            logger.exception("[telemetry] comparison telemetry generation failed")
            raise HTTPException(
                status_code=400,
                detail=(
                    "Data not found. Could not process comparison telemetry data. "
                    "Please check the provided parameters."
                ),
            ) from exc
        except Exception as exc:
            logger.exception("[telemetry] unexpected comparison telemetry error")
            raise HTTPException(
                status_code=500,
                detail="An internal error occurred while generating telemetry.",
            ) from exc

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
            logger.exception("[legacy-catalog] event lookup failed year=%s", year)
            raise HTTPException(
                status_code=400,
                detail=f"Could not load events for year {year}.",
            ) from exc

    @server.get("/legacy/catalog/years")
    async def legacy_catalog_years():
        try:
            years = await asyncio.to_thread(server.state.legacy_catalog_service.get_years)
            return {"years": years}
        except Exception as exc:
            logger.exception("[legacy-catalog] year lookup failed")
            raise HTTPException(
                status_code=400,
                detail="Could not load available years.",
            ) from exc

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
            logger.exception(
                "[legacy-catalog] driver lookup failed year=%s track=%s session=%s",
                year,
                track_name,
                session,
            )
            raise HTTPException(
                status_code=400,
                detail=(
                    "Could not load driver catalog. "
                    "Please verify year/trackName/session values."
                ),
            ) from exc

    return server


server = create_app()


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5050"))
    uvicorn.run("src.server:server", host="0.0.0.0", port=port, reload=False)
