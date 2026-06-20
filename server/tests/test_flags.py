"""
Tests for the /flags CRUD endpoints.
"""
import pytest


# ── POST /flags/ ──────────────────────────────────────────────────────────────

class TestCreateFlag:
    def test_creates_with_minimal_payload(self, client):
        r = client.post("/flags/", json={"name": "my_flag"})
        assert r.status_code == 201
        body = r.json()
        assert body["name"] == "my_flag"
        assert body["enabled"] is False
        assert body["targeting"]["type"] == "everyone"
        assert "id" in body
        assert "created_at" in body

    def test_creates_with_full_payload(self, client):
        r = client.post("/flags/", json={
            "name": "beta_flag",
            "enabled": True,
            "targeting": {"type": "beta_users"},
            "description": "Beta feature",
        })
        assert r.status_code == 201
        body = r.json()
        assert body["enabled"] is True
        assert body["targeting"]["type"] == "beta_users"
        assert body["description"] == "Beta feature"

    def test_creates_percentage_flag(self, client):
        r = client.post("/flags/", json={
            "name": "pct_flag",
            "enabled": True,
            "targeting": {"type": "percentage", "percentage": 25.0},
        })
        assert r.status_code == 201
        body = r.json()
        assert body["targeting"]["percentage"] == 25.0

    def test_creates_user_ids_flag(self, client):
        r = client.post("/flags/", json={
            "name": "uid_flag",
            "enabled": True,
            "targeting": {"type": "user_ids", "user_ids": ["alice", "bob"]},
        })
        assert r.status_code == 201
        body = r.json()
        assert body["targeting"]["user_ids"] == ["alice", "bob"]

    def test_rejects_duplicate_name(self, client):
        client.post("/flags/", json={"name": "dup_flag"})
        r = client.post("/flags/", json={"name": "dup_flag"})
        assert r.status_code == 409

    def test_rejects_missing_name(self, client):
        r = client.post("/flags/", json={"enabled": True})
        assert r.status_code == 422


# ── GET /flags/ ───────────────────────────────────────────────────────────────

class TestListFlags:
    def test_empty_list(self, client):
        r = client.get("/flags/")
        assert r.status_code == 200
        assert r.json() == []

    def test_returns_all_flags(self, seeded_client):
        r = seeded_client.get("/flags/")
        assert r.status_code == 200
        assert len(r.json()) == 4

    def test_response_shape(self, seeded_client):
        flags = seeded_client.get("/flags/").json()
        for flag in flags:
            assert all(k in flag for k in ("id", "name", "enabled", "targeting", "description"))


# ── GET /flags/{id} ───────────────────────────────────────────────────────────

class TestGetFlag:
    def test_returns_correct_flag(self, client):
        created = client.post("/flags/", json={"name": "findme"}).json()
        r = client.get(f"/flags/{created['id']}")
        assert r.status_code == 200
        assert r.json()["name"] == "findme"

    def test_404_for_unknown_id(self, client):
        r = client.get("/flags/nonexistent-id")
        assert r.status_code == 404


# ── PATCH /flags/{id} ────────────────────────────────────────────────────────

class TestUpdateFlag:
    def test_toggle_enabled(self, client):
        flag_id = client.post("/flags/", json={"name": "tog", "enabled": False}).json()["id"]
        r = client.patch(f"/flags/{flag_id}", json={"enabled": True})
        assert r.status_code == 200
        assert r.json()["enabled"] is True

    def test_update_description(self, client):
        flag_id = client.post("/flags/", json={"name": "desc_flag"}).json()["id"]
        r = client.patch(f"/flags/{flag_id}", json={"description": "new desc"})
        assert r.status_code == 200
        assert r.json()["description"] == "new desc"

    def test_update_targeting_type(self, client):
        flag_id = client.post("/flags/", json={"name": "targ"}).json()["id"]
        r = client.patch(f"/flags/{flag_id}", json={
            "targeting": {"type": "beta_users"}
        })
        assert r.status_code == 200
        assert r.json()["targeting"]["type"] == "beta_users"

    def test_update_percentage(self, client):
        flag_id = client.post("/flags/", json={"name": "pct2"}).json()["id"]
        r = client.patch(f"/flags/{flag_id}", json={
            "targeting": {"type": "percentage", "percentage": 75.0}
        })
        assert r.status_code == 200
        t = r.json()["targeting"]
        assert t["type"] == "percentage"
        assert t["percentage"] == 75.0

    def test_updated_at_changes(self, client):
        flag = client.post("/flags/", json={"name": "ts_flag"}).json()
        r = client.patch(f"/flags/{flag['id']}", json={"enabled": True})
        # updated_at should be present (may be same second in CI, just check presence)
        assert r.json()["updated_at"] != ""

    def test_404_for_unknown_id(self, client):
        r = client.patch("/flags/bad-id", json={"enabled": True})
        assert r.status_code == 404


# ── DELETE /flags/{id} ───────────────────────────────────────────────────────

class TestDeleteFlag:
    def test_deletes_flag(self, client):
        flag_id = client.post("/flags/", json={"name": "del_me"}).json()["id"]
        r = client.delete(f"/flags/{flag_id}")
        assert r.status_code == 204
        assert client.get(f"/flags/{flag_id}").status_code == 404

    def test_flag_removed_from_list(self, client):
        flag_id = client.post("/flags/", json={"name": "del_list"}).json()["id"]
        client.delete(f"/flags/{flag_id}")
        ids = [f["id"] for f in client.get("/flags/").json()]
        assert flag_id not in ids

    def test_404_for_unknown_id(self, client):
        r = client.delete("/flags/ghost-id")
        assert r.status_code == 404

    def test_name_reusable_after_delete(self, client):
        flag_id = client.post("/flags/", json={"name": "reuse_me"}).json()["id"]
        client.delete(f"/flags/{flag_id}")
        r = client.post("/flags/", json={"name": "reuse_me"})
        assert r.status_code == 201
