"""Document processing schemas — request/response models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ConvertRequest(BaseModel):
    """Request body for synchronous document conversion."""

    engine: str | None = Field(None, description="Force a specific engine")
    output_format: str = Field("markdown", description="Output format: markdown, html, json, text")
    allowed_engines: list[str] | None = Field(
        None, description="Restrict engine selection to this list"
    )


class BatchItem(BaseModel):
    """A single item in a batch request (metadata only — file sent via multipart)."""

    engine: str | None = None
    output_format: str = "markdown"


class CompareRequest(BaseModel):
    """Request body for engine comparison."""

    engines: list[str] | None = Field(None, description="Engines to compare (default: all)")
    output_format: str = "markdown"


class EngineInfo(BaseModel):
    """Engine metadata returned by the engines endpoint."""

    name: str
    available: bool
    extensions: list[str]
    capabilities: dict[str, bool]


class ConvertResponse(BaseModel):
    """Response for a completed synchronous conversion."""

    content: str
    format: str
    engine_name: str
    pages: int | None = None
    processing_time_ms: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class BatchResponse(BaseModel):
    """Response for a batch submission."""

    job_id: str
    total_files: int
    status: str = "pending"


class CompareResponse(BaseModel):
    """Response for engine comparison."""

    file_name: str
    results: dict[str, ConvertResponse]
    engines_compared: int
