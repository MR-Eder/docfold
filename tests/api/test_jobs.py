"""Tests for job status and result endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from docfold.api.app import create_app
from docfold.api.core.deps import get_queue
from docfold.api.schemas.jobs import JobResponse, JobResultResponse, JobStatus


@pytest.fixture
def mock_queue():
    return AsyncMock()


@pytest.fixture
def client(mock_queue):
    app = create_app()
    app.dependency_overrides[get_queue] = lambda: mock_queue
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


class TestGetJobStatus:
    """Tests for GET /api/v1/jobs/{job_id}."""

    def test_existing_job(self, client: TestClient, mock_queue):
        now = datetime.now(timezone.utc)
        mock_queue.get_job_status.return_value = JobResponse(
            job_id="abc-123",
            status=JobStatus.PROCESSING,
            created_at=now,
            engine_name="pymupdf",
            progress=0.5,
        )

        response = client.get("/api/v1/jobs/abc-123")
        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == "abc-123"
        assert data["status"] == "processing"
        assert data["engine_name"] == "pymupdf"

    def test_nonexistent_job(self, client: TestClient, mock_queue):
        mock_queue.get_job_status.return_value = None

        response = client.get("/api/v1/jobs/does-not-exist")
        assert response.status_code == 404


class TestGetJobResult:
    """Tests for GET /api/v1/jobs/{job_id}/result."""

    def test_completed_job_result(self, client: TestClient, mock_queue):
        now = datetime.now(timezone.utc)
        mock_queue.get_job_status.return_value = JobResponse(
            job_id="abc-123",
            status=JobStatus.COMPLETED,
            created_at=now,
        )
        mock_queue.get_job_result.return_value = JobResultResponse(
            job_id="abc-123",
            status=JobStatus.COMPLETED,
            content="# Hello World",
            format="markdown",
            engine_name="pymupdf",
            processing_time_ms=150,
        )

        response = client.get("/api/v1/jobs/abc-123/result")
        assert response.status_code == 200
        data = response.json()
        assert data["content"] == "# Hello World"
        assert data["engine_name"] == "pymupdf"

    def test_pending_job_returns_409(self, client: TestClient, mock_queue):
        now = datetime.now(timezone.utc)
        mock_queue.get_job_status.return_value = JobResponse(
            job_id="abc-123",
            status=JobStatus.PENDING,
            created_at=now,
        )

        response = client.get("/api/v1/jobs/abc-123/result")
        assert response.status_code == 409

    def test_nonexistent_job_result_returns_404(self, client: TestClient, mock_queue):
        mock_queue.get_job_status.return_value = None

        response = client.get("/api/v1/jobs/does-not-exist/result")
        assert response.status_code == 404
