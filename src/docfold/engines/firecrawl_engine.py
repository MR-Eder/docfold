"""Firecrawl engine adapter — plain HTTP, no SDK dependency.

Requires a Firecrawl API key: https://www.firecrawl.dev/

Firecrawl converts documents (PDF, DOCX, images, HTML) into clean markdown
via a simple REST API.  This adapter calls ``POST /v1/scrape`` directly
with ``urllib``, so no extra packages are needed.

Example::

    engine = FirecrawlEngine(api_key="fc-...")
    result = await engine.process("report.pdf", output_format=OutputFormat.MARKDOWN)
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
import urllib.request
from pathlib import Path
from typing import Any

from docfold.engines.base import DocumentEngine, EngineCapabilities, EngineResult, OutputFormat

logger = logging.getLogger(__name__)

_SUPPORTED_EXTENSIONS = {"pdf", "docx", "png", "jpg", "jpeg", "tiff", "html", "htm", "xml"}

_TEXT_EXTENSIONS = {"html", "htm", "xml"}


class FirecrawlEngine(DocumentEngine):
    """Adapter for the Firecrawl API via plain HTTP.

    Calls ``POST /v1/scrape`` with ``urllib.request``.  No extra
    dependencies beyond the standard library.

    Example::

        engine = FirecrawlEngine(api_key="fc-...")
        result = await engine.process("report.pdf")
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        api_url: str | None = None,
        timeout: int = 30,
        **kwargs: Any,
    ) -> None:
        self._api_key = api_key or os.getenv("FIRECRAWL_API_KEY")
        self._api_url = (
            api_url or os.getenv("FIRECRAWL_API_URL") or "https://api.firecrawl.dev"
        )
        self._timeout = timeout
        self._extra = kwargs

    @property
    def name(self) -> str:
        return "firecrawl"

    @property
    def supported_extensions(self) -> set[str]:
        return _SUPPORTED_EXTENSIONS

    @property
    def capabilities(self) -> EngineCapabilities:
        return EngineCapabilities(
            table_structure=True,
            heading_detection=True,
        )

    def is_available(self) -> bool:
        return bool(self._api_key)

    async def process(
        self,
        file_path: str,
        output_format: OutputFormat = OutputFormat.MARKDOWN,
        **kwargs: Any,
    ) -> EngineResult:
        """Process a document via the Firecrawl REST API.

        Supports PDF, DOCX, images, and HTML files.
        """
        start = time.perf_counter()

        loop = asyncio.get_running_loop()
        content, metadata = await loop.run_in_executor(
            None, self._call_api, file_path, output_format,
        )

        elapsed_ms = int((time.perf_counter() - start) * 1000)

        return EngineResult(
            content=content,
            format=output_format,
            engine_name=self.name,
            processing_time_ms=elapsed_ms,
            metadata=metadata,
        )

    def _call_api(
        self,
        file_path: str,
        output_format: OutputFormat,
    ) -> tuple[str, dict[str, Any]]:
        ext = Path(file_path).suffix.lstrip(".").lower()

        fmt_map = {
            OutputFormat.MARKDOWN: "markdown",
            OutputFormat.HTML: "html",
            OutputFormat.JSON: "markdown",
            OutputFormat.TEXT: "markdown",
        }
        requested_fmt = fmt_map[output_format]

        body: dict[str, Any] = {
            "url": f"raw:{file_path}",
            "formats": [requested_fmt],
            "timeout": self._timeout * 1000,
        }

        if ext in _TEXT_EXTENSIONS:
            with open(file_path, encoding="utf-8") as f:
                body["html"] = f.read()
        else:
            with open(file_path, "rb") as f:
                raw = f.read()
            body["rawContent"] = base64.b64encode(raw).decode()

        url = f"{self._api_url.rstrip('/')}/v1/scrape"
        payload = json.dumps(body).encode()

        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            resp_data = json.loads(resp.read())

        data = resp_data.get("data", {})
        content = data.get(requested_fmt, data.get("markdown", ""))
        metadata = data.get("metadata", {})

        # For text output, strip markdown formatting
        if output_format == OutputFormat.TEXT:
            import re
            content = re.sub(r"[#*_`~\[\]]", "", content)

        return content, metadata
