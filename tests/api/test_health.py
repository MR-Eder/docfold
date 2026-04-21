"""Tests for health and readiness endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from docfold.api.app import create_app
from docfold.api.core.deps import get_router


@pytest.fixture
def client():
    """Create a test client with mocked dependencies."""
    app = create_app()
    with TestClient(app) as c:
        yield c


class TestHealthEndpoint:
    """Tests for GET /health."""

    def test_health_returns_200(self, client: TestClient):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data

    def test_health_always_succeeds(self, client: TestClient):
        """Health probe should succeed even without engines."""
        response = client.get("/health")
        assert response.status_code == 200


class TestReadinessEndpoint:
    """Tests for GET /ready."""

    def test_ready_with_available_engines(self):
        """When engines are available, readiness should return 'ready'."""
        app = create_app()

        mock_router = MagicMock()
        mock_router.list_engines.return_value = [
            {"name": "pymupdf", "available": True, "extensions": ["pdf"]},
            {"name": "tesseract", "available": False, "extensions": ["png"]},
        ]
        app.dependency_overrides[get_router] = lambda: mock_router

        with TestClient(app) as client:
            response = client.get("/ready")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ready"
            assert data["engines_available"] == 1

        app.dependency_overrides.clear()

    def test_ready_with_no_engines(self):
        """When no engines are available, readiness should return 'not_ready'."""
        app = create_app()

        mock_router = MagicMock()
        mock_router.list_engines.return_value = []
        app.dependency_overrides[get_router] = lambda: mock_router

        with TestClient(app) as client:
            response = client.get("/ready")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "not_ready"

        app.dependency_overrides.clear()
