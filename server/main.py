"""
Feature Flag & Remote Config Engine — FastAPI server
=====================================================

Optimisation wiring in this file
─────────────────────────────────
  storage.register_mutation_callback(manager.invalidate_initial_state)
    Every flag/config write fires manager.invalidate_initial_state() via
    the storage mutation-callback chain.  The WS initial-state JSON cache
    is therefore always invalidated before the corresponding broadcast
    reaches any listening client.

  GZipMiddleware     — compresses responses > 1 kB
  X-Process-Time     — per-request latency header for observability
  Cache pre-warm     — _ensure_file() on startup loads store into memory
"""
from __future__ import annotations

import json
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

import storage
from routers import configs_router, evaluate_router, flags_router, audit_router
from websocket_manager import manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Pre-warm in-memory cache
    storage._ensure_file()
    # Wire mutation callbacks: storage → WS initial-state cache → eval cache
    storage.register_mutation_callback(manager.invalidate_initial_state)
    yield
    # Drain any coalesced pending write before shutdown
    storage._flush_now()


app = FastAPI(
    title="Feature Flag Engine",
    description="Self-hosted feature flag and remote config engine.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(flags_router)
app.include_router(configs_router)
app.include_router(evaluate_router)
app.include_router(audit_router)


@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start    = time.perf_counter()
    response = await call_next(request)
    elapsed  = time.perf_counter() - start
    response.headers["X-Process-Time"] = f"{elapsed * 1000:.2f}ms"
    return response


@app.get("/", tags=["Health"])
async def root():
    return {
        "status":         "running",
        "version":        "1.0.0",
        "flags_count":    len(storage.get_all_flags()),
        "configs_count":  len(storage.get_all_configs()),
        "ws_connections": manager.connection_count,
    }



@app.get("/dashboard", include_in_schema=False)
async def dashboard():
    import pathlib
    html_path = pathlib.Path(__file__).resolve().parent / "dashboard.html"
    return FileResponse(html_path, media_type="text/html")


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    flags   = storage.get_all_flags()
    configs = storage.get_all_configs()
    # Sends cached JSON — no re-serialisation if nothing changed since last connect
    await ws.send_text(manager.build_initial_state(flags, configs))
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
