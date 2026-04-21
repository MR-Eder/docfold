"""Tests for the job queue service and worker task lifecycle."""

from __future__ import annotations

import pytest

from docfold.api.schemas.jobs import JobStatus
from docfold.api.services.queue import JobQueue


@pytest.fixture
def queue():
    """Create a queue with in-memory fallback (no Redis needed)."""
    q = JobQueue(redis_url="redis://nonexistent:6379")
    return q


class TestJobQueueInMemory:
    """Test queue operations using the in-memory fallback."""

    @pytest.mark.asyncio
    async def test_enqueue_and_get_status(self, queue: JobQueue):
        job = await queue.enqueue_job(task_type="convert", params={"file": "test.pdf"})
        assert job.status == JobStatus.PENDING
        assert job.job_id

        status = await queue.get_job_status(job.job_id)
        assert status is not None
        assert status.job_id == job.job_id
        assert status.status == JobStatus.PENDING

    @pytest.mark.asyncio
    async def test_nonexistent_job_returns_none(self, queue: JobQueue):
        status = await queue.get_job_status("nonexistent-id")
        assert status is None

    @pytest.mark.asyncio
    async def test_update_job_status(self, queue: JobQueue):
        job = await queue.enqueue_job(task_type="convert")
        await queue.update_job(job.job_id, status=JobStatus.PROCESSING, progress=0.5)

        status = await queue.get_job_status(job.job_id)
        assert status is not None
        assert status.status == JobStatus.PROCESSING

    @pytest.mark.asyncio
    async def test_store_and_retrieve_result(self, queue: JobQueue):
        job = await queue.enqueue_job(task_type="convert")

        result_data = {
            "status": "completed",
            "content": "# Hello World",
            "format": "markdown",
            "engine_name": "pymupdf",
        }
        await queue.store_result(job.job_id, result_data)

        result = await queue.get_job_result(job.job_id)
        assert result is not None
        assert result.job_id == job.job_id
        assert result.content == "# Hello World"

    @pytest.mark.asyncio
    async def test_nonexistent_result_returns_none(self, queue: JobQueue):
        result = await queue.get_job_result("nonexistent-id")
        assert result is None

    @pytest.mark.asyncio
    async def test_full_lifecycle(self, queue: JobQueue):
        """Simulate the full job lifecycle: enqueue → processing → completed."""
        # 1. Enqueue
        job = await queue.enqueue_job(
            task_type="convert",
            params={"file_path": "/tmp/test.pdf", "output_format": "markdown"},
        )
        assert job.status == JobStatus.PENDING

        # 2. Mark processing
        await queue.update_job(job.job_id, status=JobStatus.PROCESSING, engine_name="pymupdf")
        status = await queue.get_job_status(job.job_id)
        assert status.status == JobStatus.PROCESSING
        assert status.engine_name == "pymupdf"

        # 3. Complete
        await queue.update_job(job.job_id, status=JobStatus.COMPLETED, progress=1.0)
        await queue.store_result(
            job.job_id,
            {
                "status": "completed",
                "content": "# Result",
                "format": "markdown",
                "engine_name": "pymupdf",
                "processing_time_ms": 100,
            },
        )

        # 4. Retrieve result
        result = await queue.get_job_result(job.job_id)
        assert result is not None
        assert result.content == "# Result"

    @pytest.mark.asyncio
    async def test_failed_job(self, queue: JobQueue):
        job = await queue.enqueue_job(task_type="convert")
        await queue.update_job(
            job.job_id,
            status=JobStatus.FAILED,
            error="Engine crashed",
        )

        status = await queue.get_job_status(job.job_id)
        assert status.status == JobStatus.FAILED
        assert status.error == "Engine crashed"
