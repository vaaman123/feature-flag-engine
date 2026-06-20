"""
Tests for the WebSocket /ws endpoint and the GET / health route.
"""
import json
import pytest
from fastapi.testclient import TestClient


class TestHealthEndpoint:
    def test_returns_running_status(self, client):
        r = client.get("/")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "running"

    def test_counts_match_store(self, seeded_client):
        body = seeded_client.get("/").json()
        assert body["flags_count"]   == 4
        assert body["configs_count"] == 3

    def test_version_field_present(self, client):
        assert "version" in client.get("/").json()


class TestWebSocketEndpoint:
    """
    TestClient supports WebSocket testing via client.websocket_connect().
    The server sends initial_state immediately on connect.
    """

    def test_receives_initial_state_on_connect(self, seeded_client):
        with seeded_client.websocket_connect("/ws") as ws:
            raw = ws.receive_text()
            msg = json.loads(raw)
            assert msg["event"] == "initial_state"
            assert "flags"   in msg["data"]
            assert "configs" in msg["data"]

    def test_initial_state_contains_all_seeded_flags(self, seeded_client):
        with seeded_client.websocket_connect("/ws") as ws:
            msg = json.loads(ws.receive_text())
            names = [f["name"] for f in msg["data"]["flags"]]
            assert "feature_everyone" in names
            assert "feature_beta"     in names

    def test_initial_state_contains_all_seeded_configs(self, seeded_client):
        with seeded_client.websocket_connect("/ws") as ws:
            msg = json.loads(ws.receive_text())
            keys = [c["key"] for c in msg["data"]["configs"]]
            assert "welcome_message" in keys
            assert "max_retries"     in keys

    def test_flag_toggle_broadcasts_event(self, seeded_client):
        """
        Connect a WS client, toggle a flag via REST, then verify the WS
        client received a flag_updated event.
        """
        # Get a flag id to toggle
        flag_id = seeded_client.get("/flags/").json()[0]["id"]

        with seeded_client.websocket_connect("/ws") as ws:
            # Discard the initial_state message
            ws.receive_text()

            # Mutate the flag via REST
            seeded_client.patch(f"/flags/{flag_id}", json={"enabled": False})

            # The WS client should receive a flag_updated broadcast
            raw = ws.receive_text()
            msg = json.loads(raw)
            assert msg["event"] == "flag_updated"
            assert msg["data"]["id"] == flag_id

    def test_flag_create_broadcasts_event(self, client):
        with client.websocket_connect("/ws") as ws:
            ws.receive_text()  # discard initial_state
            client.post("/flags/", json={"name": "ws_flag", "enabled": True})
            msg = json.loads(ws.receive_text())
            assert msg["event"] == "flag_created"
            assert msg["data"]["name"] == "ws_flag"

    def test_flag_delete_broadcasts_event(self, client):
        flag_id = client.post("/flags/", json={"name": "bye_flag"}).json()["id"]
        with client.websocket_connect("/ws") as ws:
            ws.receive_text()  # initial_state
            client.delete(f"/flags/{flag_id}")
            msg = json.loads(ws.receive_text())
            assert msg["event"] == "flag_deleted"
            assert msg["data"]["id"] == flag_id

    def test_config_update_broadcasts_event(self, client):
        cfg_id = client.post("/configs/", json={
            "key": "ws_cfg", "value": "old"
        }).json()["id"]
        with client.websocket_connect("/ws") as ws:
            ws.receive_text()  # initial_state
            client.patch(f"/configs/{cfg_id}", json={"value": "new"})
            msg = json.loads(ws.receive_text())
            assert msg["event"] == "config_updated"
            assert msg["data"]["value"] == "new"

    def test_empty_store_initial_state(self, client):
        with client.websocket_connect("/ws") as ws:
            msg = json.loads(ws.receive_text())
            assert msg["event"] == "initial_state"
            assert msg["data"]["flags"]   == []
            assert msg["data"]["configs"] == []
