"""
Tests for the /evaluate endpoint and all four targeting rules.

Covers
─────
  • everyone        → ON for all users when flag is enabled
  • beta_users      → ON only if is_beta_user=True
  • percentage      → deterministic bucket assignment via FNV-1a hash
  • user_ids        → ON only for explicitly listed user IDs
  • disabled flag   → always OFF regardless of targeting
  • config types    → string / number / boolean casting
"""
import pytest
from routers.evaluate import evaluate_flag, parse_config_value
from models import FeatureFlag, TargetingConfig


# ══════════════════════════════════════════════════════════════════════════════
# Unit tests for the pure evaluation functions
# ══════════════════════════════════════════════════════════════════════════════

class TestEvaluateFlagUnit:
    """Direct unit tests for evaluate_flag() — no HTTP involved."""

    def _flag(self, t_type, enabled=True, percentage=None, user_ids=None):
        return FeatureFlag(
            name="test_flag",
            enabled=enabled,
            targeting=TargetingConfig(
                type=t_type,
                percentage=percentage,
                user_ids=user_ids or [],
            ),
        )

    # ── everyone ──────────────────────────────────────────────────────────

    def test_everyone_on_for_regular_user(self):
        assert evaluate_flag(self._flag("everyone"), "user_1", False) is True

    def test_everyone_on_for_beta_user(self):
        assert evaluate_flag(self._flag("everyone"), "user_1", True) is True

    def test_everyone_off_when_disabled(self):
        assert evaluate_flag(self._flag("everyone", enabled=False), "user_1", False) is False

    # ── beta_users ────────────────────────────────────────────────────────

    def test_beta_on_for_beta_user(self):
        assert evaluate_flag(self._flag("beta_users"), "user_1", True) is True

    def test_beta_off_for_regular_user(self):
        assert evaluate_flag(self._flag("beta_users"), "user_1", False) is False

    def test_beta_off_when_flag_disabled(self):
        assert evaluate_flag(self._flag("beta_users", enabled=False), "user_1", True) is False

    # ── percentage ────────────────────────────────────────────────────────

    def _bucket(self, user_id: str, flag_name: str = "test_flag") -> int:
        from routers.evaluate import _compute_bucket
        return _compute_bucket(user_id, flag_name)

    def test_percentage_100_is_always_on(self):
        flag = self._flag("percentage", percentage=100)
        for uid in ["alice", "bob", "charlie", "dave", "eve"]:
            assert evaluate_flag(flag, uid, False) is True

    def test_percentage_0_is_always_off(self):
        flag = self._flag("percentage", percentage=0)
        for uid in ["alice", "bob", "charlie", "dave", "eve"]:
            assert evaluate_flag(flag, uid, False) is False

    def test_percentage_deterministic(self):
        flag = self._flag("percentage", percentage=50)
        # Same user should always get the same result
        for uid in ["stable_user_1", "stable_user_2", "stable_user_3"]:
            r1 = evaluate_flag(flag, uid, False)
            r2 = evaluate_flag(flag, uid, False)
            assert r1 == r2, f"Non-deterministic result for {uid}"

    def test_percentage_bucket_boundary(self):
        """A user whose bucket equals the percentage should be IN."""
        flag = self._flag("percentage", percentage=50)
        # Find a user who is exactly on the boundary
        for i in range(1000):
            uid = f"user_{i}"
            bucket = self._bucket(uid)
            expected = bucket <= 50
            assert evaluate_flag(flag, uid, False) == expected

    def test_percentage_distribution_roughly_correct(self):
        """With 10 % rollout, roughly 10 % of 1000 users should be ON."""
        flag = self._flag("percentage", percentage=10)
        on_count = sum(
            1 for i in range(1000)
            if evaluate_flag(flag, f"user_{i}", False)
        )
        # Allow ±5 % tolerance around the expected 100 users
        assert 50 <= on_count <= 150, f"Got {on_count}/1000 — too far from 10 %"

    def test_percentage_off_when_flag_disabled(self):
        flag = self._flag("percentage", enabled=False, percentage=100)
        assert evaluate_flag(flag, "any_user", False) is False

    # ── user_ids ──────────────────────────────────────────────────────────

    def test_user_ids_on_for_listed_user(self):
        flag = self._flag("user_ids", user_ids=["alice", "bob"])
        assert evaluate_flag(flag, "alice", False) is True
        assert evaluate_flag(flag, "bob",   False) is True

    def test_user_ids_off_for_unlisted_user(self):
        flag = self._flag("user_ids", user_ids=["alice"])
        assert evaluate_flag(flag, "charlie", False) is False

    def test_user_ids_off_for_empty_list(self):
        flag = self._flag("user_ids", user_ids=[])
        assert evaluate_flag(flag, "alice", False) is False

    def test_user_ids_off_when_flag_disabled(self):
        flag = self._flag("user_ids", enabled=False, user_ids=["alice"])
        assert evaluate_flag(flag, "alice", False) is False

    def test_user_ids_case_sensitive(self):
        flag = self._flag("user_ids", user_ids=["Alice"])
        assert evaluate_flag(flag, "alice", False) is False


# ══════════════════════════════════════════════════════════════════════════════
# Unit tests for parse_config_value()
# ══════════════════════════════════════════════════════════════════════════════

