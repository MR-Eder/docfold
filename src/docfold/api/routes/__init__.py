"""Route aggregation — includes all API route modules."""

from __future__ import annotations

from fastapi import APIRouter

from docfold.api.routes.documents import router as documents_router
from docfold.api.routes.health import router as health_router
from docfold.api.routes.jobs import router as jobs_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(jobs_router)
api_router.include_router(documents_router)
