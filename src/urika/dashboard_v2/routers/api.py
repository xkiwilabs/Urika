"""JSON API routes — used by HTMX fragments and external callers."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["api"])
