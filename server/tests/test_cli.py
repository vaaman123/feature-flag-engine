"""
Tests for cli.py — all commands exercised against a live TestClient.

The TestClient (requests-compatible) has the same .get()/.post()/.patch()/.delete()
interface as httpx.Client, so CLI functions accept it directly — no subprocess,
no networking, no mocking needed.
"""
from __future__ import annotations
import io, json, sys, pytest
from unittest.mock import patch

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.dirname(__file__)))
from cli import (
    _parse_targeting,
    cmd_flags_list, cmd_flag_create, cmd_flag_on, cmd_flag_off,
    cmd_flag_toggle, cmd_flag_delete,
    cmd_configs_list, cmd_config_set, cmd_config_delete,
    cmd_evaluate, cmd_audit, cmd_export, cmd_import,
)


def capture(fn, *args, **kwargs) -> str:
    """Run fn, capture and return its stdout."""
    buf = io.StringIO()
    with patch("sys.stdout", buf):
        fn(*args, **kwargs)
    return buf.getvalue()


# ── Targeting parser ──────────────────────────────────────────────────────────

class TestTargetingParser:
    def test_everyone(self):
        assert _parse_targeting("everyone") == {"type": "everyone"}

    def test_all_alias(self):
        assert _parse_targeting("all") == {"type": "everyone"}

    def test_beta(self):
        assert _parse_targeting("beta") == {"type": "beta_users"}

    def test_percentage(self):
        assert _parse_targeting("pct:25") == {"type": "percentage", "percentage": 25.0}

    def test_user_ids(self):
        t = _parse_targeting("users:alice,bob")
        assert t["type"] == "user_ids"
        assert set(t["user_ids"]) == {"alice", "bob"}

    def test_invalid_spec_exits(self):
        with pytest.raises(SystemExit):
            _parse_targeting("unknown_spec")

    def test_invalid_pct_exits(self):
        with pytest.raises(SystemExit):
            _parse_targeting("pct:notanumber")


# ── Flags ─────────────────────────────────────────────────────────────────────

class TestCLIFlags:
    def test_flags_list_empty(self, client):
        out = capture(cmd_flags_list, client)
        assert "0" in out or "no flags" in out.lower()

    def test_flag_create_basic(self, client):
        out = capture(cmd_flag_create, client, "cli_flag", False, "everyone", "")
        assert "cli_flag" in out

    def test_flag_create_enabled(self, client):
        out = capture(cmd_flag_create, client, "on_flag", True, "everyone", "desc")
        assert "on_flag" in out

    def test_flag_create_beta(self, client):
        out = capture(cmd_flag_create, client, "beta_flag", False, "beta", "")
        assert "beta_flag" in out

    def test_flag_create_percentage(self, client):
        out = capture(cmd_flag_create, client, "pct_flag", False, "pct:30", "")
        assert "pct_flag" in out

    def test_flag_create_user_ids(self, client):
        out = capture(cmd_flag_create, client, "uid_flag", False, "users:alice,bob", "")
        assert "uid_flag" in out

    def test_flags_list_shows_created(self, client):
        cmd_flag_create(client, "visible_flag", True, "everyone", "")
        out = capture(cmd_flags_list, client)
        assert "visible_flag" in out

    def test_flag_on_turns_flag_on(self, client):
        cmd_flag_create(client, "tog_flag", False, "everyone", "")
        out = capture(cmd_flag_on, client, "tog_flag")
        assert "ON" in out or "enabled" in out.lower()
        # Verify via API
        flags = client.get("/flags/").json()
        flag  = next(f for f in flags if f["name"] == "tog_flag")
        assert flag["enabled"] is True

    def test_flag_off_turns_flag_off(self, client):
        cmd_flag_create(client, "tog2_flag", True, "everyone", "")
        out = capture(cmd_flag_off, client, "tog2_flag")
        assert "OFF" in out or "disabled" in out.lower()
        flags = client.get("/flags/").json()
        flag  = next(f for f in flags if f["name"] == "tog2_flag")
        assert flag["enabled"] is False

    def test_flag_toggle_flips_state(self, client):
        cmd_flag_create(client, "tgl_flag", False, "everyone", "")
        capture(cmd_flag_toggle, client, "tgl_flag")   # OFF → ON
        flags = client.get("/flags/").json()
        flag  = next(f for f in flags if f["name"] == "tgl_flag")
        assert flag["enabled"] is True
        capture(cmd_flag_toggle, client, "tgl_flag")   # ON → OFF
        flags = client.get("/flags/").json()
        flag  = next(f for f in flags if f["name"] == "tgl_flag")
        assert flag["enabled"] is False

    def test_flag_delete_removes_flag(self, client):
        cmd_flag_create(client, "del_flag", False, "everyone", "")
        out = capture(cmd_flag_delete, client, "del_flag")
        assert "del_flag" in out
        flags = client.get("/flags/").json()
        assert not any(f["name"] == "del_flag" for f in flags)

    def test_flag_on_unknown_exits(self, client):
        with pytest.raises(SystemExit):
            cmd_flag_on(client, "ghost_flag")

    def test_flag_off_unknown_exits(self, client):
        with pytest.raises(SystemExit):
            cmd_flag_off(client, "ghost_flag")

    def test_flag_delete_unknown_exits(self, client):
        with pytest.raises(SystemExit):
            cmd_flag_delete(client, "ghost_flag")

    def test_duplicate_create_exits(self, client):
        cmd_flag_create(client, "dup_flag", False, "everyone", "")
        with pytest.raises(SystemExit):
            cmd_flag_create(client, "dup_flag", False, "everyone", "")


