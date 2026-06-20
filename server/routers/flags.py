"""Feature Flags CRUD — ETag conditional responses, eval-cache invalidation, audit logging."""
from __future__ import annotations
import hashlib, json
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from models import FeatureFlag, CreateFlagRequest, UpdateFlagRequest
import storage
from websocket_manager import manager
from routers.evaluate import bump_eval_cache
from audit import write_audit

router = APIRouter(prefix="/flags", tags=["Feature Flags"])


def _etag(data: list) -> str:
    return '"' + hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:24] + '"'


@router.get("/", summary="List all flags")
async def list_flags(request: Request):
    flags = storage.get_all_flags()
    data  = [f.model_dump() for f in flags]
    tag   = _etag(data)
    if request.headers.get("if-none-match") == tag:
        return Response(status_code=304)
    return JSONResponse(content=data, headers={"ETag": tag, "Cache-Control": "no-cache"})


@router.post("/", response_model=FeatureFlag, status_code=201, summary="Create a flag")
async def create_flag(req: CreateFlagRequest):
    if storage.get_flag_by_name(req.name):
        raise HTTPException(409, detail=f"Flag '{req.name}' already exists.")
    flag    = FeatureFlag(**req.model_dump())
    created = storage.create_flag(flag)
    bump_eval_cache()
    write_audit("created", "flag", created.id, created.name,
                {"enabled": created.enabled, "targeting": created.targeting.model_dump()})
    await manager.broadcast("flag_created", created.model_dump())
    return created


@router.get("/{flag_id}", response_model=FeatureFlag, summary="Get a single flag")
async def get_flag(flag_id: str):
    flag = storage.get_flag_by_id(flag_id)
    if not flag:
        raise HTTPException(404, detail="Flag not found.")
    return flag


@router.patch("/{flag_id}", response_model=FeatureFlag, summary="Update a flag")
async def update_flag(flag_id: str, req: UpdateFlagRequest):
    before  = storage.get_flag_by_id(flag_id)
    if not before:
        raise HTTPException(404, detail="Flag not found.")
    updates = req.model_dump(exclude_none=True)
    if "targeting" in updates and hasattr(updates["targeting"], "model_dump"):
        updates["targeting"] = updates["targeting"].model_dump(exclude_none=True)
    updated = storage.update_flag(flag_id, updates)
    if not updated:
        raise HTTPException(404, detail="Flag not found.")
    bump_eval_cache()
    # Record only what changed — ensure all values are JSON-serialisable
    raw_changes = req.model_dump(exclude_none=True)
    changes = {}
    for k in raw_changes:
        v = getattr(updated, k, None)
        changes[k] = v.model_dump() if hasattr(v, "model_dump") else v
    write_audit("updated", "flag", updated.id, updated.name, changes)
    await manager.broadcast("flag_updated", updated.model_dump())
    return updated


@router.delete("/{flag_id}", status_code=204, summary="Delete a flag")
async def delete_flag(flag_id: str):
    flag = storage.get_flag_by_id(flag_id)
    if not flag:
        raise HTTPException(404, detail="Flag not found.")
    storage.delete_flag(flag_id)
    bump_eval_cache()
    write_audit("deleted", "flag", flag.id, flag.name, {})
    await manager.broadcast("flag_deleted", {"id": flag_id})
