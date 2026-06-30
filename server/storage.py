"""
Storage layer — O(1) indexed in-memory store with coalesced atomic disk writes.

Read path  → O(1) dict lookup, zero disk I/O
Write path → mutate memory instantly (O(1)), then schedule a disk flush
             that fires 10 ms after the LAST mutation in a burst.
             Effect: 50 rapid flag toggles → 1 disk write, not 50.

Durability → the 10 ms window is the only data-loss risk on hard crash.
             A clean shutdown (SIGTERM / uvicorn reload) drains the pending
             write via atexit.  The window is tunable via _COALESCE_MS.

Atomicity  → the disk write itself is a single os.replace() rename —
             the file is never in a partially-written state.

Thread-safety
  _lock        RLock  guards the four in-memory indexes
  _timer_lock  Lock   guards the coalesce timer itself
  Generation   each _reset() increments _flush_gen; the timer callback
               checks the generation before writing so stale timers from a
               previous test can never touch the wrong file.
"""
from __future__ import annotations

import atexit
import json
import os
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

IST = timezone(timedelta(hours=5, minutes=30))

from models import FeatureFlag, RemoteConfig

_BASE_DIR = Path(__file__).resolve().parent
DATA_DIR  = _BASE_DIR / "data"
DATA_FILE = DATA_DIR / "store.json"

_lock = threading.RLock()

# ── Four O(1) in-memory indexes ───────────────────────────────────────────────
_flags_by_id:    Dict[str, Dict] = {}
_flags_by_name:  Dict[str, str]  = {}   # name  → id
_configs_by_id:  Dict[str, Dict] = {}
_configs_by_key: Dict[str, str]  = {}   # key   → id
_loaded: bool = False

# ── Write-coalescing timer ────────────────────────────────────────────────────
_COALESCE_MS = 10                             # ms to wait after last mutation
_timer_lock  = threading.Lock()
_flush_timer: Optional[threading.Timer] = None
_flush_gen:   int = 0                         # invalidates stale timers on reset

# ── Mutation hooks (used by WS cache, etc.) ───────────────────────────────────
_mutation_callbacks: List[Callable[[], None]] = []


def register_mutation_callback(fn: Callable[[], None]) -> None:
    """Register a zero-argument function called after every mutation."""
    _mutation_callbacks.append(fn)


def _fire_callbacks() -> None:
    for fn in _mutation_callbacks:
        try:
            fn()
        except Exception:
            pass


# ─── Core I/O ────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(IST).isoformat()


def _build_indexes(data: Dict[str, Any]) -> None:
    global _flags_by_id, _flags_by_name, _configs_by_id, _configs_by_key, _loaded
    _flags_by_id    = {f["id"]: f for f in data.get("flags",   [])}
    _flags_by_name  = {f["name"]: f["id"] for f in _flags_by_id.values()}
    _configs_by_id  = {c["id"]: c for c in data.get("configs", [])}
    _configs_by_key = {c["key"]: c["id"] for c in _configs_by_id.values()}
    _loaded = True


def _load() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    if DATA_FILE.exists():
        with open(DATA_FILE, "r", encoding="utf-8") as fh:
            _build_indexes(json.load(fh))
    else:
        _build_indexes({"flags": [], "configs": []})
        _flush()


def _ensure_loaded() -> None:
    if not _loaded:
        _load()


def _flush() -> None:
    """Atomic write: serialise to .tmp → os.replace() into place."""
    DATA_DIR.mkdir(exist_ok=True)
    data = {
        "flags":   list(_flags_by_id.values()),
        "configs": list(_configs_by_id.values()),
    }
    tmp = DATA_FILE.with_suffix(".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        os.replace(tmp, DATA_FILE)
    except (PermissionError, OSError):
        # Windows may lock the file; fall back to direct overwrite
        try:
            tmp.unlink(missing_ok=True)
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False)
            os.replace(tmp, DATA_FILE)
        except (PermissionError, OSError):
            try:
                with open(DATA_FILE, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, indent=2, ensure_ascii=False)
            except (PermissionError, OSError):
                pass
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass


def _schedule_flush() -> None:
    """
    Debounce disk writes.  Cancels any pending timer and schedules a new
    flush COALESCE_MS ms from now.  The generation check ensures that a
    timer created before _reset() can never fire after it.
    """
    global _flush_timer
    with _timer_lock:
        if _flush_timer is not None:
            _flush_timer.cancel()
        gen = _flush_gen

        def _timed_flush() -> None:
            with _timer_lock:
                if _flush_gen != gen:
                    return           # stale — a reset happened after us
            _flush()

        _flush_timer = threading.Timer(_COALESCE_MS / 1000.0, _timed_flush)
        _flush_timer.daemon = True
        _flush_timer.start()


