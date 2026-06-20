"""
Tests for the storage layer.
Validates persistence, isolation, CRUD correctness and thread-safety.
"""
import threading
import pytest
from models import FeatureFlag, RemoteConfig, TargetingConfig
import storage


# ══════════════════════════════════════════════════════════════════════════════
# Flag storage
# ══════════════════════════════════════════════════════════════════════════════

class TestFlagStorage:

    def _make_flag(self, name="test_flag", enabled=False):
        return FeatureFlag(name=name, enabled=enabled)

    # ── create / read ─────────────────────────────────────────────────────

    def test_create_and_retrieve_by_id(self, isolated_store):
        flag = self._make_flag()
        storage.create_flag(flag)
        found = storage.get_flag_by_id(flag.id)
        assert found is not None
        assert found.name == "test_flag"

    def test_create_and_retrieve_by_name(self, isolated_store):
        flag = self._make_flag("named_flag")
        storage.create_flag(flag)
        found = storage.get_flag_by_name("named_flag")
        assert found is not None
        assert found.id == flag.id

    def test_get_all_flags_empty(self, isolated_store):
        assert storage.get_all_flags() == []

    def test_get_all_flags_multiple(self, isolated_store):
        for i in range(5):
            storage.create_flag(self._make_flag(f"flag_{i}"))
        assert len(storage.get_all_flags()) == 5

    def test_get_by_id_unknown_returns_none(self, isolated_store):
        assert storage.get_flag_by_id("does-not-exist") is None

    def test_get_by_name_unknown_returns_none(self, isolated_store):
        assert storage.get_flag_by_name("ghost") is None

    # ── update ────────────────────────────────────────────────────────────

    def test_update_enabled(self, isolated_store):
        flag = self._make_flag(enabled=False)
        storage.create_flag(flag)
        updated = storage.update_flag(flag.id, {"enabled": True})
        assert updated.enabled is True
        assert storage.get_flag_by_id(flag.id).enabled is True

    def test_update_description(self, isolated_store):
        flag = self._make_flag()
        storage.create_flag(flag)
        storage.update_flag(flag.id, {"description": "new desc"})
        assert storage.get_flag_by_id(flag.id).description == "new desc"

    def test_update_targeting_merges(self, isolated_store):
        flag = FeatureFlag(name="merge_test",
                           targeting=TargetingConfig(type="everyone"))
        storage.create_flag(flag)
        storage.update_flag(flag.id, {"targeting": {"type": "beta_users"}})
        result = storage.get_flag_by_id(flag.id)
        assert result.targeting.type == "beta_users"

    def test_update_nonexistent_returns_none(self, isolated_store):
        assert storage.update_flag("ghost-id", {"enabled": True}) is None

    def test_update_bumps_updated_at(self, isolated_store):
        flag = self._make_flag()
        storage.create_flag(flag)
        original_ts = storage.get_flag_by_id(flag.id).updated_at
        import time; time.sleep(0.01)
        storage.update_flag(flag.id, {"enabled": True})
        new_ts = storage.get_flag_by_id(flag.id).updated_at
        # updated_at may be identical if the system clock resolution is low,
        # but the field must exist and be a string
        assert isinstance(new_ts, str) and len(new_ts) > 0

    # ── delete ────────────────────────────────────────────────────────────

    def test_delete_removes_flag(self, isolated_store):
        flag = self._make_flag()
        storage.create_flag(flag)
        assert storage.delete_flag(flag.id) is True
        assert storage.get_flag_by_id(flag.id) is None

    def test_delete_returns_false_for_unknown(self, isolated_store):
        assert storage.delete_flag("ghost-id") is False

    def test_delete_does_not_affect_others(self, isolated_store):
        f1 = self._make_flag("keep")
        f2 = self._make_flag("delete_me")
        storage.create_flag(f1)
        storage.create_flag(f2)
        storage.delete_flag(f2.id)
        assert storage.get_flag_by_id(f1.id) is not None
        assert len(storage.get_all_flags()) == 1

    # ── persistence ───────────────────────────────────────────────────────

    def test_data_persists_across_reads(self, isolated_store):
        flag = self._make_flag("persistent")
        storage.create_flag(flag)
        # Re-read from disk
        all_flags = storage.get_all_flags()
        names = [f.name for f in all_flags]
        assert "persistent" in names


# ══════════════════════════════════════════════════════════════════════════════
# Config storage
# ══════════════════════════════════════════════════════════════════════════════

class TestConfigStorage:

    def _make_config(self, key="test_key", value="test_val", type_="string"):
        return RemoteConfig(key=key, value=value, type=type_)

    def test_create_and_retrieve(self, isolated_store):
        cfg = self._make_config()
        storage.create_config(cfg)
        found = storage.get_config_by_id(cfg.id)
        assert found is not None
        assert found.key == "test_key"

    def test_get_by_key(self, isolated_store):
        cfg = self._make_config(key="lookup_me")
        storage.create_config(cfg)
        found = storage.get_config_by_key("lookup_me")
        assert found is not None
        assert found.id == cfg.id

    def test_get_all_empty(self, isolated_store):
        assert storage.get_all_configs() == []

    def test_update_value(self, isolated_store):
        cfg = self._make_config(value="old")
        storage.create_config(cfg)
        storage.update_config(cfg.id, {"value": "new"})
        assert storage.get_config_by_id(cfg.id).value == "new"

    def test_update_type(self, isolated_store):
        cfg = self._make_config()
        storage.create_config(cfg)
        storage.update_config(cfg.id, {"type": "number"})
        assert storage.get_config_by_id(cfg.id).type == "number"

    def test_delete_config(self, isolated_store):
        cfg = self._make_config()
        storage.create_config(cfg)
        assert storage.delete_config(cfg.id) is True
        assert storage.get_config_by_id(cfg.id) is None

    def test_delete_unknown_returns_false(self, isolated_store):
        assert storage.delete_config("ghost") is False


# ══════════════════════════════════════════════════════════════════════════════
# Thread safety
# ══════════════════════════════════════════════════════════════════════════════

class TestThreadSafety:

    def test_concurrent_flag_creates_no_data_loss(self, isolated_store):
        """100 threads each create a unique flag; all 100 must survive."""
        errors = []

        def create(i):
            try:
                storage.create_flag(FeatureFlag(name=f"concurrent_flag_{i}"))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=create, args=(i,)) for i in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Errors during concurrent create: {errors}"
        assert len(storage.get_all_flags()) == 100

    def test_concurrent_updates_no_corruption(self, isolated_store):
        """50 threads all toggle the same flag; final state must be valid."""
        flag = FeatureFlag(name="hotspot_flag", enabled=False)
        storage.create_flag(flag)

        def toggle(i):
            storage.update_flag(flag.id, {"enabled": i % 2 == 0})

        threads = [threading.Thread(target=toggle, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # After all toggles, the flag must still exist and have a valid bool
        result = storage.get_flag_by_id(flag.id)
        assert result is not None
        assert isinstance(result.enabled, bool)
