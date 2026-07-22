"""Define the telemetry and legacy-catalog HTTP endpoints.

This module validates query parameters, translates service failures into stable
HTTP responses, and coordinates PDF cache hits/misses. Application creation,
middleware, authentication, and core routes remain in :mod:`src.server`.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from functools import partial
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from src.send_telemetry_file import SendTelemetryFile
from src.telemetry import Telemetry, TelemetryError

logger = logging.getLogger(__name__)

telemetry_router = APIRouter()
catalog_router = APIRouter(prefix="/legacy/catalog")


async def _serve_cached_pdf(
    request: Request,
    cache_filename: str,
    report_kind: str,
    generator: Callable[[str], str],
) -> Any:
    """Return a cached report or generate and atomically publish it."""
    cache_manager = request.app.state.telemetry_pdf_cache
    send_manager = SendTelemetryFile()

    cached_file_path = cache_manager.get_cached_path(cache_filename)
    if cached_file_path:
        logger.info(
            "[telemetry] cache-hit kind=%s file=%s",
            report_kind,
            cache_filename,
        )
        return send_manager.send_file_from_path(file_path=cached_file_path)

    cache_lock = request.app.state.telemetry_cache_locks.setdefault(
        cache_filename,
        asyncio.Lock(),
    )
    async with cache_lock:
        cached_file_path = cache_manager.get_cached_path(cache_filename)
        if cached_file_path:
            logger.info(
                "[telemetry] cache-hit-after-lock kind=%s file=%s",
                report_kind,
                cache_filename,
            )
            return send_manager.send_file_from_path(file_path=cached_file_path)

        async with request.app.state.telemetry_semaphore:
            output_path = cache_manager.prepare_output_path(cache_filename)
            logger.info(
                "[telemetry] cache-miss generating-fastf1 kind=%s file=%s",
                report_kind,
                cache_filename,
            )
            try:
                generated_path = await asyncio.to_thread(generator, output_path)
                file_path = cache_manager.commit_output(cache_filename, generated_path)
            except Exception:
                cache_manager.discard_output(output_path)
                raise
            logger.info(
                "[telemetry] generated-fastf1 kind=%s file=%s path=%s",
                report_kind,
                cache_filename,
                file_path,
            )

    return send_manager.send_file_from_path(file_path=file_path)


def _telemetry_for_request(
    request: Request,
    year: int,
    track_name: str,
    session: str,
    driver_name: str,
) -> Telemetry:
    return Telemetry(
        year=year,
        track_name=track_name,
        session=session,
        driver_name=driver_name,
        max_plot_points=request.app.state.telemetry_config.max_plot_points,
    )


@telemetry_router.get("/telemetry/cache/status")
async def telemetry_cache_status(request: Request):
    return request.app.state.telemetry_pdf_cache.stats()


@telemetry_router.get("/get-telemetry")
async def get_telemetry(
    request: Request,
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

    telemetry = _telemetry_for_request(
        request,
        year,
        track_name,
        session,
        driver_name,
    )
    cache_manager = request.app.state.telemetry_pdf_cache
    cache_filename = cache_manager.single_filename(
        year,
        track_name,
        session,
        driver_name,
    )

    try:
        return await _serve_cached_pdf(
            request,
            cache_filename,
            "single",
            telemetry.get_fl_telemetry,
        )
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


@telemetry_router.get("/get-telemetry-compare")
async def get_telemetry_compare(
    request: Request,
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

    telemetry = _telemetry_for_request(
        request,
        year,
        track_name,
        session,
        driver_a,
    )
    cache_manager = request.app.state.telemetry_pdf_cache
    cache_filename = cache_manager.comparison_filename(
        year=year,
        track_name=track_name,
        session=session,
        driver_a=driver_a,
        driver_b=driver_b,
    )

    try:
        return await _serve_cached_pdf(
            request,
            cache_filename,
            "comparison",
            partial(telemetry.get_comparison_telemetry_pdf, driver_a, driver_b),
        )
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


@catalog_router.get("/events")
async def legacy_catalog_events(
    request: Request,
    year: Optional[int] = Query(default=None),
):
    if year is None:
        raise HTTPException(status_code=400, detail="Missing required parameter: year")

    try:
        events = await asyncio.to_thread(
            request.app.state.legacy_catalog_service.get_events,
            year,
        )
        return {"year": year, "events": events}
    except Exception as exc:
        logger.exception("[legacy-catalog] event lookup failed year=%s", year)
        raise HTTPException(
            status_code=400,
            detail=f"Could not load events for year {year}.",
        ) from exc


@catalog_router.get("/years")
async def legacy_catalog_years(request: Request):
    try:
        years = await asyncio.to_thread(
            request.app.state.legacy_catalog_service.get_years
        )
        return {"years": years}
    except Exception as exc:
        logger.exception("[legacy-catalog] year lookup failed")
        raise HTTPException(
            status_code=400,
            detail="Could not load available years.",
        ) from exc


@catalog_router.get("/drivers")
async def legacy_catalog_drivers(
    request: Request,
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
            request.app.state.legacy_catalog_service.get_drivers,
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
