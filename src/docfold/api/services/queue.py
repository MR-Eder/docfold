"""Job queue abstraction with Redis backend and in-memory fallback."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from pipeline_common.tenant_context import get_tenant_id

from docfold.api.schemas.jobs import JobResponse, JobResultResponse, JobStatus

logger = logging.getLogger(__name__)


class JobQueue:
    """Manages async job lifecycle via Redis (or in-memory fallback).

    The queue stores job metadata and results as JSON in Redis hashes.
    When Redis is not available, falls back to an in-memory dict so
    the API can still function in development without Docker.
    """

    def __init__(self, redis_url: str = "redis://localhost:6379") -> None:
        self._redis_url = redis_url
        self._redis: Any = None
        self._connected = False

        # In-memory fallback
        self._jobs: dict[str, dict[str, Any]] = {}
        self._results: dict[str, dict[str, Any]] = {}

    async def _ensure_redis(self) -> bool:
        """Try to connect to Redis. Return True if successful."""
        if self._connected and self._redis is not None:
            return True
        try:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(self._redis_url, decode_responses=True)
            await self._redis.ping()
            self._connected = True
            logger.info("Connected to Redis at %s", self._redis_url)
            return True
        except Exception as exc:
            logger.warning("Redis unavailable (%s) — using in-memory fallback", exc)
            self._connected = False
            self._redis = None
            return False

    # ------------------------------------------------------------------
    # Job submission
    # ------------------------------------------------------------------

    async def enqueue_job(
        self,
        task_type: str = "convert",
        params: dict[str, Any] | None = None,
    ) -> JobResponse:
        """Create a new job and return its initial status."""
        job_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        # Snapshot the tenant from the ContextVar at enqueue time so the
        # worker can rebind it at the start of every job. Without this,
        # the worker would process every job under DEFAULT_TENANT and
        # Redis keys / voyager collections / metrics would all attribute
        # cross-tenant work to "default" — the failure mode the audit
        # flagged as C3.
        enriched_params = {"tenant_id": get_tenant_id(), **(params or {})}

        job_data = {
            "job_id": job_id,
            "status": JobStatus.PENDING.value,
            "task_type": task_type,
            "params": json.dumps(enriched_params),
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "engine_name": None,
            "progress": None,
            "error": None,
        }

        if await self._ensure_redis():
            # Redis hset rejects None values — filter them out
            redis_data = {k: v for k, v in job_data.items() if v is not None}
            await self._redis.hset(f"job:{job_id}", mapping=redis_data)
        else:
            self._jobs[job_id] = job_data

        return JobResponse(
            job_id=job_id,
            status=JobStatus.PENDING,
            created_at=now,
            updated_at=now,
        )

    # ------------------------------------------------------------------
    # Status & result retrieval
    # ------------------------------------------------------------------

    async def get_job_status(self, job_id: str) -> JobResponse | None:
        """Get current job status. Returns None if not found."""
        raw: dict[str, Any] | None = None

        if await self._ensure_redis():
            raw = await self._redis.hgetall(f"job:{job_id}")
            if not raw:
                return None
        else:
            raw = self._jobs.get(job_id)
            if raw is None:
                return None

        return JobResponse(
            job_id=raw["job_id"],
            status=JobStatus(raw["status"]),
            created_at=datetime.fromisoformat(raw["created_at"]),
            updated_at=(
                datetime.fromisoformat(raw["updated_at"]) if raw.get("updated_at") else None
            ),
            engine_name=raw.get("engine_name") or None,
            progress=float(raw["progress"]) if raw.get("progress") else None,
            error=raw.get("error") or None,
        )

    async def get_job_result(self, job_id: str) -> JobResultResponse | None:
        """Get the full result for a completed job."""
        raw: dict[str, Any] | None = None

        if await self._ensure_redis():
            raw_str = await self._redis.get(f"result:{job_id}")
            if raw_str:
                raw = json.loads(raw_str)
        else:
            raw = self._results.get(job_id)

        if raw is None:
            return None

        return JobResultResponse(**raw)

    # ------------------------------------------------------------------
    # State mutations (used by workers)
    # ------------------------------------------------------------------

    async def update_job(
        self,
        job_id: str,
        status: JobStatus | None = None,
        engine_name: str | None = None,
        progress: float | None = None,
        error: str | None = None,
    ) -> None:
        """Update job metadata (called by worker tasks)."""
        updates: dict[str, Any] = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if status is not None:
            updates["status"] = status.value
        if engine_name is not None:
            updates["engine_name"] = engine_name
        if progress is not None:
            updates["progress"] = str(progress)
        if error is not None:
            updates["error"] = error

        if await self._ensure_redis():
            await self._redis.hset(f"job:{job_id}", mapping=updates)
        else:
            if job_id in self._jobs:
                self._jobs[job_id].update(updates)

    async def store_result(
        self,
        job_id: str,
        result: dict[str, Any],
        ttl_seconds: int = 86400,
    ) -> None:
        """Store the result payload for a completed job."""
        result_data = {"job_id": job_id, **result}

        if await self._ensure_redis():
            await self._redis.set(
                f"result:{job_id}",
                json.dumps(result_data, default=str),
                ex=ttl_seconds,
            )
        else:
            self._results[job_id] = result_data

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the Redis connection pool."""
        if self._redis is not None:
            await self._redis.close()
            self._redis = None
            self._connected = False
