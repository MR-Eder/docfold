"""LightOnOCR-2 engine adapter — LightOn's SOTA end-to-end OCR model.

Install: ``pip install docfold[lightonocr]``

LightOnOCR-2-1B is a 1B-parameter vision-language model that converts
document pages (PDF renders / images) into clean, naturally ordered Markdown
without relying on multi-stage pipelines.  SOTA on OlmOCR-Bench (83.2%),
3.3× faster than Chandra, Apache 2.0 licensed.

Supports model variants:
- ``lightonai/LightOnOCR-2-1B`` — default, best transcription
- ``lightonai/LightOnOCR-2-1B-bbox`` — OCR + embedded image localization
- ``lightonai/LightOnOCR-2-1B-ocr-soup`` — tradeoff (OCR + bbox strengths)

No API key needed; runs entirely locally.

See https://huggingface.co/lightonai/LightOnOCR-2-1B
"""

from __future__ import annotations

import logging
import time
from typing import Any

from docfold.engines.base import DocumentEngine, EngineCapabilities, EngineResult, OutputFormat

logger = logging.getLogger(__name__)

_SUPPORTED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "tiff", "tif", "bmp", "webp"}

# Rendering scale: 200 DPI / 72 ≈ 2.77
_PDF_RENDER_SCALE = 200 / 72

# Max longest dimension for rendered pages
_MAX_DIMENSION = 1540


def _resize_to_max(image: Any, max_dim: int = _MAX_DIMENSION) -> Any:
    """Resize PIL image so longest side <= max_dim, preserving aspect ratio."""
    w, h = image.size
    if max(w, h) <= max_dim:
        return image
    scale = max_dim / max(w, h)
    new_w = int(w * scale)
    new_h = int(h * scale)
    return image.resize((new_w, new_h))


class LightOnOCREngine(DocumentEngine):
    """Adapter for LightOnOCR-2 (end-to-end document → Markdown).

    Uses HuggingFace Transformers API (``transformers >= 5.0``).

    Args:
        model: HuggingFace model ID.  Default ``lightonai/LightOnOCR-2-1B``.
        max_new_tokens: Maximum tokens to generate per page.
        render_dpi_scale: Scale factor for PDF page rendering (200 DPI ≈ 2.77).
    """

    def __init__(
        self,
        model: str = "lightonai/LightOnOCR-2-1B",
        max_new_tokens: int = 4096,
        render_dpi_scale: float = _PDF_RENDER_SCALE,
    ) -> None:
        self._model_id = model
        self._max_new_tokens = max_new_tokens
        self._render_scale = render_dpi_scale
        self._model = None
        self._processor = None

    @property
    def name(self) -> str:
        return "lightonocr"

    @property
    def supported_extensions(self) -> set[str]:
        return _SUPPORTED_EXTENSIONS

    @property
    def capabilities(self) -> EngineCapabilities:
        return EngineCapabilities(
            table_structure=True,
            heading_detection=True,
            reading_order=True,
        )

    def is_available(self) -> bool:
        try:
            import pypdfium2  # noqa: F401
            import torch  # noqa: F401
            import transformers  # noqa: F401

            # LightOnOcrForConditionalGeneration requires transformers >= 5.0
            from transformers import LightOnOcrForConditionalGeneration  # noqa: F401

            return True
        except Exception:
            return False

    def _load_model(self) -> tuple[Any, Any]:
        """Lazy-load model + processor on first use."""
        if self._model is not None:
            return self._model, self._processor

        import torch
        from transformers import LightOnOcrForConditionalGeneration, LightOnOcrProcessor

        device = (
            "mps"
            if torch.backends.mps.is_available()
            else "cuda"
            if torch.cuda.is_available()
            else "cpu"
        )
        dtype = torch.float32 if device in ("mps", "cpu") else torch.bfloat16

        logger.info(
            "Loading LightOnOCR-2 model '%s' on %s (dtype=%s)",
            self._model_id,
            device,
            dtype,
        )

        self._model = LightOnOcrForConditionalGeneration.from_pretrained(
            self._model_id, torch_dtype=dtype
        ).to(device)
        self._processor = LightOnOcrProcessor.from_pretrained(self._model_id)

        logger.info("LightOnOCR-2 model loaded successfully")
        return self._model, self._processor

    def _render_pdf_pages(self, file_path: str) -> list[Any]:
        """Render each page of a PDF to a PIL image at 200 DPI."""
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(file_path)
        images = []
        for page in pdf:
            pil_image = page.render(scale=self._render_scale).to_pil()
            pil_image = _resize_to_max(pil_image)
            images.append(pil_image)
        pdf.close()
        return images

    def _ocr_image(self, image: Any, model: Any, processor: Any) -> str:
        """Run OCR on a single PIL image and return text."""
        import torch

        conversation = [{"role": "user", "content": [{"type": "image", "image": image}]}]

        inputs = processor.apply_chat_template(
            conversation,
            add_generation_prompt=True,
            tokenize=True,
            return_dict=True,
            return_tensors="pt",
        )

        device = next(model.parameters()).device
        dtype = next(model.parameters()).dtype
        inputs = {
            k: v.to(device=device, dtype=dtype) if v.is_floating_point() else v.to(device)
            for k, v in inputs.items()
        }

        with torch.no_grad():
            output_ids = model.generate(**inputs, max_new_tokens=self._max_new_tokens)

        generated_ids = output_ids[0, inputs["input_ids"].shape[1] :]
        return processor.decode(generated_ids, skip_special_tokens=True)

    async def process(
        self,
        file_path: str,
        output_format: OutputFormat = OutputFormat.MARKDOWN,
        **kwargs: Any,
    ) -> EngineResult:
        import asyncio

        start = time.perf_counter()

        loop = asyncio.get_running_loop()
        content, page_count = await loop.run_in_executor(
            None, self._do_process, file_path, output_format
        )

        elapsed_ms = int((time.perf_counter() - start) * 1000)

        return EngineResult(
            content=content,
            format=output_format,
            engine_name=self.name,
            pages=page_count,
            processing_time_ms=elapsed_ms,
            metadata={"model": self._model_id},
        )

    def _do_process(self, file_path: str, output_format: OutputFormat) -> tuple[str, int]:
        from pathlib import Path

        from PIL import Image

        model, processor = self._load_model()
        ext = Path(file_path).suffix.lstrip(".").lower()

        # Load page images
        if ext == "pdf":
            images = self._render_pdf_pages(file_path)
        else:
            img = Image.open(file_path).convert("RGB")
            img = _resize_to_max(img)
            images = [img]

        # OCR each page
        pages_text: list[str] = []
        for idx, image in enumerate(images):
            logger.info("Processing page %d/%d", idx + 1, len(images))
            text = self._ocr_image(image, model, processor)
            pages_text.append(text)

        page_count = len(pages_text)
        full_text = "\n\n".join(pages_text)

        # Format output
        if output_format == OutputFormat.JSON:
            import json

            content = json.dumps(
                {"pages": [{"page": i + 1, "text": t} for i, t in enumerate(pages_text)]},
                ensure_ascii=False,
            )
        elif output_format == OutputFormat.HTML:
            html_parts = [
                f"<div class='page' data-page='{i + 1}'><p>{t}</p></div>"
                for i, t in enumerate(pages_text)
            ]
            content = "<html><body>" + "\n".join(html_parts) + "</body></html>"
        else:
            content = full_text

        return content, page_count
