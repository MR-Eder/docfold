"""FastAPI application factory for the docfold API."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pipeline_common.middleware import (
    TenantMiddleware,
    add_request_id_middleware,
    parse_cors_origins,
    parse_tenants,
)

from docfold.api.core.auth import APIKeyMiddleware
from docfold.api.core.config import get_settings
from docfold.api.core.logging import setup_logging
from docfold.api.core.provider_keys import ProviderKeysMiddleware
from docfold.api.routes import api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle handler."""
    settings = get_settings()

    # Ensure upload and results directories exist
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.results_dir.mkdir(parents=True, exist_ok=True)

    # Pre-warm the engine router so first request isn't slow
    from docfold.api.core.deps import get_router

    get_router()

    yield  # app runs here

    # Cleanup: close Redis pool if queue was initialised
    from docfold.api.core.deps import _job_queue

    if _job_queue is not None:
        await _job_queue.close()


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="docfold API",
        description=(
            "REST API for docfold — turn any document into structured data. "
            "Supports 16+ document processing engines with async job queue."
        ),
        version="0.6.12",
        lifespan=lifespan,
    )

    # --- Request ID middleware (shared impl) ---
    add_request_id_middleware(app)

    # --- CORS ---
    # M2 fix: ``allow_origins=["*"]`` with ``allow_credentials=True`` is
    # spec-violating — browsers reject the combo. ``parse_cors_origins``
    # forces credentials off when the wildcard is present and leaves
    # them on for an explicit origin list.
    cors_origins, allow_credentials = parse_cors_origins(settings.cors_origins)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Multi-tenancy ---
    # Added BEFORE APIKeyMiddleware — last-added runs first, so auth
    # gates before tenant resolution.
    app.add_middleware(
        TenantMiddleware,
        tenants=parse_tenants(settings.tenants),
        allow_default=settings.allow_default_tenant,
    )

    # --- API Key Authentication ---
    app.add_middleware(
        APIKeyMiddleware,
        api_keys=settings.api_keys,
        service_key=settings.service_key,
    )

    # --- Provider Keys (BYOK) ---
    app.add_middleware(ProviderKeysMiddleware)

    # Routes
    app.include_router(api_router)

    return app


# Module-level instance for uvicorn: docfold.api.app:app
_settings = get_settings()
setup_logging(level=_settings.log_level.upper(), service="docfold")
app = create_app()
