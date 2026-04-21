"""Job status and result retrieval routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from docfold.api.core.deps import get_queue
from docfold.api.schemas.jobs import JobResponse, JobResultResponse, JobStatus

router = APIRouter(prefix="/api/v1", tags=["jobs"])


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job_status(
    job_id: str,
    queue=Depends(get_queue),
) -> JobResponse:
    """Get the current status of a processing job."""
    job = await queue.get_job_status(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return job


@router.get("/jobs/{job_id}/result", response_model=JobResultResponse)
async def get_job_result(
    job_id: str,
    queue=Depends(get_queue),
) -> JobResultResponse:
    """Get the result of a completed job.

    Returns 404 if the job doesn't exist, 409 if the job is still running.
    """
    job = await queue.get_job_status(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    if job.status in (JobStatus.PENDING, JobStatus.PROCESSING):
        raise HTTPException(
            status_code=409,
            detail=f"Job '{job_id}' is still {job.status.value}",
        )

    result = await queue.get_job_result(job_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Result for job '{job_id}' not found")
    return result
