"""
Evaluation router.

Optimisations in this file
──────────────────────────

1. Deterministic bucket memoisation — the real hash speedup.
   The bucket for (user_id, flag_name) is constant once computed — the
   same user always lands in the same bucket regardless of the percentage
   value.  We cache bucket results in a bounded dict so repeated calls for
   the same user skip hashing entirely.
   Bounded at _BUCKET_MEMO_MAX entries; beyond that new lookups always
   compute fresh (no eviction overhead, just a size guard).

3. Generation-keyed LRU result cache (unchanged from previous round).
   Full evaluate results are cached per (gen, user_id, is_beta, flags_key).

Layer interaction
─────────────────
  Cache hit  → O(1) dict lookup (no hashing, no flag iteration)
  Cache miss → O(F) flag loop; % flags use bucket memo (O(1) after first)
  Mutation   → bump_eval_cache() clears the LRU; bucket memo is permanent
               (buckets are content-free — they don't encode flag state)
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Optional

from fastapi import APIRouter
from models import EvaluateRequest, EvaluateResponse, FeatureFlag
import storage

router = APIRouter(prefix="/evaluate", tags=["Evaluation"])

import hashlib

# ── Deterministic bucket memo ─────────────────────────────────────────────────
# hashlib.md5 is a C extension — fastest available hash in CPython.
# Bucket is purely a function of (user_id, flag_name) — it never changes.
# Memoising it means each unique (user, flag) pair is hashed exactly once;
# repeat evaluate calls for the same user skip hashing entirely.
_BUCKET_MEMO_MAX = 50_000   # ~3.2 MB at ~64 bytes/entry
_bucket_memo: dict[tuple[str, str], int] = {}


def _compute_bucket(user_id: str, flag_name: str) -> int:
    raw = f"{user_id}:{flag_name}".encode()
    return (int(hashlib.md5(raw).hexdigest(), 16) % 100) + 1


def _get_bucket(user_id: str, flag_name: str) -> int:
    key = (user_id, flag_name)
    val = _bucket_memo.get(key)
    if val is None:
        val = _compute_bucket(user_id, flag_name)
        if len(_bucket_memo) < _BUCKET_MEMO_MAX:
            _bucket_memo[key] = val
    return val


def _clear_bucket_memo() -> None:
    """Exposed for tests that need a clean slate."""
    _bucket_memo.clear()


# ── Generation-keyed LRU result cache ─────────────────────────────────────────
_CACHE_MAX_SIZE = 4_096

_cache_lock = threading.Lock()
_eval_gen:   int = 0
_eval_cache: OrderedDict = OrderedDict()


def _cache_key(gen: int, user_id: str, is_beta: bool,
               flag_names: Optional[tuple]) -> tuple:
    return (gen, user_id, is_beta, flag_names)


def bump_eval_cache() -> None:
    global _eval_gen
    with _cache_lock:
        _eval_gen += 1
        _eval_cache.clear()


def _cache_get(key: tuple) -> Optional[EvaluateResponse]:
    with _cache_lock:
        if key in _eval_cache:
            _eval_cache.move_to_end(key)
            return _eval_cache[key]
    return None


def _cache_set(key: tuple, value: EvaluateResponse) -> None:
    with _cache_lock:
        _eval_cache[key] = value
        _eval_cache.move_to_end(key)
        if len(_eval_cache) > _CACHE_MAX_SIZE:
            _eval_cache.popitem(last=False)


def _reset_eval_cache() -> None:
    global _eval_gen
    with _cache_lock:
        _eval_gen = 0
        _eval_cache.clear()


# ── Targeting logic ───────────────────────────────────────────────────────────

def evaluate_flag(flag: FeatureFlag, user_id: str, is_beta_user: bool) -> bool:
    if not flag.enabled:
        return False
    t = flag.targeting
    match t.type:
        case "everyone":
            return True
        case "beta_users":
            return is_beta_user
        case "percentage":
            return _get_bucket(user_id, flag.name) <= (t.percentage or 0.0)
        case "user_ids":
            return user_id in t.user_ids
        case _:
            return False


def parse_config_value(value: str, config_type: str) -> object:
    match config_type:
        case "number":
            try:
                return float(value) if "." in value else int(value)
            except ValueError:
                return value
        case "boolean":
            return value.strip().lower() in ("true", "1", "yes", "on")
        case _:
            return value


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post("/", response_model=EvaluateResponse, summary="Evaluate flags for a user")
async def evaluate(req: EvaluateRequest):
    flag_names_key = tuple(sorted(req.flag_names)) if req.flag_names else None

    with _cache_lock:
        gen = _eval_gen
    key    = _cache_key(gen, req.user_id, req.is_beta_user, flag_names_key)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    flags   = storage.get_all_flags()
    configs = storage.get_all_configs()

    if req.flag_names is not None:
        flags = [f for f in flags if f.name in req.flag_names]

    result = EvaluateResponse(
        user_id=req.user_id,
        flags={
            f.name: evaluate_flag(f, req.user_id, req.is_beta_user)
            for f in flags
        },
        configs={
            c.key: parse_config_value(c.value, c.type)
            for c in configs
        },
    )
    _cache_set(key, result)
    return result