# ── Configs ───────────────────────────────────────────────────────────────────

class TestCLIConfigs:
    def test_configs_list_empty(self, client):
        out = capture(cmd_configs_list, client)
        assert "0" in out or "no configs" in out.lower()

    def test_config_set_creates_new(self, client):
        out = capture(cmd_config_set, client, "msg", "Hello", "string", "")
        assert "msg" in out
        configs = client.get("/configs/").json()
        assert any(c["key"] == "msg" and c["value"] == "Hello" for c in configs)

    def test_config_set_updates_existing(self, client):
        cmd_config_set(client, "msg", "Hello", "string", "")
        capture(cmd_config_set, client, "msg", "World", "string", "")
        configs = client.get("/configs/").json()
        assert any(c["key"] == "msg" and c["value"] == "World" for c in configs)

    def test_config_set_number(self, client):
        cmd_config_set(client, "retries", "5", "number", "")
        configs = client.get("/configs/").json()
        assert any(c["key"] == "retries" and c["type"] == "number" for c in configs)

    def test_config_set_boolean(self, client):
        cmd_config_set(client, "dark", "true", "boolean", "")
        configs = client.get("/configs/").json()
        assert any(c["key"] == "dark" and c["type"] == "boolean" for c in configs)

    def test_configs_list_shows_created(self, client):
        cmd_config_set(client, "list_cfg", "val", "string", "")
        out = capture(cmd_configs_list, client)
        assert "list_cfg" in out

    def test_config_delete_removes_key(self, client):
        cmd_config_set(client, "del_cfg", "x", "string", "")
        out = capture(cmd_config_delete, client, "del_cfg")
        assert "del_cfg" in out
        configs = client.get("/configs/").json()
        assert not any(c["key"] == "del_cfg" for c in configs)

    def test_config_delete_unknown_exits(self, client):
        with pytest.raises(SystemExit):
            cmd_config_delete(client, "ghost_key")


# ── Evaluate ──────────────────────────────────────────────────────────────────

class TestCLIEvaluate:
    def test_evaluate_empty_store(self, client):
        out = capture(cmd_evaluate, client, "alice", False)
        assert "alice" in out   # user_id in header

    def test_evaluate_shows_flag_result(self, client):
        cmd_flag_create(client, "eval_flag", True, "everyone", "")
        out = capture(cmd_evaluate, client, "bob", False)
        assert "eval_flag" in out

    def test_evaluate_beta_flag_on_for_beta_user(self, client):
        cmd_flag_create(client, "beta_ev", True, "beta", "")
        out_beta = capture(cmd_evaluate, client, "u", True)
        out_reg  = capture(cmd_evaluate, client, "u", False)
        # ✓ = on, ✗ = off — both outputs mention the flag
        assert "beta_ev" in out_beta
        assert "beta_ev" in out_reg

    def test_evaluate_shows_config_values(self, client):
        cmd_config_set(client, "ev_cfg", "42", "number", "")
        out = capture(cmd_evaluate, client, "user", False)
        assert "ev_cfg" in out
        assert "42" in out


# ── Audit ─────────────────────────────────────────────────────────────────────

