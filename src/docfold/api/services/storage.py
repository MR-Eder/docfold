"""Storage service — handles file persistence for uploads and results."""

from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Safe filename charset — alphanumerics, dash, dot, underscore. Matches
# what browsers produce for sanitised downloads and what every engine
# we shell out to can read back without quoting surprises. Anything
# outside this set is stripped so a caller-supplied ``../../etc/passwd``
# becomes ``etcpasswd`` — the path-traversal construct can't survive
# the sanitiser, and the containment check below is a second fence.
_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _sanitise_filename(filename: str) -> str:
    """Return a filesystem-safe basename derived from ``filename``.

    Steps (in order):
      1. Strip any directory components — only the basename survives.
         This alone neutralises ``../../etc/passwd``-style inputs.
      2. Replace runs of unsafe characters with a single ``_``.
      3. Collapse leading dots so callers can't land on dotfiles
         (``.ssh/config`` -> ``ssh_config`` after step 1+2; ``.env``
         -> ``env``).
      4. Cap the length at 255 bytes (POSIX NAME_MAX) to prevent a
         pathological long-filename DoS on the upload directory.
      5. Fall back to ``"upload"`` if the sanitiser stripped everything
         (e.g. filename was entirely separators or dots).
    """
    base = os.path.basename(filename or "")
    base = _SAFE_FILENAME_RE.sub("_", base)
    base = base.lstrip(".")
    base = base[:255]
    return base or "upload"


def _assert_contained(dest: Path, root: Path) -> None:
    """Raise ``ValueError`` unless ``dest`` resolves inside ``root``.

    Belt-and-suspenders check on top of the basename sanitiser: if a
    future refactor accidentally re-introduces a path segment into the
    caller path, this stops the write before bytes hit disk. Uses
    ``Path.resolve()`` so symlink targets are also honoured.
    """
    try:
        dest.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(
            f"refusing to write outside upload root: {dest} not under {root}"
        ) from exc


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
        """Save an uploaded file and return its path.

        ``filename`` is user-controlled — previous versions would happily
        accept ``../../etc/passwd`` and write ``{ts}_../../etc/passwd``
        (Path behaviour: still a path under ``_upload_dir`` syntactically,
        but ``resolve()`` escapes). The sanitiser strips the directory
        components and unsafe characters; the containment check is a
        defence-in-depth fence in case the sanitiser misses something.
        """
        ts = int(time.time() * 1000)
        safe_name = f"{ts}_{_sanitise_filename(filename)}"
        dest = self._upload_dir / safe_name
        _assert_contained(dest, self._upload_dir)
        dest.write_bytes(content)
        logger.info("Saved upload: %s (%d bytes)", dest, len(content))
        return str(dest)

    async def get_upload(self, filename: str) -> bytes | None:
        """Read an uploaded file's content.

        Sanitises the caller-supplied name so a request like
        ``GET /uploads/../secrets.txt`` can't read outside the upload
        directory. Returns ``None`` when the path doesn't exist OR
        escapes the root — fail-silent here rather than leaking which
        paths exist via differential errors.
        """
        path = self._upload_dir / _sanitise_filename(filename)
        try:
            _assert_contained(path, self._upload_dir)
        except ValueError:
            return None
        if path.exists():
            return path.read_bytes()
        return None

    async def delete_upload(self, file_path: str) -> bool:
        """Delete an uploaded file.

        Only deletes when the resolved path is inside the upload root —
        prevents a caller from passing ``/etc/passwd`` or similar.
        Returns ``False`` on escape attempts so the caller sees a normal
        "not found" outcome rather than a 500.
        """
        path = Path(file_path)
        try:
            _assert_contained(path, self._upload_dir)
        except ValueError:
            logger.warning("delete_upload refused out-of-root path: %s", file_path)
            return False
        try:
            os.remove(path)
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
