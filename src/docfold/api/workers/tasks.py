"""arq worker tasks for async document processing.

Workers pull jobs from Redis and process them using the EngineRouter.
Run with::

    arq docfold.api.workers.tasks.WorkerSettings
"""

from __future__ import annotations

import logging
import os
from typing import Any

from arq.connections import RedisSettings

from docfold.api.schemas.jobs import JobStatus

logger = logging.getLogger(__name__)


async def process_document_task(ctx: dict, job_id: str, params: dict[str, Any]) -> None:
    """Process a single document conversion job.

    Updates job status in Redis as it progresses, then stores the result.
    """
    queue = ctx["queue"]

    try:
        await queue.update_job(job_id, status=JobStatus.PROCESSING)

        router = ctx["router"]
        file_path = params["file_path"]
        engine = params.get("engine")
        output_format = params.get("output_format", "markdown")

        from docfold.api.services.processor import ProcessorService

        processor = ProcessorService(router=router)
        result = await processor.process_document(
            file_path=file_path,
            output_format=output_format,
            engine_hint=engine,
        )

        await queue.update_job(
            job_id,
            status=JobStatus.COMPLETED,
            engine_name=result.get("engine_name"),
            progress=1.0,
        )
        await queue.store_result(
            job_id,
            {
                "status": JobStatus.COMPLETED.value,
                **result,
            },
        )

    except Exception as exc:
        logger.exception("Job %s failed: %s", job_id, exc)
        await queue.update_job(
            job_id,
            status=JobStatus.FAILED,
            error=str(exc),
        )
        await queue.store_result(
            job_id,
            {
                "status": JobStatus.FAILED.value,
                "error": str(exc),
            },
        )
    finally:
        # Clean up uploaded file
        file_path = params.get("file_path")
        if file_path:
            try:
                os.remove(file_path)
            except OSError:
                pass


async def process_batch_task(ctx: dict, job_id: str, params: dict[str, Any]) -> None:
    """Process a batch of documents."""
    queue = ctx["queue"]

    try:
        await queue.update_job(job_id, status=JobStatus.PROCESSING)

        router = ctx["router"]
        file_paths = params["file_paths"]
        engine = params.get("engine")
        output_format = params.get("output_format", "markdown")

        from docfold.engines.base import OutputFormat

        fmt = OutputFormat(output_format)
        batch_result = await router.process_batch(
            file_paths,
            output_format=fmt,
            engine_hint=engine,
        )

        await queue.update_job(
            job_id,
            status=JobStatus.COMPLETED,
            progress=1.0,
        )

        results_data = {
            fp: {
                "content": res.content,
                "format": res.format.value,
                "engine_name": res.engine_name,
                "pages": res.pages,
                "processing_time_ms": res.processing_time_ms,
            }
            for fp, res in batch_result.results.items()
        }

        await queue.store_result(
            job_id,
            {
                "status": JobStatus.COMPLETED.value,
                "results": results_data,
                "errors": batch_result.errors,
                "total": batch_result.total,
                "succeeded": batch_result.succeeded,
                "failed": batch_result.failed,
                "total_time_ms": batch_result.total_time_ms,
            },
        )

    except Exception as exc:
        logger.exception("Batch job %s failed: %s", job_id, exc)
        await queue.update_job(job_id, status=JobStatus.FAILED, error=str(exc))
        await queue.store_result(
            job_id,
            {
                "status": JobStatus.FAILED.value,
                "error": str(exc),
            },
        )
    finally:
        for fp in params.get("file_paths", []):
            try:
                os.remove(fp)
            except OSError:
                pass


async def compare_engines_task(ctx: dict, job_id: str, params: dict[str, Any]) -> None:
    """Compare engines on a single document."""
    queue = ctx["queue"]

    try:
        await queue.update_job(job_id, status=JobStatus.PROCESSING)

        router = ctx["router"]
        file_path = params["file_path"]
        engines = params.get("engines")
        output_format = params.get("output_format", "markdown")

        from docfold.api.services.processor import ProcessorService

        processor = ProcessorService(router=router)
        results = await processor.compare_engines(
            file_path=file_path,
            output_format=output_format,
            engines=engines,
        )

        await queue.update_job(job_id, status=JobStatus.COMPLETED, progress=1.0)
        await queue.store_result(
            job_id,
            {
                "status": JobStatus.COMPLETED.value,
                "results": results,
                "engines_compared": len(results),
            },
        )

    except Exception as exc:
        logger.exception("Compare job %s failed: %s", job_id, exc)
        await queue.update_job(job_id, status=JobStatus.FAILED, error=str(exc))
        await queue.store_result(
            job_id,
            {
                "status": JobStatus.FAILED.value,
                "error": str(exc),
            },
        )
    finally:
        file_path = params.get("file_path")
        if file_path:
            try:
                os.remove(file_path)
            except OSError:
                pass


# ------------------------------------------------------------------
# arq WorkerSettings
# ------------------------------------------------------------------


async def startup(ctx: dict) -> None:
    """Worker startup — initialise engine router and queue."""
    from docfold.api.core.deps import get_queue, get_router

    ctx["router"] = get_router()
    ctx["queue"] = get_queue()
    logger.info("Worker started — router and queue initialised")


async def shutdown(ctx: dict) -> None:
    """Worker shutdown — close connections."""
    queue = ctx.get("queue")
    if queue:
        await queue.close()
    logger.info("Worker shut down")


def _parse_redis_url(env_var: str, default: str) -> RedisSettings:
    """Parse a Redis URL into arq RedisSettings."""
    from urllib.parse import urlparse

    url = os.environ.get(env_var, default)
    parsed = urlparse(url)
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        database=int(parsed.path.lstrip("/") or 0),
        password=parsed.password,
    )


class WorkerSettings:
    """arq worker configuration.

    Usage::

        arq docfold.api.workers.tasks.WorkerSettings
    """

    functions = [process_document_task, process_batch_task, compare_engines_task]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = _parse_redis_url("DOCFOLD_REDIS_URL", "redis://localhost:6379/0")

    max_jobs = 10
    job_timeout = 600  # 10 minutes
    keep_result = 86400  # 24 hours


if __name__ == "__main__":
    from arq import run_worker

    run_worker(WorkerSettings)
