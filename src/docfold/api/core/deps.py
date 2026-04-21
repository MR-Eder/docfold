"""FastAPI dependency injection providers."""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from docfold.api.core.config import get_settings

if TYPE_CHECKING:
    from docfold.api.services.queue import JobQueue
    from docfold.engines.router import EngineRouter


@lru_cache
def get_router() -> EngineRouter:
    """Build and cache the engine router with all discoverable engines.

    Mirrors the discovery logic from ``docfold.cli._build_router`` so that
    the API uses the same engine registry.
    """
    from docfold.engines.router import EngineRouter

    router = EngineRouter()

    _engine_imports: list[tuple[str, str]] = [
        ("docfold.engines.docling_engine", "DoclingEngine"),
        ("docfold.engines.mineru_engine", "MinerUEngine"),
        ("docfold.engines.marker_engine", "MarkerEngine"),
        ("docfold.engines.pymupdf_engine", "PyMuPDFEngine"),
        ("docfold.engines.paddleocr_engine", "PaddleOCREngine"),
        ("docfold.engines.tesseract_engine", "TesseractEngine"),
        ("docfold.engines.easyocr_engine", "EasyOCREngine"),
        ("docfold.engines.unstructured_engine", "UnstructuredEngine"),
        ("docfold.engines.llamaparse_engine", "LlamaParseEngine"),
        ("docfold.engines.mistral_ocr_engine", "MistralOCREngine"),
        ("docfold.engines.glm_ocr_engine", "GLMOCREngine"),
        ("docfold.engines.zerox_engine", "ZeroxEngine"),
        ("docfold.engines.textract_engine", "TextractEngine"),
        ("docfold.engines.google_docai_engine", "GoogleDocAIEngine"),
        ("docfold.engines.azure_docint_engine", "AzureDocIntEngine"),
        ("docfold.engines.nougat_engine", "NougatEngine"),
        ("docfold.engines.surya_engine", "SuryaEngine"),
        ("docfold.engines.lightonocr_engine", "LightOnOCREngine"),
        ("docfold.engines.firecrawl_engine", "FirecrawlEngine"),
        ("docfold.engines.docling_serve_engine", "DoclingServeEngine"),
    ]

    import importlib

    for module_path, class_name in _engine_imports:
        try:
            mod = importlib.import_module(module_path)
            engine_cls = getattr(mod, class_name)
            router.register(engine_cls())
        except Exception:
            pass

    # Apply engine default from settings
    settings = get_settings()
    if settings.engine_default:
        import os

        os.environ.setdefault("ENGINE_DEFAULT", settings.engine_default)

    return router


_job_queue: JobQueue | None = None


def get_queue() -> JobQueue:
    """Return the shared job queue instance (lazy-initialised)."""
    global _job_queue
    if _job_queue is None:
        from docfold.api.services.queue import JobQueue

        settings = get_settings()
        _job_queue = JobQueue(redis_url=settings.redis_url)
    return _job_queue
