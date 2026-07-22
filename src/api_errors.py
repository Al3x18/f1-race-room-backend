"""Translate application failures into stable, public HTTP responses."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.telemetry.errors import (
    DriverTelemetryUnavailableError,
    SessionUnavailableError,
    TelemetryArtifactError,
    TelemetryError,
    TelemetryGenerationError,
    TelemetryProviderError,
)

logger = logging.getLogger(__name__)


class ApiErrorCode(StrEnum):
    MISSING_REQUIRED_PARAMETERS = "MISSING_REQUIRED_PARAMETERS"
    SESSION_UNAVAILABLE = "SESSION_UNAVAILABLE"
    DRIVER_TELEMETRY_UNAVAILABLE = "DRIVER_TELEMETRY_UNAVAILABLE"
    TELEMETRY_DATA_UNAVAILABLE = "TELEMETRY_DATA_UNAVAILABLE"
    TELEMETRY_PROVIDER_UNAVAILABLE = "TELEMETRY_PROVIDER_UNAVAILABLE"
    TELEMETRY_GENERATION_FAILED = "TELEMETRY_GENERATION_FAILED"
    TELEMETRY_FILE_UNAVAILABLE = "TELEMETRY_FILE_UNAVAILABLE"
    INTERNAL_SERVER_ERROR = "INTERNAL_SERVER_ERROR"


@dataclass(frozen=True)
class ApiErrorDefinition:
    status_code: int
    code: ApiErrorCode
    detail: str
    log_level: int = logging.ERROR


MISSING_SINGLE_TELEMETRY_PARAMETERS = ApiErrorDefinition(
    status_code=400,
    code=ApiErrorCode.MISSING_REQUIRED_PARAMETERS,
    detail="Missing required parameters: year, trackName, session, driverName",
    log_level=logging.INFO,
)

MISSING_COMPARISON_TELEMETRY_PARAMETERS = ApiErrorDefinition(
    status_code=400,
    code=ApiErrorCode.MISSING_REQUIRED_PARAMETERS,
    detail="Missing required parameters: year, trackName, session, driverA, driverB",
    log_level=logging.INFO,
)

_TELEMETRY_ERRORS: dict[type[TelemetryError], ApiErrorDefinition] = {
    SessionUnavailableError: ApiErrorDefinition(
        status_code=404,
        code=ApiErrorCode.SESSION_UNAVAILABLE,
        detail="The requested session is not available.",
        log_level=logging.INFO,
    ),
    DriverTelemetryUnavailableError: ApiErrorDefinition(
        status_code=404,
        code=ApiErrorCode.DRIVER_TELEMETRY_UNAVAILABLE,
        detail="Telemetry is not available for the requested driver.",
        log_level=logging.INFO,
    ),
    TelemetryProviderError: ApiErrorDefinition(
        status_code=502,
        code=ApiErrorCode.TELEMETRY_PROVIDER_UNAVAILABLE,
        detail="The telemetry data provider is temporarily unavailable.",
    ),
    TelemetryGenerationError: ApiErrorDefinition(
        status_code=500,
        code=ApiErrorCode.TELEMETRY_GENERATION_FAILED,
        detail="An internal error occurred while generating telemetry.",
    ),
    TelemetryArtifactError: ApiErrorDefinition(
        status_code=500,
        code=ApiErrorCode.TELEMETRY_FILE_UNAVAILABLE,
        detail="The generated telemetry file is unavailable.",
    ),
    TelemetryError: ApiErrorDefinition(
        status_code=400,
        code=ApiErrorCode.TELEMETRY_DATA_UNAVAILABLE,
        detail="Could not process telemetry data. Please check the provided parameters.",
    ),
}

INTERNAL_SERVER_ERROR = ApiErrorDefinition(
    status_code=500,
    code=ApiErrorCode.INTERNAL_SERVER_ERROR,
    detail="An internal server error occurred.",
)


def api_error_response(error: ApiErrorDefinition) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content={"code": error.code.value, "detail": error.detail},
    )


def _telemetry_error_definition(exc: TelemetryError) -> ApiErrorDefinition:
    for error_type in type(exc).__mro__:
        definition = _TELEMETRY_ERRORS.get(error_type)
        if definition is not None:
            return definition
    return _TELEMETRY_ERRORS[TelemetryError]


async def telemetry_error_handler(
    request: Request,
    exc: TelemetryError,
) -> JSONResponse:
    definition = _telemetry_error_definition(exc)
    logger.log(
        definition.log_level,
        "[telemetry] request failed code=%s path=%s error=%s",
        definition.code.value,
        request.url.path,
        exc,
        exc_info=(type(exc), exc, exc.__traceback__)
        if definition.log_level >= logging.ERROR
        else None,
    )
    return api_error_response(definition)


async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "[api] unexpected request error path=%s",
        request.url.path,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return api_error_response(INTERNAL_SERVER_ERROR)


def install_api_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(TelemetryError, telemetry_error_handler)
    app.add_exception_handler(Exception, unexpected_error_handler)
