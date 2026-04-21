"""Tests for document processing endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from docfold.api.app import create_app
from docfold.api.core.deps import get_queue, get_router
from docfold.api.schemas.jobs import JobResponse, JobStatus


class TestEnginesEndpoint:
    """Tests for GET /api/v1/engines."""

    def test_list_engines(self):
        app = create_app()

        mock_router = MagicMock()
        mock_router.list_engines.return_value = [
            {
                "name": "pymupdf",
                "available": True,
                "extensions": ["pdf"],
                "capabilities": {
                    "bounding_boxes": True,
                    "confidence": False,
                    "images": True,
                    "table_structure": False,
                    "heading_detection": False,
                    "reading_order": False,
                },
            }
        ]
        app.dependency_overrides[get_router] = lambda: mock_router

        with TestClient(app) as client:
            response = client.get("/api/v1/engines")
            assert response.status_code == 200
            data = response.json()
            assert len(data) == 1
            assert data[0]["name"] == "pymupdf"
            assert data[0]["available"] is True

        app.dependency_overrides.clear()


class TestConvertAsyncEndpoint:
    """Tests for POST /api/v1/convert."""

    def test_async_convert_returns_job_id(self):
        app = create_app()

        now = datetime.now(timezone.utc)
        mock_queue = AsyncMock()
        mock_queue.enqueue_job.return_value = JobResponse(
            job_id="test-job-1",
            status=JobStatus.PENDING,
            created_at=now,
        )

        mock_router = MagicMock()
        app.dependency_overrides[get_router] = lambda: mock_router
        app.dependency_overrides[get_queue] = lambda: mock_queue

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/convert",
                files={"file": ("test.pdf", b"fake-pdf-bytes", "application/pdf")},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["job_id"] == "test-job-1"
            assert data["status"] == "pending"

        app.dependency_overrides.clear()
