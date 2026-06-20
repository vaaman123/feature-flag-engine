"""
Tests for the audit log — write_audit(), get_audit_log(),
and the GET /audit/ endpoint.
"""
import json
import time
import pytest
import audit as audit_store
from pathlib import Path


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolated_audit(tmp_path, monkeypatch):
    """Redirect AUDIT_FILE to a temp directory for full isolation."""
    monkeypatch.setattr(audit_store, "AUDIT_FILE", tmp_path / "audit.jsonl")
    yield
    audit_store.clear_audit_log()


# ══════════════════════════════════════════════════════════════════════════════
# Unit tests for audit storage layer
# ══════════════════════════════════════════════════════════════════════════════

class TestAuditStorage:
    def test_write_creates_file(self, isolated_audit):
        audit_store.write_audit("created", "flag", "id1", "my_flag", {})
        assert audit_store.AUDIT_FILE.exists()

    def test_written_entry_is_readable(self, isolated_audit):
        audit_store.write_audit("created", "flag", "id1", "my_flag",
                                {"enabled": True})
        entries = audit_store.get_audit_log()
        assert len(entries) == 1
        e = entries[0]
        assert e["action"]      == "created"
        assert e["entity_type"] == "flag"
        assert e["entity_id"]   == "id1"
        assert e["entity_name"] == "my_flag"
        assert e["changes"]     == {"enabled": True}

    def test_entry_has_timestamp(self, isolated_audit):
        audit_store.write_audit("updated", "config", "c1", "key", {})
        entry = audit_store.get_audit_log()[0]
        assert "ts" in entry
        assert "T" in entry["ts"]   # ISO-8601 format

    def test_multiple_entries_in_order(self, isolated_audit):
        for i in range(5):
            audit_store.write_audit("created", "flag", f"id{i}", f"flag_{i}", {})
        entries = audit_store.get_audit_log()
        assert len(entries) == 5
        names = [e["entity_name"] for e in entries]
        assert names == [f"flag_{i}" for i in range(5)]

    def test_limit_returns_newest(self, isolated_audit):
        for i in range(10):
            audit_store.write_audit("created", "flag", f"id{i}", f"flag_{i}", {})
        last_3 = audit_store.get_audit_log(limit=3)
        assert len(last_3) == 3
        assert last_3[-1]["entity_name"] == "flag_9"

    def test_empty_returns_empty_list(self, isolated_audit):
        assert audit_store.get_audit_log() == []

    def test_clear_removes_file(self, isolated_audit):
        audit_store.write_audit("created", "flag", "x", "x", {})
        audit_store.clear_audit_log()
        assert not audit_store.AUDIT_FILE.exists()

    def test_append_is_atomic_on_disk(self, isolated_audit):
        """Each entry must be a complete JSON line on disk."""
        for i in range(20):
            audit_store.write_audit("created", "flag", f"id{i}", f"flag_{i}", {})
        with open(audit_store.AUDIT_FILE, "r") as fh:
            lines = [l.strip() for l in fh if l.strip()]
        assert len(lines) == 20
        for line in lines:
            json.loads(line)   # must be valid JSON

    def test_corrupt_line_skipped(self, isolated_audit):
        """A half-written line must not prevent reading the rest."""
        audit_store.write_audit("created", "flag", "id1", "good", {})
        with open(audit_store.AUDIT_FILE, "a") as fh:
            fh.write("NOT_VALID_JSON\n")
        audit_store.write_audit("created", "flag", "id2", "also_good", {})
        entries = audit_store.get_audit_log()
        assert len(entries) == 2
        assert entries[0]["entity_name"] == "good"
        assert entries[1]["entity_name"] == "also_good"

    def test_concurrent_writes_no_interleaving(self, isolated_audit):
        """50 threads each write 10 entries — all 500 must be intact."""
        import threading

        def write_batch(n):
            for _ in range(10):
                audit_store.write_audit("created", "flag", f"id{n}", f"flag_{n}", {})

        threads = [threading.Thread(target=write_batch, args=(i,))
                   for i in range(50)]
        for t in threads: t.start()
        for t in threads: t.join()

        entries = audit_store.get_audit_log(limit=1000)
        assert len(entries) == 500, f"Got {len(entries)} entries, expected 500"
        # Every entry must be valid JSON (no interleaving)
        with open(audit_store.AUDIT_FILE) as fh:
            for line in fh:
                if line.strip():
                    json.loads(line)   # raises if interleaved/corrupt


