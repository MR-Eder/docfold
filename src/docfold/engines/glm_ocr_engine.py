"""GLM-OCR engine adapter — ZhipuAI's lightweight document parsing model.

Supports two modes:
1. **SDK mode** (``pip install glmocr``): Uses the official SDK for both
   cloud MaaS and self-hosted (vLLM/SGLang) deployments.
2. **HTTP fallback**: Direct API calls using stdlib ``urllib.request`` when
   the SDK is not installed — zero extra dependencies.

Environment variables:
- ``GLM_OCR_API_KEY`` — API key for MaaS / cloud mode
- ``GLM_OCR_BASE_URL`` — Override the default API base URL
- ``GLM_OCR_MODE`` — ``maas`` or ``selfhosted`` (SDK only)
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any

from docfold.engines.base import (
    BoundingBox,
    DocumentEngine,
    EngineCapabilities,
    EngineResult,
    OutputFormat,
)

logger = logging.getLogger(__name__)

_SUPPORTED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg"}

# Label mapping from GLM-OCR native labels to BoundingBox types
_LABEL_MAP: dict[str, str] = {
    "text": "Text",
    "paragraph_title": "SectionHeader",
    "image": "Image",
    "table": "Table",
    "formula": "Formula",
}

_DEFAULT_BASE_URL = "https://api.z.ai/api/paas/v4"


def _has_glmocr_sdk() -> bool:
    """Check if the ``glmocr`` SDK is importable."""
    try:
        import glmocr  # noqa: F401

        return True
    except ImportError:
        return False


class GLMOCREngine(DocumentEngine):
    """Adapter for ZhipuAI's GLM-OCR layout parsing API.

    GLM-OCR is a lightweight 0.9B parameter model that achieves SOTA on
    OmniDocBench V1.5 for document parsing.  It supports PDF and image
    inputs and returns structured Markdown with bounding boxes.

    **Modes**:

    - ``mode="maas"`` — Cloud API via SDK or HTTP fallback (needs API key).
    - ``mode="selfhosted"`` — Local vLLM/SGLang via SDK (needs running server).
    - ``mode=None`` — Auto-detect: SDK if installed, else HTTP fallback.

    See https://docs.z.ai/guides/vlm/glm-ocr
    See https://github.com/zai-org/GLM-OCR
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = "glm-ocr",
        mode: str | None = None,
        ocr_api_host: str | None = None,
        ocr_api_port: int | None = None,
    ) -> None:
        self._api_key = api_key or os.getenv("GLM_OCR_API_KEY")
        self._base_url = (base_url or os.getenv("GLM_OCR_BASE_URL") or _DEFAULT_BASE_URL).rstrip(
            "/"
        )
        self._model = model
        self._mode = mode or os.getenv("GLM_OCR_MODE")  # "maas" | "selfhosted" | None
        self._ocr_api_host = ocr_api_host
        self._ocr_api_port = ocr_api_port
        self._sdk_available = _has_glmocr_sdk()

    @property
    def name(self) -> str:
        return "glm_ocr"

    @property
    def supported_extensions(self) -> set[str]:
        return _SUPPORTED_EXTENSIONS

    @property
    def capabilities(self) -> EngineCapabilities:
        return EngineCapabilities(
            bounding_boxes=True,
            table_structure=True,
            heading_detection=True,
        )

    def is_available(self) -> bool:
        # SDK self-hosted mode: available even without API key
        if self._sdk_available and self._mode == "selfhosted":
            return True
        # MaaS (SDK or HTTP): needs API key
        return bool(self._api_key)

    async def process(
        self,
        file_path: str,
        output_format: OutputFormat = OutputFormat.MARKDOWN,
        **kwargs: Any,
    ) -> EngineResult:
        import asyncio

        start = time.perf_counter()

        # BYOK: allow per-request API key override via provider_keys
        provider_keys = kwargs.get("provider_keys") or {}
        runtime_api_key = (
            provider_keys.get("glm_ocr") or provider_keys.get("GLM_OCR_API_KEY") or self._api_key
        )

        loop = asyncio.get_running_loop()

        if self._sdk_available:
            content, metadata, bboxes, pages = await loop.run_in_executor(
                None,
                self._call_sdk,
                file_path,
                output_format,
                runtime_api_key,
            )
        else:
            content, metadata, bboxes, pages = await loop.run_in_executor(
                None,
                self._call_api,
                file_path,
                output_format,
                runtime_api_key,
            )

        elapsed_ms = int((time.perf_counter() - start) * 1000)

        return EngineResult(
            content=content,
            format=output_format,
            engine_name=self.name,
            processing_time_ms=elapsed_ms,
            metadata=metadata,
            pages=pages,
            bounding_boxes=bboxes,
        )

    # ------------------------------------------------------------------
    # SDK path (glmocr package)
    # ------------------------------------------------------------------

    def _call_sdk(
        self,
        file_path: str,
        output_format: OutputFormat,
        api_key: str | None = None,
    ) -> tuple[str, dict, list[dict[str, Any]] | None, int | None]:
        """Use the official ``glmocr`` SDK for parsing."""
        from glmocr import GlmOcr

        # Build SDK kwargs
        sdk_kwargs: dict[str, Any] = {}
        effective_key = api_key or self._api_key
        if effective_key:
            sdk_kwargs["api_key"] = effective_key
        if self._mode:
            sdk_kwargs["mode"] = self._mode
        if self._ocr_api_host:
            sdk_kwargs["ocr_api_host"] = self._ocr_api_host
        if self._ocr_api_port:
            sdk_kwargs["ocr_api_port"] = self._ocr_api_port
        if self._model and self._model != "glm-ocr":
            sdk_kwargs["model"] = self._model

        logger.info("Calling GLM-OCR via SDK (mode=%s): %s", self._mode or "auto", file_path)

        with GlmOcr(**sdk_kwargs) as parser:
            result = parser.parse(file_path)

        # Extract data from PipelineResult
        md_content: str = result.markdown_result or ""
        json_result = result.json_result or []

        # Page count and dimensions
        data_info: dict = getattr(result, "_data_info", {}) or {}
        num_pages = data_info.get("num_pages") or len(json_result) or None
        page_dims = data_info.get("pages", [])

        # Build bounding boxes from json_result
        # SDK normalizes bboxes to 0-1000 scale; we convert back to pixel coords
        bboxes: list[dict[str, Any]] | None = None
        if json_result:
            bboxes = []
            for page_idx, page_elements in enumerate(json_result):
                # Get page dimensions
                page_w: float | None = None
                page_h: float | None = None
                if page_idx < len(page_dims):
                    page_w = float(page_dims[page_idx].get("width", 0)) or None
                    page_h = float(page_dims[page_idx].get("height", 0)) or None

                for el in page_elements:
                    raw_bbox = el.get("bbox_2d")
                    if not raw_bbox or len(raw_bbox) != 4:
                        continue

                    # Convert 0-1000 normalized coords back to pixel coords
                    if page_w and page_h:
                        pixel_bbox = [
                            raw_bbox[0] * page_w / 1000.0,
                            raw_bbox[1] * page_h / 1000.0,
                            raw_bbox[2] * page_w / 1000.0,
                            raw_bbox[3] * page_h / 1000.0,
                        ]
                    else:
                        pixel_bbox = [float(c) for c in raw_bbox]

                    label = el.get("label", "text")
                    bbox_type = _LABEL_MAP.get(label, "Text")

                    bb = BoundingBox(
                        type=bbox_type,
                        bbox=pixel_bbox,
                        page=page_idx + 1,
                        text=el.get("content", ""),
                        id=f"p{page_idx + 1}-e{el.get('index', 0)}",
                        page_width=page_w,
                        page_height=page_h,
                    )
                    bboxes.append(bb.to_dict())

        # Format conversion
        content = self._format_content(md_content, json_result, output_format)

        # Metadata
        usage = getattr(result, "_usage", None) or {}
        metadata = {
            "model": self._model,
            "mode": self._mode or ("maas" if self._api_key else "selfhosted"),
            "sdk_version": True,
            "usage": usage if usage else None,
        }

        return content, metadata, bboxes, num_pages

    # ------------------------------------------------------------------
    # Direct HTTP path (stdlib only — no glmocr dependency)
    # ------------------------------------------------------------------

    def _call_api(
        self,
        file_path: str,
        output_format: OutputFormat,
        api_key: str | None = None,
    ) -> tuple[str, dict, list[dict[str, Any]] | None, int | None]:
        """POST file to GLM-OCR API directly (stdlib only)."""

        # Encode file as base64 data URI
        ext = os.path.splitext(file_path)[1].lstrip(".").lower()
        mime = {
            "pdf": "application/pdf",
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
        }.get(ext, "application/octet-stream")

        with open(file_path, "rb") as f:
            raw = f.read()
        b64 = base64.b64encode(raw).decode("ascii")
        file_uri = f"data:{mime};base64,{b64}"

        # Build request
        payload = json.dumps(
            {
                "model": self._model,
                "file": file_uri,
            }
        ).encode("utf-8")

        effective_key = api_key or self._api_key
        if not effective_key:
            raise ValueError(
                "GLM-OCR API key is required. Set GLM_OCR_API_KEY env var "
                'or pass it via the X-Provider-Keys header as {"glm_ocr": "your-key"}.'
            )

        url = f"{self._base_url}/layout_parsing"
        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Authorization": f"Bearer {effective_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        logger.info("Calling GLM-OCR API directly: %s (%d bytes)", url, len(raw))

        try:
            resp = urllib.request.urlopen(req, timeout=120)
            data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace") if e.fp else ""
            if e.code == 401:
                raise ValueError(
                    f"GLM-OCR API returned 401 Unauthorized. "
                    f"The API key may be invalid or expired. "
                    f"Response: {body[:500]}"
                ) from e
            elif e.code == 403:
                raise ValueError(f"GLM-OCR API returned 403 Forbidden: {body[:500]}") from e
            else:
                raise ValueError(
                    f"GLM-OCR API request failed with HTTP {e.code}: {body[:500]}"
                ) from e

        # Extract markdown content
        md_content: str = data.get("md_results", "")

        # Page count
        data_info = data.get("data_info", {})
        num_pages: int | None = data_info.get("num_pages")
        page_dims = data_info.get("pages", [])

        # Build bounding boxes
        bboxes: list[dict[str, Any]] | None = None
        layout_details = data.get("layout_details", [])
        if layout_details:
            bboxes = []
            for page_idx, page_elements in enumerate(layout_details):
                page_w: float | None = None
                page_h: float | None = None
                if page_idx < len(page_dims):
                    page_w = float(page_dims[page_idx].get("width", 0)) or None
                    page_h = float(page_dims[page_idx].get("height", 0)) or None

                for el in page_elements:
                    raw_bbox = el.get("bbox_2d", [0, 0, 0, 0])
                    el_w = float(el.get("width", 0)) or page_w
                    el_h = float(el.get("height", 0)) or page_h

                    native_label = el.get("native_label", el.get("label", "text"))
                    label = el.get("label", "text")
                    bbox_type = _LABEL_MAP.get(native_label, _LABEL_MAP.get(label, "Text"))

                    bb = BoundingBox(
                        type=bbox_type,
                        bbox=[float(c) for c in raw_bbox],
                        page=page_idx + 1,
                        text=el.get("content", ""),
                        id=f"p{page_idx + 1}-e{el.get('index', 0)}",
                        page_width=el_w,
                        page_height=el_h,
                    )
                    bboxes.append(bb.to_dict())

        # Format conversion
        content = self._format_content(md_content, layout_details, output_format)

        metadata = {
            "model": data.get("model", self._model),
            "mode": "http",
            "sdk_version": False,
            "usage": data.get("usage"),
            "request_id": data.get("request_id"),
        }

        return content, metadata, bboxes, num_pages

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_content(
        md_content: str,
        layout_pages: list,
        output_format: OutputFormat,
    ) -> str:
        """Convert markdown result to the requested output format."""
        if output_format == OutputFormat.MARKDOWN:
            return md_content

        if output_format == OutputFormat.JSON:
            pages_data = []
            for page_idx, page_elements in enumerate(layout_pages):
                elements = []
                for el in page_elements:
                    elements.append(
                        {
                            "index": el.get("index"),
                            "label": el.get("label"),
                            "content": el.get("content", ""),
                            "bbox_2d": el.get("bbox_2d"),
                        }
                    )
                pages_data.append({"page": page_idx + 1, "elements": elements})
            return json.dumps(
                {"markdown": md_content, "pages": pages_data},
                ensure_ascii=False,
            )

        if output_format == OutputFormat.HTML:
            escaped = md_content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            return f"<html><body><pre>{escaped}</pre></body></html>"

        if output_format == OutputFormat.TEXT:
            import re

            content = re.sub(r"!\[.*?\]\(.*?\)\n*", "", md_content)  # Remove images
            content = re.sub(r"#{1,6}\s*", "", content)  # Remove heading markers
            return content.strip()

        return md_content
