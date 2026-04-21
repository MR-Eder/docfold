"""Document processing endpoints — convert, batch, compare, engines."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from docfold.api.core.config import Settings, get_settings
from docfold.api.core.deps import get_queue, get_router
from docfold.api.core.provider_keys import get_all_provider_keys
from docfold.api.schemas.documents import (
    CompareResponse,
    ConvertResponse,
    EngineInfo,
)
from docfold.api.services.processor import ProcessorService

router = APIRouter(prefix="/api/v1", tags=["documents"])


def _get_processor(
    engine_router=Depends(get_router),
    settings: Settings = Depends(get_settings),
) -> ProcessorService:
    return ProcessorService(router=engine_router, upload_dir=settings.upload_dir)


# ------------------------------------------------------------------
# GET /api/v1/engines
# ------------------------------------------------------------------


@router.get("/engines", response_model=list[EngineInfo])
async def list_engines(
    engine_router=Depends(get_router),
) -> list[EngineInfo]:
    """List all registered engines with availability and capabilities."""
    engines = engine_router.list_engines()
    return [EngineInfo(**e) for e in engines]


# ------------------------------------------------------------------
# POST /api/v1/convert  (async — returns job_id)
# ------------------------------------------------------------------


@router.post("/convert")
async def convert_async(
    file: UploadFile = File(...),
    engine: str | None = Form(None),
    output_format: str = Form("markdown"),
    processor: ProcessorService = Depends(_get_processor),
    queue=Depends(get_queue),
) -> dict[str, Any]:
    """Submit a document for async conversion. Returns a job_id for polling."""
    content = await file.read()
    file_path = await processor.save_upload(file.filename or "upload", content)

    job = await queue.enqueue_job(
        task_type="convert",
        params={
            "file_path": file_path,
            "engine": engine,
            "output_format": output_format,
            "provider_keys": get_all_provider_keys(),
        },
    )
    return {"job_id": job.job_id, "status": job.status.value}


# ------------------------------------------------------------------
# POST /api/v1/convert/sync  (synchronous — waits for result)
# ------------------------------------------------------------------


@router.post("/convert/sync", response_model=ConvertResponse)
async def convert_sync(
    file: UploadFile = File(...),
    engine: str | None = Form(None),
    output_format: str = Form("markdown"),
    processor: ProcessorService = Depends(_get_processor),
) -> ConvertResponse:
    """Submit and wait for document conversion result."""
    content = await file.read()
    file_path = await processor.save_upload(file.filename or "upload", content)

    try:
        result = await processor.process_document(
            file_path=file_path,
            output_format=output_format,
            engine_hint=engine,
            provider_keys=get_all_provider_keys(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        # Clean up uploaded file
        try:
            os.remove(file_path)
        except OSError:
            pass

    return ConvertResponse(**result)


# ------------------------------------------------------------------
# POST /api/v1/batch  (async — returns job_id)
# ------------------------------------------------------------------


@router.post("/batch")
async def batch_convert(
    files: list[UploadFile] = File(...),
    engine: str | None = Form(None),
    output_format: str = Form("markdown"),
    processor: ProcessorService = Depends(_get_processor),
    queue=Depends(get_queue),
) -> dict[str, Any]:
    """Submit multiple documents for batch processing."""
    file_paths = []
    for f in files:
        content = await f.read()
        fpath = await processor.save_upload(f.filename or "upload", content)
        file_paths.append(fpath)

    job = await queue.enqueue_job(
        task_type="batch",
        params={
            "file_paths": file_paths,
            "engine": engine,
            "output_format": output_format,
        },
    )

    return {
        "job_id": job.job_id,
        "total_files": len(file_paths),
        "status": job.status.value,
    }


# ------------------------------------------------------------------
# POST /api/v1/compare  (sync — compares engines on a document)
# ------------------------------------------------------------------


@router.post("/compare", response_model=CompareResponse)
async def compare_engines(
    file: UploadFile = File(...),
    engines: str | None = Form(None),
    output_format: str = Form("markdown"),
    processor: ProcessorService = Depends(_get_processor),
) -> CompareResponse:
    """Compare multiple engines on the same document."""
    content = await file.read()
    file_path = await processor.save_upload(file.filename or "upload", content)

    engine_list = engines.split(",") if engines else None

    try:
        results = await processor.compare_engines(
            file_path=file_path,
            output_format=output_format,
            engines=engine_list,
        )
    finally:
        try:
            os.remove(file_path)
        except OSError:
            pass

    convert_results = {name: ConvertResponse(**data) for name, data in results.items()}

    return CompareResponse(
        file_name=file.filename or "upload",
        results=convert_results,
        engines_compared=len(convert_results),
    )
