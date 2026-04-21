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


class TestPathTraversalDefense:
    """H3 regression — caller-supplied filenames are sanitised and
    contained within the upload root. Previously ``../../etc/passwd``
    could flow through :meth:`save_upload` unchecked."""

    @pytest.mark.asyncio
    async def test_save_strips_directory_traversal(
        self, storage: StorageService, tmp_path: Path
    ):
        # A name like ``../../etc/passwd`` must not escape the upload
        # root. Basename strips the prefix; the containment check is
        # the safety net in case a future refactor regresses that.
        path = await storage.save_upload("../../etc/passwd", b"pwned")
        resolved = Path(path).resolve()
        assert resolved.is_relative_to((tmp_path / "uploads").resolve()), (
            f"upload escaped root: {resolved}"
        )
        assert resolved.name.endswith("_passwd"), (
            f"sanitiser should have reduced the name to basename+clean: {resolved.name}"
        )

    @pytest.mark.asyncio
    async def test_save_strips_unsafe_characters(self, storage: StorageService):
        path = await storage.save_upload("file with spaces & $pecial.pdf", b"x")
        name = Path(path).name
        # Spaces, ampersand, dollar sign all collapse to "_".
        assert "&" not in name and " " not in name and "$" not in name
        assert name.endswith(".pdf")

    @pytest.mark.asyncio
    async def test_save_rejects_leading_dot(self, storage: StorageService):
        # Dotfiles would otherwise let an attacker drop an ``.env`` into
        # the upload root.
        path = await storage.save_upload(".env", b"OPENAI_API_KEY=stolen")
        name = Path(path).name
        assert not name.split("_", 1)[1].startswith("."), (
            f"leading dot should be stripped: {name}"
        )

    @pytest.mark.asyncio
    async def test_save_falls_back_on_empty_sanitised_name(
        self, storage: StorageService
    ):
        # An input that's entirely separators / dots sanitises to the
        # empty string; we fall back to ``"upload"`` so the write still
        # lands at a valid, contained path.
        path = await storage.save_upload("../../", b"x")
        assert Path(path).name.endswith("_upload")
        assert Path(path).exists()

    @pytest.mark.asyncio
    async def test_get_upload_refuses_traversal(self, storage: StorageService):
        # ``../../etc/passwd`` must return None, not a file from outside
        # the upload root.
        result = await storage.get_upload("../../etc/passwd")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_refuses_path_outside_root(
        self, storage: StorageService, tmp_path: Path
    ):
        # Create a file *outside* the upload root and try to delete it
        # via the public API.
        outside = tmp_path / "secrets.txt"
        outside.write_text("sensitive")

        ok = await storage.delete_upload(str(outside))
        assert ok is False, "delete_upload should refuse out-of-root paths"
        assert outside.exists(), "the target file must survive the refusal"


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