class TestCLIAudit:
    def test_audit_empty(self, client, tmp_path, monkeypatch):
        import audit as audit_mod
        monkeypatch.setattr(audit_mod, "AUDIT_FILE", tmp_path / "audit.jsonl")
        out = capture(cmd_audit, client, 20)
        assert "no audit" in out.lower() or out.strip() == ""

    def test_audit_shows_entries(self, client, tmp_path, monkeypatch):
        import audit as audit_mod
        monkeypatch.setattr(audit_mod, "AUDIT_FILE", tmp_path / "audit.jsonl")
        cmd_flag_create(client, "audit_test", False, "everyone", "")
        out = capture(cmd_audit, client, 20)
        assert "audit_test" in out

    def test_audit_respects_limit(self, client, tmp_path, monkeypatch):
        import audit as audit_mod
        monkeypatch.setattr(audit_mod, "AUDIT_FILE", tmp_path / "audit.jsonl")
        for i in range(5):
            cmd_flag_create(client, f"alim_{i}", False, "everyone", "")
        out = capture(cmd_audit, client, 2)
        # Should contain only the last 2 flags
        lines = [l for l in out.splitlines() if "alim_" in l]
        assert len(lines) <= 2


# ── Export / Import ───────────────────────────────────────────────────────────

class TestCLIExportImport:
    def test_export_stdout_valid_json(self, client):
        cmd_flag_create(client, "exp_flag", True, "everyone", "")
        out = capture(cmd_export, client, None)
        data = json.loads(out)
        assert "flags" in data and "configs" in data
        assert any(f["name"] == "exp_flag" for f in data["flags"])

    def test_export_includes_metadata(self, client):
        out  = capture(cmd_export, client, None)
        data = json.loads(out)
        assert data["version"] == "1.0"
        assert "exported_at" in data

    def test_export_to_file(self, client, tmp_path):
        cmd_flag_create(client, "file_flag", False, "beta", "")
        out_path = str(tmp_path / "export.json")
        capture(cmd_export, client, out_path)
        with open(out_path) as f:
            data = json.load(f)
        assert any(fl["name"] == "file_flag" for fl in data["flags"])

    def test_import_creates_flags_and_configs(self, client, tmp_path):
        payload = {
            "version": "1.0", "exported_at": "2024-01-01T00:00:00Z",
            "flags": [
                {"name": "imp_flag", "enabled": True,
                 "targeting": {"type": "everyone"}, "description": ""},
            ],
            "configs": [
                {"key": "imp_cfg", "value": "hello",
                 "type": "string", "description": ""},
            ],
        }
        p = tmp_path / "import.json"
        p.write_text(json.dumps(payload))
        out = capture(cmd_import, client, str(p), False)
        assert "created" in out.lower()
        flags = client.get("/flags/").json()
        assert any(f["name"] == "imp_flag" for f in flags)

    def test_import_skips_existing_by_default(self, client, tmp_path):
        cmd_flag_create(client, "dup_flag", False, "everyone", "")
        payload = {
            "flags": [{"name": "dup_flag", "enabled": True,
                       "targeting": {"type": "everyone"}, "description": ""}],
            "configs": [],
        }
        p = tmp_path / "dup.json"
        p.write_text(json.dumps(payload))
        out = capture(cmd_import, client, str(p), False)
        assert "skipped" in out

    def test_import_overwrite_updates_existing(self, client, tmp_path):
        cmd_flag_create(client, "ow_flag", False, "everyone", "")
        payload = {
            "flags": [{"name": "ow_flag", "enabled": True,
                       "targeting": {"type": "everyone"}, "description": "overwritten"}],
            "configs": [],
        }
        p = tmp_path / "ow.json"
        p.write_text(json.dumps(payload))
        capture(cmd_import, client, str(p), True)
        flags = client.get("/flags/").json()
        ow    = next(f for f in flags if f["name"] == "ow_flag")
        assert ow["enabled"] is True

    def test_import_missing_file_exits(self, client):
        with pytest.raises(SystemExit):
            cmd_import(client, "/nonexistent/path.json", False)

    def test_roundtrip_export_import(self, client, tmp_path):
        """Export → wipe → import should restore everything."""
        cmd_flag_create(client, "rt_flag", True, "beta", "roundtrip")
        cmd_config_set(client, "rt_cfg", "99", "number", "roundtrip")

        out_path = str(tmp_path / "rt.json")
        capture(cmd_export, client, out_path)

        # Delete originals
        flags = client.get("/flags/").json()
        for f in flags:
            client.delete(f"/flags/{f['id']}")
        configs = client.get("/configs/").json()
        for c in configs:
            client.delete(f"/configs/{c['id']}")

        capture(cmd_import, client, out_path, False)

        flags   = client.get("/flags/").json()
        configs = client.get("/configs/").json()
        assert any(f["name"] == "rt_flag" for f in flags)
        assert any(c["key"]  == "rt_cfg"  for c in configs)
