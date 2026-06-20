"""Remote Configs CRUD — ETag conditional responses, eval-cache invalidation, audit logging."""
from __future__ import annotations
import hashlib, json
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from models import RemoteConfig, CreateConfigRequest, UpdateConfigRequest
import storage
from websocket_manager import manager
from routers.evaluate import bump_eval_cache
from audit import write_audit

router = APIRouter(prefix="/configs", tags=["Remote Configs"])


def _etag(data: list) -> str:
    return '"' + hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:24] + '"'


@router.get("/", summary="List all configs")
async def list_configs(request: Request):
    configs = storage.get_all_configs()
    data    = [c.model_dump() for c in configs]
    tag     = _etag(data)
    if request.headers.get("if-none-match") == tag:
        return Response(status_code=304)
    return JSONResponse(content=data, headers={"ETag": tag, "Cache-Control": "no-cache"})


@router.post("/", response_model=RemoteConfig, status_code=201, summary="Create a config")
async def create_config(req: CreateConfigRequest):
    if storage.get_config_by_key(req.key):
        raise HTTPException(409, detail=f"Config key '{req.key}' already exists.")
    config  = RemoteConfig(**req.model_dump())
    created = storage.create_config(config)
    bump_eval_cache()
    write_audit("created", "config", created.id, created.key,
                {"value": created.value, "type": created.type})
    await manager.broadcast("config_created", created.model_dump())
    return created


@router.get("/{config_id}", response_model=RemoteConfig, summary="Get a single config")
async def get_config(config_id: str):
    config = storage.get_config_by_id(config_id)
    if not config:
        raise HTTPException(404, detail="Config not found.")
    return config


@router.patch("/{config_id}", response_model=RemoteConfig, summary="Update a config")
async def update_config(config_id: str, req: UpdateConfigRequest):
    before  = storage.get_config_by_id(config_id)
    if not before:
        raise HTTPException(404, detail="Config not found.")
    updates = req.model_dump(exclude_none=True)
    updated = storage.update_config(config_id, updates)
    if not updated:
        raise HTTPException(404, detail="Config not found.")
    bump_eval_cache()
    changes = {k: getattr(updated, k, None)
               for k in req.model_dump(exclude_none=True)}
    write_audit("updated", "config", updated.id, updated.key, changes)
    await manager.broadcast("config_updated", updated.model_dump())
    return updated


@router.delete("/{config_id}", status_code=204, summary="Delete a config")
async def delete_config(config_id: str):
    config = storage.get_config_by_id(config_id)
    if not config:
        raise HTTPException(404, detail="Config not found.")
    storage.delete_config(config_id)
    bump_eval_cache()
    write_audit("deleted", "config", config.id, config.key, {})
    await manager.broadcast("config_deleted", {"id": config_id})
