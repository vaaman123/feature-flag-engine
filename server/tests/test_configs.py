"""
Tests for the /configs CRUD endpoints.
"""
import pytest


# ── POST /configs/ ────────────────────────────────────────────────────────────

class TestCreateConfig:
    def test_creates_string_config(self, client):
        r = client.post("/configs/", json={
            "key": "welcome_message",
            "value": "Hello!",
            "type": "string",
        })
        assert r.status_code == 201
        body = r.json()
        assert body["key"] == "welcome_message"
        assert body["value"] == "Hello!"
        assert body["type"] == "string"
        assert "id" in body

    def test_creates_number_config(self, client):
        r = client.post("/configs/", json={
            "key": "max_retries", "value": "5", "type": "number",
        })
        assert r.status_code == 201
        assert r.json()["type"] == "number"

    def test_creates_boolean_config(self, client):
        r = client.post("/configs/", json={
            "key": "dark_mode", "value": "true", "type": "boolean",
        })
        assert r.status_code == 201
        assert r.json()["type"] == "boolean"

    def test_defaults_to_string_type(self, client):
        r = client.post("/configs/", json={"key": "plain", "value": "42"})
        assert r.status_code == 201
        assert r.json()["type"] == "string"

    def test_rejects_duplicate_key(self, client):
        client.post("/configs/", json={"key": "dup", "value": "a"})
        r = client.post("/configs/", json={"key": "dup", "value": "b"})
        assert r.status_code == 409

    def test_rejects_missing_key_or_value(self, client):
        assert client.post("/configs/", json={"value": "x"}).status_code == 422
        assert client.post("/configs/", json={"key": "k"}).status_code == 422

    def test_invalid_type_rejected(self, client):
        r = client.post("/configs/", json={
            "key": "bad", "value": "x", "type": "json",
        })
        assert r.status_code == 422


# ── GET /configs/ ────────────────────────────────────────────────────────────

class TestListConfigs:
    def test_empty_list(self, client):
        r = client.get("/configs/")
        assert r.status_code == 200
        assert r.json() == []

    def test_returns_all_configs(self, seeded_client):
        r = seeded_client.get("/configs/")
        assert r.status_code == 200
        assert len(r.json()) == 3


# ── GET /configs/{id} ────────────────────────────────────────────────────────

class TestGetConfig:
    def test_returns_correct_config(self, client):
        created = client.post("/configs/", json={"key": "find", "value": "x"}).json()
        r = client.get(f"/configs/{created['id']}")
        assert r.status_code == 200
        assert r.json()["key"] == "find"

    def test_404_for_unknown_id(self, client):
        assert client.get("/configs/ghost").status_code == 404


# ── PATCH /configs/{id} ──────────────────────────────────────────────────────

class TestUpdateConfig:
    def test_update_value(self, client):
        cfg_id = client.post("/configs/", json={"key": "k", "value": "v1"}).json()["id"]
        r = client.patch(f"/configs/{cfg_id}", json={"value": "v2"})
        assert r.status_code == 200
        assert r.json()["value"] == "v2"

    def test_update_type(self, client):
        cfg_id = client.post("/configs/", json={"key": "t", "value": "5"}).json()["id"]
        r = client.patch(f"/configs/{cfg_id}", json={"type": "number"})
        assert r.status_code == 200
        assert r.json()["type"] == "number"

    def test_update_description(self, client):
        cfg_id = client.post("/configs/", json={"key": "d", "value": "x"}).json()["id"]
        r = client.patch(f"/configs/{cfg_id}", json={"description": "docs"})
        assert r.status_code == 200
        assert r.json()["description"] == "docs"

    def test_404_for_unknown_id(self, client):
        assert client.patch("/configs/ghost", json={"value": "x"}).status_code == 404


# ── DELETE /configs/{id} ─────────────────────────────────────────────────────

class TestDeleteConfig:
    def test_deletes_config(self, client):
        cfg_id = client.post("/configs/", json={"key": "gone", "value": "x"}).json()["id"]
        assert client.delete(f"/configs/{cfg_id}").status_code == 204
        assert client.get(f"/configs/{cfg_id}").status_code == 404

    def test_key_reusable_after_delete(self, client):
        cfg_id = client.post("/configs/", json={"key": "reuse", "value": "1"}).json()["id"]
        client.delete(f"/configs/{cfg_id}")
        r = client.post("/configs/", json={"key": "reuse", "value": "2"})
        assert r.status_code == 201

    def test_404_for_unknown_id(self, client):
        assert client.delete("/configs/ghost").status_code == 404
