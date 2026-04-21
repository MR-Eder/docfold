"""API key authentication middleware.

Validates ``Authorization: Bearer <key>`` against a configurable list
of accepted keys.  When no keys are configured (``api_keys`` is empty),
authentication is **disabled** — this preserves backwards compatibility
for development but MUST NOT be used in production.

Public endpoints (health, docs) are always exempt.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# Paths that never require authentication
PUBLIC_PATHS: set[str] = {
    "/health",
    "/ready",
    "/docs",
    "/redoc",
    "/openapi.json",
}


def _is_public(path: str) -> bool:
    """Return True if the path is a public (unauthenticated) endpoint."""
    return path in PUBLIC_PATHS or path.rstrip("/") in PUBLIC_PATHS


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Validate Bearer token against a set of allowed API keys.

    Parameters
    ----------
    app : ASGIApp
        The wrapped ASGI application.
    api_keys : str
        Comma-separated list of accepted API keys.  If empty,
        authentication is disabled (dev-mode).
    service_key : str
        Shared secret for inter-service calls.  Accepted alongside
        normal API keys when non-empty.
    """

    def __init__(self, app, api_keys: str = "", service_key: str = "") -> None:  # noqa: ANN001
        super().__init__(app)
        keys = {k.strip() for k in api_keys.split(",") if k.strip()}
        if service_key:
            keys.add(service_key)
        self._allowed_keys: frozenset[str] = frozenset(keys)
        self._auth_enabled: bool = bool(self._allowed_keys)

        if not self._auth_enabled:
            logger.warning(
                "API key authentication is DISABLED — set API_KEYS env var for production"
            )

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,  # type: ignore[type-arg]
    ) -> Response:
        # Always allow public endpoints
        if _is_public(request.url.path):
            return await call_next(request)

        # Skip auth when no keys configured (dev mode)
        if not self._auth_enabled:
            return await call_next(request)

        # Extract Bearer token
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing or invalid Authorization header"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        token = auth_header[7:]  # strip "Bearer "
        if token not in self._allowed_keys:
            return JSONResponse(
                status_code=403,
                content={"detail": "Invalid API key"},
            )

        return await call_next(request)
