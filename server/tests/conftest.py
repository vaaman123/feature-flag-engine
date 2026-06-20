"""
Shared pytest fixtures.

Run from server/:
    pytest tests/ -v
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    """
    Full isolation per test:
      - Temp DATA_DIR / DATA_FILE so tests never touch the real store
      - storage._reset() wipes indexes + cancels any pending coalesce timer
      - _reset_eval_cache() wipes the LRU result cache
      - _clear_bucket_memo() wipes the FNV-1a bucket memo
      - storage._flush_now() at teardown drains any pending write BEFORE
        monkeypatch restores the original DATA_FILE path (prevents
        cross-test file contamination)
    """
    import storage
    import audit as audit_mod
    from routers.evaluate import _reset_eval_cache, _clear_bucket_memo

    monkeypatch.setattr(storage, "DATA_DIR",  tmp_path)
    monkeypatch.setattr(storage, "DATA_FILE", tmp_path / "store.json")
    monkeypatch.setattr(audit_mod, "AUDIT_FILE", tmp_path / "audit.jsonl")
    storage._reset()
    _reset_eval_cache()
    _clear_bucket_memo()
    storage._ensure_file()
    yield
    storage._flush_now()   # drain coalesced writes before monkeypatch restores


@pytest.fixture
def client(isolated_store):
    from main import app
    from fastapi.testclient import TestClient
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture
def seeded_client(client):
    client.post("/flags/", json={
        "name": "feature_everyone", "enabled": True,
        "targeting": {"type": "everyone"}, "description": "Always on",
    })
    client.post("/flags/", json={
        "name": "feature_beta", "enabled": True,
        "targeting": {"type": "beta_users"},
    })
    client.post("/flags/", json={
        "name": "feature_pct", "enabled": True,
        "targeting": {"type": "percentage", "percentage": 50},
    })
    client.post("/flags/", json={
        "name": "feature_disabled", "enabled": False,
        "targeting": {"type": "everyone"},
    })
    client.post("/configs/", json={"key": "welcome_message", "value": "Hello!", "type": "string"})
    client.post("/configs/", json={"key": "max_retries",     "value": "3",      "type": "number"})
    client.post("/configs/", json={"key": "maintenance_mode","value": "false",  "type": "boolean"})
    return client