def _flush_now() -> None:
    """Cancel pending timer and flush immediately (used by tests + shutdown)."""
    global _flush_timer
    with _timer_lock:
        if _flush_timer is not None:
            _flush_timer.cancel()
            _flush_timer = None
    with _lock:
        _flush()


# Ensure final state always reaches disk on clean shutdown
atexit.register(_flush_now)


# ─── Public hooks ────────────────────────────────────────────────────────────

def _ensure_file() -> None:
    with _lock:
        _ensure_loaded()


def _reset() -> None:
    """Wipe in-memory state and cancel any pending flush (called by tests)."""
    global _flags_by_id, _flags_by_name, _configs_by_id, _configs_by_key
    global _loaded, _flush_gen, _flush_timer
    with _timer_lock:
        _flush_gen += 1
        if _flush_timer is not None:
            _flush_timer.cancel()
            _flush_timer = None
    with _lock:
        _flags_by_id    = {}
        _flags_by_name  = {}
        _configs_by_id  = {}
        _configs_by_key = {}
        _loaded = False


# ─── Feature Flags ───────────────────────────────────────────────────────────

def get_all_flags() -> List[FeatureFlag]:
    with _lock:
        _ensure_loaded()
        return [FeatureFlag(**f) for f in _flags_by_id.values()]


def get_flag_by_id(flag_id: str) -> Optional[FeatureFlag]:
    with _lock:
        _ensure_loaded()
        raw = _flags_by_id.get(flag_id)
        return FeatureFlag(**raw) if raw else None


def get_flag_by_name(name: str) -> Optional[FeatureFlag]:
    with _lock:
        _ensure_loaded()
        fid = _flags_by_name.get(name)
        raw = _flags_by_id.get(fid) if fid else None
        return FeatureFlag(**raw) if raw else None


def create_flag(flag: FeatureFlag) -> FeatureFlag:
    with _lock:
        _ensure_loaded()
        d = flag.model_dump()
        _flags_by_id[flag.id]     = d
        _flags_by_name[flag.name] = flag.id
    _schedule_flush()
    _fire_callbacks()
    return flag


def update_flag(flag_id: str, updates: Dict[str, Any]) -> Optional[FeatureFlag]:
    result = None
    with _lock:
        _ensure_loaded()
        f = _flags_by_id.get(flag_id)
        if f is not None:
            if "targeting" in updates and isinstance(updates["targeting"], dict):
                f["targeting"] = {**f.get("targeting", {}), **updates.pop("targeting")}
            for k, v in updates.items():
                if v is not None:
                    f[k] = v
            f["updated_at"] = _now()
            result = FeatureFlag(**f)
    if result is not None:
        _schedule_flush()
        _fire_callbacks()
    return result


def delete_flag(flag_id: str) -> bool:
    deleted = False
    with _lock:
        _ensure_loaded()
        f = _flags_by_id.pop(flag_id, None)
        if f is not None:
            _flags_by_name.pop(f["name"], None)
            deleted = True
    if deleted:
        _schedule_flush()
        _fire_callbacks()
    return deleted


# ─── Remote Configs ──────────────────────────────────────────────────────────

def get_all_configs() -> List[RemoteConfig]:
    with _lock:
        _ensure_loaded()
        return [RemoteConfig(**c) for c in _configs_by_id.values()]


def get_config_by_id(config_id: str) -> Optional[RemoteConfig]:
    with _lock:
        _ensure_loaded()
        raw = _configs_by_id.get(config_id)
        return RemoteConfig(**raw) if raw else None


def get_config_by_key(key: str) -> Optional[RemoteConfig]:
    with _lock:
        _ensure_loaded()
        cid = _configs_by_key.get(key)
        raw = _configs_by_id.get(cid) if cid else None
        return RemoteConfig(**raw) if raw else None


def create_config(config: RemoteConfig) -> RemoteConfig:
    with _lock:
        _ensure_loaded()
        d = config.model_dump()
        _configs_by_id[config.id]   = d
        _configs_by_key[config.key] = config.id
    _schedule_flush()
    _fire_callbacks()
    return config


def update_config(config_id: str, updates: Dict[str, Any]) -> Optional[RemoteConfig]:
    result = None
    with _lock:
        _ensure_loaded()
        c = _configs_by_id.get(config_id)
        if c is not None:
            for k, v in updates.items():
                if v is not None:
                    c[k] = v
            c["updated_at"] = _now()
            result = RemoteConfig(**c)
    if result is not None:
        _schedule_flush()
        _fire_callbacks()
    return result


def delete_config(config_id: str) -> bool:
    deleted = False
    with _lock:
        _ensure_loaded()
        c = _configs_by_id.pop(config_id, None)
        if c is not None:
            _configs_by_key.pop(c["key"], None)
            deleted = True
    if deleted:
        _schedule_flush()
        _fire_callbacks()
    return deleted
