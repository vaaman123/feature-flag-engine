"""GET /audit/ — tail the append-only audit log."""
from __future__ import annotations
from typing import Annotated
from fastapi import APIRouter, Query
import audit as audit_store

router = APIRouter(prefix="/audit", tags=["Audit Log"])


@router.get("/", summary="Recent audit entries (newest last)")
async def get_audit(
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
):
    return audit_store.get_audit_log(limit=limit)
