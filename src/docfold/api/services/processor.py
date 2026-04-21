"""Processor service — wraps EngineRouter for the API layer."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from docfold.engines.base import EngineResult, OutputFormat
from docfold.engines.router import EngineRouter


class ProcessorService:
    """High-level document processing service for the API.

    Handles file persistence (uploaded files → temp path), delegates to
    the :class:`EngineRouter`, and formats responses for the API layer.
    """

    def __init__(self, router: EngineRouter, upload_dir: Path | None = None) -> None:
        self._router = router
        self._upload_dir = upload_dir or Path(tempfile.gettempdir()) / "docfold" / "uploads"
        self._upload_dir.mkdir(parents=True, exist_ok=True)

    async def process_document(
        self,
        file_path: str,
        output_format: str = "markdown",
        engine_hint: str | None = None,
        allowed_engines: list[str] | None = None,
        provider_keys: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Process a single document and return API-friendly result dict."""
        fmt = OutputFormat(output_format)

        if allowed_engines:
            self._router._allowed_engines = set(allowed_engines)

        try:
            result = await self._router.process(
                file_path,
                output_format=fmt,
                engine_hint=engine_hint,
                provider_keys=provider_keys or {},
            )
        finally:
            # Reset allowed engines after processing
            if allowed_engines:
                self._router._allowed_engines = None

        return self._result_to_dict(result)

    async def compare_engines(
        self,
        file_path: str,
        output_format: str = "markdown",
        engines: list[str] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Run engine comparison and return results dict."""
        fmt = OutputFormat(output_format)
        results = await self._router.compare(file_path, fmt, engines=engines)
        return {name: self._result_to_dict(res) for name, res in results.items()}

    def list_engines(self) -> list[dict[str, Any]]:
        """Return engine info list."""
        return self._router.list_engines()

    async def save_upload(self, filename: str, content: bytes) -> str:
        """Save uploaded file content and return the path."""
        dest = self._upload_dir / filename
        dest.write_bytes(content)
        return str(dest)

    @staticmethod
    def _result_to_dict(result: EngineResult) -> dict[str, Any]:
        """Convert EngineResult to an API-friendly dict."""
        return {
            "content": result.content,
            "format": result.format.value,
            "engine_name": result.engine_name,
            "pages": result.pages,
            "processing_time_ms": result.processing_time_ms,
            "metadata": result.metadata,
        }
