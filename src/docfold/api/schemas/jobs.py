"""Job-related Pydantic schemas."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    """Lifecycle states for an async job."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobResponse(BaseModel):
    """Returned when a job is submitted or its status is queried."""

    job_id: str
    status: JobStatus
    created_at: datetime
    updated_at: datetime | None = None
    engine_name: str | None = None
    progress: float | None = Field(None, ge=0, le=1, description="0.0–1.0 progress")
    error: str | None = None


class JobResultResponse(BaseModel):
    """Full result payload for a completed job."""

    job_id: str
    status: JobStatus
    content: str | None = None
    format: str | None = None
    engine_name: str | None = None
    pages: int | None = None
    processing_time_ms: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
