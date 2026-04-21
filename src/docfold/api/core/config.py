"""Application settings powered by pydantic-settings."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Docfold API configuration.

    All values can be overridden via environment variables prefixed with
    ``DOCFOLD_`` (e.g. ``DOCFOLD_REDIS_URL``).
    """

    # --- Server ---
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1
    log_level: str = "info"
    debug: bool = False

    # --- Auth ---
    api_keys: str = ""
    service_key: str = ""

    # --- Multi-tenancy ---
    tenants: str = ""
    allow_default_tenant: bool = True

    # --- CORS ---
    cors_origins: str = "*"

    # --- Redis ---
    redis_url: str = "redis://localhost:6379"

    # --- Engine ---
    engine_default: str | None = None

    # --- Upload / Storage ---
    upload_dir: Path = Path("/tmp/docfold/uploads")
    results_dir: Path = Path("/tmp/docfold/results")
    max_upload_size_mb: int = 100

    # --- Storage backend ---
    storage_backend: str = "local"  # "local" or "s3"
    s3_bucket: str = ""
    s3_endpoint: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_region: str = "us-east-1"

    # --- Job results ---
    result_ttl_hours: int = 24

    model_config: dict[str, Any] = {
        "env_prefix": "DOCFOLD_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }


@lru_cache
def get_settings() -> Settings:
    """Return a cached settings instance."""
    return Settings()