# ══════════════════════════════════════════════════════════════════════════════
# Integration tests: mutations produce audit entries
# ══════════════════════════════════════════════════════════════════════════════

class TestAuditIntegration:
    def test_flag_create_audited(self, client, isolated_audit):
        client.post("/flags/", json={"name": "audit_flag"})
        entries = audit_store.get_audit_log()
        assert any(
            e["action"] == "created" and e["entity_name"] == "audit_flag"
            for e in entries
        )

    def test_flag_update_audited(self, client, isolated_audit):
        flag_id = client.post("/flags/", json={"name": "upd_flag"}).json()["id"]
        client.patch(f"/flags/{flag_id}", json={"enabled": True})
        entries = audit_store.get_audit_log()
        upd = [e for e in entries if e["action"] == "updated"]
        assert upd, "No 'updated' audit entry found"
        assert upd[0]["entity_name"] == "upd_flag"
        assert upd[0]["changes"].get("enabled") is True

    def test_flag_delete_audited(self, client, isolated_audit):
        flag_id = client.post("/flags/", json={"name": "del_flag"}).json()["id"]
        client.delete(f"/flags/{flag_id}")
        entries = audit_store.get_audit_log()
        assert any(e["action"] == "deleted" and e["entity_name"] == "del_flag"
                   for e in entries)

    def test_config_create_audited(self, client, isolated_audit):
        client.post("/configs/", json={"key": "audit_cfg", "value": "x"})
        entries = audit_store.get_audit_log()
        assert any(e["action"] == "created" and e["entity_name"] == "audit_cfg"
                   for e in entries)

    def test_config_update_audited(self, client, isolated_audit):
        cfg_id = client.post("/configs/", json={"key": "upd_cfg", "value": "old"}).json()["id"]
        client.patch(f"/configs/{cfg_id}", json={"value": "new"})
        entries = audit_store.get_audit_log()
        upd = [e for e in entries if e["action"] == "updated"]
        assert upd
        assert upd[0]["changes"].get("value") == "new"

    def test_config_delete_audited(self, client, isolated_audit):
        cfg_id = client.post("/configs/", json={"key": "del_cfg", "value": "v"}).json()["id"]
        client.delete(f"/configs/{cfg_id}")
        assert any(e["action"] == "deleted" and e["entity_name"] == "del_cfg"
                   for e in audit_store.get_audit_log())


# ══════════════════════════════════════════════════════════════════════════════
# GET /audit/ endpoint tests
# ══════════════════════════════════════════════════════════════════════════════

class TestAuditEndpoint:
    def test_empty_audit_returns_list(self, client, isolated_audit):
        r = client.get("/audit/")
        assert r.status_code == 200
        assert r.json() == []

    def test_returns_entries_after_mutations(self, client, isolated_audit):
        client.post("/flags/", json={"name": "ep_flag"})
        r = client.get("/audit/")
        assert r.status_code == 200
        assert len(r.json()) >= 1

    def test_limit_query_param(self, client, isolated_audit):
        for i in range(10):
            client.post("/flags/", json={"name": f"lim_{i}"})
        r = client.get("/audit/?limit=3")
        assert r.status_code == 200
        assert len(r.json()) == 3

    def test_limit_too_large_rejected(self, client, isolated_audit):
        r = client.get("/audit/?limit=9999")
        assert r.status_code == 422

    def test_limit_zero_rejected(self, client, isolated_audit):
        r = client.get("/audit/?limit=0")
        assert r.status_code == 422

    def test_entry_schema(self, client, isolated_audit):
        client.post("/flags/", json={"name": "schema_flag"})
        entry = client.get("/audit/").json()[0]
        for field in ("ts", "action", "entity_type", "entity_id",
                      "entity_name", "changes"):
            assert field in entry, f"Missing field: {field}"
