"""Firecrawl engine adapter.

Install: ``pip install docfold[firecrawl]``

Requires a Firecrawl API key: https://www.firecrawl.dev/

Firecrawl converts documents (PDF, DOCX, images, HTML) into clean markdown.
It handles scanned PDFs via OCR, JavaScript-rendered web pages, and produces
high-quality structured markdown output with tables and headings preserved.

Example::

    engine = FirecrawlEngine(api_key="fc-...")
    result = await engine.process("report.pdf", output_format=OutputFormat.MARKDOWN)
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

from docfold.engines.base import DocumentEngine, EngineCapabilities, EngineResult, OutputFormat

logger = logging.getLogger(__name__)

_SUPPORTED_EXTENSIONS = {"pdf", "docx", "png", "jpg", "jpeg", "tiff", "html", "htm", "xml"}

_TEXT_EXTENSIONS = {"html", "htm", "xml"}


class FirecrawlEngine(DocumentEngine):
    """Adapter for the Firecrawl API (SaaS).

    Firecrawl converts documents and web content into clean, structured
    markdown.  Supports PDF (text and scanned), Office documents, images,
    and HTML.  Handles JavaScript rendering, removes boilerplate, and
    extracts the main content with headings and tables preserved.

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
        try:
            import firecrawl  # noqa: F401

            return bool(self._api_key)
        except ImportError:
            return False

    async def process(
        self,
        file_path: str,
        output_format: OutputFormat = OutputFormat.MARKDOWN,
        **kwargs: Any,
    ) -> EngineResult:
        """Process a document via the Firecrawl API.

        Supports PDF, DOCX, images, and HTML files.  Binary files (PDF,
        images, DOCX) are uploaded directly; text-based files (HTML) are
        read and sent as raw content.
        """
        import asyncio

        start = time.perf_counter()

        loop = asyncio.get_running_loop()
        content, metadata = await loop.run_in_executor(
            None, self._extract, file_path, output_format
        )

        elapsed_ms = int((time.perf_counter() - start) * 1000)

        return EngineResult(
            content=content,
            format=output_format,
            engine_name=self.name,
            processing_time_ms=elapsed_ms,
            metadata=metadata,
        )

    def _extract(
        self,
        file_path: str,
        output_format: OutputFormat,
    ) -> tuple[str, dict[str, Any]]:
        from firecrawl import FirecrawlApp

        app = FirecrawlApp(api_key=self._api_key, api_url=self._api_url)

        ext = Path(file_path).suffix.lstrip(".").lower()

        fmt_map = {
            OutputFormat.MARKDOWN: "markdown",
            OutputFormat.HTML: "html",
            OutputFormat.JSON: "markdown",
            OutputFormat.TEXT: "markdown",
        }
        requested_fmt = fmt_map[output_format]

        if ext in _TEXT_EXTENSIONS:
            with open(file_path, encoding="utf-8") as f:
                html_content = f.read()

            result = app.scrape_url(
                f"raw:{file_path}",
                params={
                    "formats": [requested_fmt],
                    "rawHtml": html_content,
                    "timeout": self._timeout * 1000,
                },
            )
        else:
            # Binary files: PDF, DOCX, images — upload directly
            with open(file_path, "rb") as f:
                file_bytes = f.read()

            result = app.scrape_url(
                f"raw:{file_path}",
                params={
                    "formats": [requested_fmt],
                    "rawContent": file_bytes,
                    "timeout": self._timeout * 1000,
                },
            )

        content = ""
        if isinstance(result, dict):
            content = result.get(requested_fmt, result.get("markdown", ""))
            metadata = result.get("metadata", {})
        else:
            content = str(result)
            metadata = {}

        # For text output, strip markdown formatting
        if output_format == OutputFormat.TEXT:
            import re

            content = re.sub(r"[#*_`~\[\]]", "", content)

        return content, metadata
