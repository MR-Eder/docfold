"""Health and readiness probe endpoints."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends

from docfold.api.core.deps import get_router

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict:
    """Liveness probe — always returns 200 if the process is alive."""
    return {
        "status": "healthy",
        "timestamp": time.time(),
    }


@router.get("/ready")
async def readiness_check(
    engine_router=Depends(get_router),
) -> dict:
    """Readiness probe — checks that at least one engine is available."""
    engines = engine_router.list_engines()
    available = [e for e in engines if e["available"]]

    if available:
        return {
            "status": "ready",
            "engines_available": len(available),
            "engines_total": len(engines),
        }
    return {
        "status": "not_ready",
        "engines_available": 0,
        "engines_total": len(engines),
    }