class TestParseConfigValue:
    def test_string_passthrough(self):
        assert parse_config_value("hello", "string") == "hello"

    def test_integer_number(self):
        assert parse_config_value("42", "number") == 42
        assert isinstance(parse_config_value("42", "number"), int)

    def test_float_number(self):
        result = parse_config_value("3.14", "number")
        assert abs(result - 3.14) < 1e-9
        assert isinstance(result, float)

    def test_invalid_number_returns_string(self):
        assert parse_config_value("not-a-number", "number") == "not-a-number"

    @pytest.mark.parametrize("val", ["true", "True", "TRUE", "1", "yes"])
    def test_truthy_boolean_values(self, val):
        assert parse_config_value(val, "boolean") is True

    @pytest.mark.parametrize("val", ["false", "False", "FALSE", "0", "no"])
    def test_falsy_boolean_values(self, val):
        assert parse_config_value(val, "boolean") is False


# ══════════════════════════════════════════════════════════════════════════════
# Integration tests for POST /evaluate/
# ══════════════════════════════════════════════════════════════════════════════

class TestEvaluateEndpoint:
    def test_empty_store_returns_empty_dicts(self, client):
        r = client.post("/evaluate/", json={"user_id": "alice"})
        assert r.status_code == 200
        body = r.json()
        assert body["flags"]   == {}
        assert body["configs"] == {}
        assert body["user_id"] == "alice"

    def test_everyone_flag_is_on(self, seeded_client):
        r = seeded_client.post("/evaluate/", json={"user_id": "anyone"})
        assert r.status_code == 200
        assert r.json()["flags"]["feature_everyone"] is True

    def test_disabled_flag_is_always_off(self, seeded_client):
        r = seeded_client.post("/evaluate/", json={"user_id": "anyone"})
        assert r.json()["flags"]["feature_disabled"] is False

    def test_beta_flag_on_for_beta_user(self, seeded_client):
        r = seeded_client.post("/evaluate/", json={
            "user_id": "beta_tester", "is_beta_user": True,
        })
        assert r.json()["flags"]["feature_beta"] is True

    def test_beta_flag_off_for_non_beta(self, seeded_client):
        r = seeded_client.post("/evaluate/", json={
            "user_id": "regular", "is_beta_user": False,
        })
        assert r.json()["flags"]["feature_beta"] is False

    def test_user_id_included_in_response(self, seeded_client):
        r = seeded_client.post("/evaluate/", json={"user_id": "custom_id"})
        assert r.json()["user_id"] == "custom_id"

    def test_flag_names_filter(self, seeded_client):
        r = seeded_client.post("/evaluate/", json={
            "user_id": "alice",
            "flag_names": ["feature_everyone"],
        })
        flags = r.json()["flags"]
        assert set(flags.keys()) == {"feature_everyone"}

    def test_config_types_are_cast(self, seeded_client):
        configs = seeded_client.post(
            "/evaluate/", json={"user_id": "alice"}
        ).json()["configs"]
        assert isinstance(configs["welcome_message"],  str)
        assert isinstance(configs["max_retries"],       int)
        assert isinstance(configs["maintenance_mode"],  bool)

    def test_config_number_value(self, seeded_client):
        configs = seeded_client.post(
            "/evaluate/", json={"user_id": "x"}
        ).json()["configs"]
        assert configs["max_retries"] == 3

    def test_config_boolean_false(self, seeded_client):
        configs = seeded_client.post(
            "/evaluate/", json={"user_id": "x"}
        ).json()["configs"]
        assert configs["maintenance_mode"] is False

    def test_anonymous_user_default(self, seeded_client):
        """Omitting user_id should default to 'anonymous'."""
        r = seeded_client.post("/evaluate/", json={})
        assert r.status_code == 200
        assert r.json()["user_id"] == "anonymous"

    def test_percentage_consistency_across_calls(self, client):
        """Same user must get the same evaluation on repeated calls."""
        client.post("/flags/", json={
            "name": "pct_stable",
            "enabled": True,
            "targeting": {"type": "percentage", "percentage": 50},
        })
        payload = {"user_id": "same_user_every_time"}
        first  = client.post("/evaluate/", json=payload).json()["flags"]["pct_stable"]
        second = client.post("/evaluate/", json=payload).json()["flags"]["pct_stable"]
        third  = client.post("/evaluate/", json=payload).json()["flags"]["pct_stable"]
        assert first == second == third

    def test_user_ids_targeting_via_evaluate(self, client):
        client.post("/flags/", json={
            "name": "vip_feature",
            "enabled": True,
            "targeting": {"type": "user_ids", "user_ids": ["vip_alice"]},
        })
        assert client.post("/evaluate/", json={
            "user_id": "vip_alice"
        }).json()["flags"]["vip_feature"] is True

        assert client.post("/evaluate/", json={
            "user_id": "regular_bob"
        }).json()["flags"]["vip_feature"] is False

    def test_toggling_flag_changes_evaluation(self, client):
        flag_id = client.post("/flags/", json={
            "name": "toggleable",
            "enabled": True,
            "targeting": {"type": "everyone"},
        }).json()["id"]

        assert client.post(
            "/evaluate/", json={"user_id": "x"}
        ).json()["flags"]["toggleable"] is True

        client.patch(f"/flags/{flag_id}", json={"enabled": False})

        assert client.post(
            "/evaluate/", json={"user_id": "x"}
        ).json()["flags"]["toggleable"] is False
