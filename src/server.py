"""Build and expose the FastAPI application.

This is the application composition root: it loads settings, initializes shared
state, installs middleware and authentication, defines core routes, and mounts
the domain routers declared in :mod:`src.api_routes`. It does not implement
telemetry processing or PDF rendering.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

# Domain routes are declared in ``src/api_routes.py``. Keeping them outside
# this module leaves ``create_app`` focused on application setup and middleware.
from src.api_routes import catalog_router, telemetry_router
from src.api_errors import install_api_error_handlers
from src.app_settings import AppSettings
from src.legacy_catalog import LegacyCatalogService
from src.telemetry.cache import MIB, TelemetryPdfCache
from src.telemetry.config import TelemetryRuntimeConfig

logger = logging.getLogger(__name__)
_PUBLIC_PATHS = {"/", "/favicon.ico", "/health"}
_PUBLIC_PREFIXES = ("/static/",)


def _read_app_version(base_dir: Path) -> str:
    try:
        payload = json.loads((base_dir / "version.json").read_text(encoding="utf-8"))
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
    """Configure application state, middleware and domain routers."""
    app_settings = settings or AppSettings.from_env()
    telemetry_config = TelemetryRuntimeConfig.load()
    telemetry_cache = TelemetryPdfCache(
        cache_dir=telemetry_config.cache_dir,
        max_docs=telemetry_config.cache_max_docs,
        max_bytes=telemetry_config.cache_max_mb * MIB,
    )

    server = FastAPI(title="F1 Race Room Telemetry Backend")
    install_api_error_handlers(server)
    server.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

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
    server.state.legacy_catalog_service = (
        legacy_catalog_service or LegacyCatalogService()
    )
    server.state.app_version = _read_app_version(base_dir)
    server.state.telemetry_config = telemetry_config
    server.state.telemetry_semaphore = asyncio.Semaphore(
        telemetry_config.max_concurrency
    )
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
        if provided_api_key and secrets.compare_digest(
            provided_api_key,
            expected_api_key,
        ):
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
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "app_version": server.state.app_version,
                "api_key_header": server.state.settings.api_key_header,
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

    # Registers /get-telemetry, /get-telemetry-compare and
    # /telemetry/cache/status, all declared in src/api_routes.py.
    server.include_router(telemetry_router)

    # Registers /legacy/catalog/years, /events and /drivers, also declared in
    # src/api_routes.py. Core routes (/, /health and /status) remain above.
    server.include_router(catalog_router)
    return server


server = create_app()


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5050"))
    uvicorn.run("src.server:server", host="0.0.0.0", port=port, reload=False)
