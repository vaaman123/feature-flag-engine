"""
WebSocket connection manager.

Optimisations
─────────────
1. Concurrent broadcast via asyncio.gather() — all N sends fire simultaneously;
   total time = slowest single send, not sum of all sends.

2. Initial-state payload cache — the JSON for the "initial_state" message is
   serialised once and reused for every new connection.  Invalidated by the
   mutation callback registered in main.py so it is always fresh after any
   flag or config change.

   Before: every new WS connection called model_dump() on every flag/config
           and json.dumps() on the result  (O(F+C) CPU per connect)
   After:  first connect serialises once; subsequent connects copy a string
           (O(1) per connect after warm-up)
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional

from fastapi import WebSocket


class WebSocketManager:
    def __init__(self) -> None:
        self.active: List[WebSocket] = []
        self._initial_state_cache: Optional[str] = None   # pre-serialised JSON

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        try:
            self.active.remove(ws)
        except ValueError:
            pass

    def invalidate_initial_state(self) -> None:
        """Called after any flag or config mutation."""
        self._initial_state_cache = None

    def build_initial_state(self, flags: list, configs: list) -> str:
        """Return the cached initial_state JSON, building it on first call."""
        if self._initial_state_cache is None:
            self._initial_state_cache = json.dumps({
                "event": "initial_state",
                "data": {
                    "flags":   [f.model_dump() for f in flags],
                    "configs": [c.model_dump() for c in configs],
                },
            })
        return self._initial_state_cache

    async def broadcast(self, event: str, data: Dict[str, Any]) -> None:
        if not self.active:
            return
        payload  = json.dumps({"event": event, "data": data})
        snapshot = list(self.active)
        results  = await asyncio.gather(
            *[ws.send_text(payload) for ws in snapshot],
            return_exceptions=True,
        )
        self.active = [
            ws for ws, result in zip(snapshot, results)
            if not isinstance(result, Exception)
        ]

    @property
    def connection_count(self) -> int:
        return len(self.active)


manager = WebSocketManager()
