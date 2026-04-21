"""Storage service — handles file persistence for uploads and results."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class StorageService:
    """File storage abstraction supporting local disk and S3-compatible backends.

    For now only local storage is implemented. S3 support can be added by
    subclassing or extending with boto3 calls.
    """

    def __init__(
        self,
        upload_dir: Path | str = "/tmp/docfold/uploads",
        results_dir: Path | str = "/tmp/docfold/results",
        backend: str = "local",
        s3_config: dict[str, Any] | None = None,
    ) -> None:
        self._upload_dir = Path(upload_dir)
        self._results_dir = Path(results_dir)
        self._backend = backend
        self._s3_config = s3_config or {}

        # Ensure directories exist
        self._upload_dir.mkdir(parents=True, exist_ok=True)
        self._results_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Uploads
    # ------------------------------------------------------------------

    async def save_upload(self, filename: str, content: bytes) -> str:
        """Save an uploaded file and return its path."""
        # Add timestamp to avoid collisions
        ts = int(time.time() * 1000)
        safe_name = f"{ts}_{filename}"
        dest = self._upload_dir / safe_name
        dest.write_bytes(content)
        logger.info("Saved upload: %s (%d bytes)", dest, len(content))
        return str(dest)

    async def get_upload(self, filename: str) -> bytes | None:
        """Read an uploaded file's content."""
        path = self._upload_dir / filename
        if path.exists():
            return path.read_bytes()
        return None

    async def delete_upload(self, file_path: str) -> bool:
        """Delete an uploaded file."""
        try:
            os.remove(file_path)
            return True
        except OSError:
            return False

    # ------------------------------------------------------------------
    # Results
    # ------------------------------------------------------------------

    async def save_result(self, job_id: str, content: str, extension: str = "md") -> str:
        """Save a processing result and return its path."""
        dest = self._results_dir / f"{job_id}.{extension}"
        dest.write_text(content, encoding="utf-8")
        logger.info("Saved result: %s", dest)
        return str(dest)

    async def get_result(self, job_id: str, extension: str = "md") -> str | None:
        """Read a processing result."""
        path = self._results_dir / f"{job_id}.{extension}"
        if path.exists():
            return path.read_text(encoding="utf-8")
        return None

    async def delete_result(self, job_id: str, extension: str = "md") -> bool:
        """Delete a processing result."""
        path = self._results_dir / f"{job_id}.{extension}"
        try:
            path.unlink()
            return True
        except OSError:
            return False

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def cleanup_expired(self, max_age_hours: int = 24) -> int:
        """Remove files older than ``max_age_hours``. Returns count removed."""
        cutoff = time.time() - (max_age_hours * 3600)
        removed = 0

        for directory in [self._upload_dir, self._results_dir]:
            for path in directory.iterdir():
                if path.is_file() and path.stat().st_mtime < cutoff:
                    try:
                        path.unlink()
                        removed += 1
                    except OSError:
                        pass

        logger.info("Cleaned up %d expired files", removed)
        return removed

    # ------------------------------------------------------------------
    # Info
    # ------------------------------------------------------------------

    def get_storage_info(self) -> dict[str, Any]:
        """Return storage backend info and usage stats."""
        upload_count = sum(1 for _ in self._upload_dir.iterdir() if _.is_file())
        result_count = sum(1 for _ in self._results_dir.iterdir() if _.is_file())

        return {
            "backend": self._backend,
            "upload_dir": str(self._upload_dir),
            "results_dir": str(self._results_dir),
            "upload_count": upload_count,
            "result_count": result_count,
        }
