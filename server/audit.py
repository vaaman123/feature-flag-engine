"""
Audit log — append-only JSON Lines storage.

Every flag and config mutation writes one JSON object per line to
data/audit.jsonl.  JSON Lines means:
  • Appends are a single fwrite — O(1), no file rewrite
  • The file is grep/jq-friendly:  tail -f data/audit.jsonl | jq .
  • A partial last line (crash mid-write) is silently skipped on read
  • Compatible with log-rotation tooling

Thread-safety: a module-level Lock serialises concurrent appends.
               Reads are unlocked (appends are atomic at the OS level
               for lines shorter than PIPE_BUF, which ours always are).
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List

IST = timezone(timedelta(hours=5, minutes=30))

_BASE_DIR   = Path(__file__).resolve().parent
AUDIT_FILE  = _BASE_DIR / "data/audit.jsonl"
_audit_lock = threading.Lock()


def write_audit(
    action:      str,   # "created" | "updated" | "deleted"
    entity_type: str,   # "flag"    | "config"
    entity_id:   str,
    entity_name: str,
    changes:     Dict[str, Any],
) -> None:
    entry = {
        "ts":          datetime.now(IST).isoformat(),
        "action":      action,
        "entity_type": entity_type,
        "entity_id":   entity_id,
        "entity_name": entity_name,
        "changes":     changes,
    }
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    with _audit_lock:
        AUDIT_FILE.parent.mkdir(exist_ok=True)
        with open(AUDIT_FILE, "a", encoding="utf-8") as fh:
            fh.write(line)


def get_audit_log(limit: int = 100) -> List[Dict[str, Any]]:
    """Return the last *limit* audit entries, newest last."""
    if not AUDIT_FILE.exists():
        return []
    entries: List[Dict] = []
    try:
        with open(AUDIT_FILE, "r", encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    entries.append(json.loads(raw))
                except json.JSONDecodeError:
                    pass   # skip corrupt lines gracefully
    except FileNotFoundError:
        return []
    return entries[-limit:]


def clear_audit_log() -> None:
    """Wipe the file — used only by tests."""
    with _audit_lock:
        if AUDIT_FILE.exists():
            AUDIT_FILE.unlink()
