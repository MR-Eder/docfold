"""Per-request provider API keys via contextvars.

The ``ProviderKeysMiddleware`` extracts the ``X-Provider-Keys`` JSON
header (injected by the frontend playground proxy) and stores the
key-value map in a contextvar.  Any downstream code can call
``get_provider_key("OPENAI_API_KEY")`` to retrieve the user's key.
"""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger(__name__)

# Context variable — set per-request by the middleware
_provider_keys: ContextVar[dict[str, str]] = ContextVar("provider_keys", default={})


def get_provider_key(name: str) -> str | None:
    """Get a provider API key for the current request.

    Returns the key from the ``X-Provider-Keys`` header if present,
    otherwise ``None`` (so callers fall back to env-var defaults).
    """
    return _provider_keys.get().get(name)


def get_all_provider_keys() -> dict[str, str]:
    """Return all provider keys for the current request."""
    return dict(_provider_keys.get())


class ProviderKeysMiddleware(BaseHTTPMiddleware):
    """Extract X-Provider-Keys header and populate the contextvar."""

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        raw = request.headers.get("X-Provider-Keys")
        if raw:
            try:
                keys = json.loads(raw)
                if isinstance(keys, dict):
                    _provider_keys.set(keys)
                    logger.debug(
                        "Provider keys injected for request: %s",
                        list(keys.keys()),
                    )
            except (json.JSONDecodeError, TypeError):
                logger.warning("Invalid X-Provider-Keys header, ignoring")
        else:
            _provider_keys.set({})

        response = await call_next(request)
        return response
