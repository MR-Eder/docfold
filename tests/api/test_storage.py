"""Tests for the storage service."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from docfold.api.services.storage import StorageService


@pytest.fixture
def storage(tmp_path: Path) -> StorageService:
    """Create a storage service backed by a temp directory."""
    return StorageService(
        upload_dir=tmp_path / "uploads",
        results_dir=tmp_path / "results",
    )


class TestUploadStorage:
    """Tests for upload file operations."""

    @pytest.mark.asyncio
    async def test_save_and_read_upload(self, storage: StorageService):
        content = b"fake PDF content"
        path = await storage.save_upload("test.pdf", content)
        assert Path(path).exists()
        assert Path(path).read_bytes() == content

    @pytest.mark.asyncio
    async def test_delete_upload(self, storage: StorageService):
        path = await storage.save_upload("test.pdf", b"content")
        assert Path(path).exists()

        deleted = await storage.delete_upload(path)
        assert deleted is True
        assert not Path(path).exists()

    @pytest.mark.asyncio
    async def test_delete_nonexistent_upload(self, storage: StorageService):
        deleted = await storage.delete_upload("/nonexistent/file")
        assert deleted is False


class TestResultStorage:
    """Tests for result file operations."""

    @pytest.mark.asyncio
    async def test_save_and_get_result(self, storage: StorageService):
        path = await storage.save_result("job-123", "# Hello World")
        assert Path(path).exists()

        content = await storage.get_result("job-123")
        assert content == "# Hello World"

    @pytest.mark.asyncio
    async def test_get_nonexistent_result(self, storage: StorageService):
        content = await storage.get_result("nonexistent")
        assert content is None

    @pytest.mark.asyncio
    async def test_delete_result(self, storage: StorageService):
        await storage.save_result("job-123", "content")
        deleted = await storage.delete_result("job-123")
        assert deleted is True

        content = await storage.get_result("job-123")
        assert content is None


class TestCleanup:
    """Tests for file cleanup."""

    @pytest.mark.asyncio
    async def test_cleanup_expired_files(self, storage: StorageService, tmp_path: Path):
        # Create a file and backdate its modification time
        path = await storage.save_upload("old_file.pdf", b"old content")
        old_time = time.time() - (48 * 3600)  # 48 hours ago
        import os

        os.utime(path, (old_time, old_time))

        # Create a fresh file
        await storage.save_upload("new_file.pdf", b"new content")

        removed = await storage.cleanup_expired(max_age_hours=24)
        assert removed == 1

    @pytest.mark.asyncio
    async def test_get_storage_info(self, storage: StorageService):
        await storage.save_upload("a.pdf", b"x")
        await storage.save_result("job-1", "content")

        info = storage.get_storage_info()
        assert info["backend"] == "local"
        assert info["upload_count"] == 1
        assert info["result_count"] == 1
