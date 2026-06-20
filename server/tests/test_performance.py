"""
Performance benchmark tests.

These tests measure concrete speed properties of the optimised components
and assert that they stay within acceptable bounds.  They run in the normal
pytest suite — no separate tooling required.

What is measured
────────────────
  storage     — O(1) lookup vs linear-scan baseline
  eval cache  — repeated /evaluate calls for the same user
  ETags       — 304 round-trip avoids JSON body transfer
  broadcast   — asyncio.gather concurrent broadcast throughput
  thread-safe — 200-thread concurrent write stress test
"""
from __future__ import annotations

import asyncio
import threading
import time
from typing import List

import pytest

import storage
from models import FeatureFlag, RemoteConfig, TargetingConfig
from routers.evaluate import (
    _eval_cache, _reset_eval_cache, bump_eval_cache, evaluate_flag,
)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _bulk_flags(n: int) -> List[FeatureFlag]:
    return [
        FeatureFlag(
            name=f"flag_{i}",
            enabled=True,
            targeting=TargetingConfig(type="everyone"),
        )
        for i in range(n)
    ]


def _bulk_configs(n: int) -> List[RemoteConfig]:
    return [RemoteConfig(key=f"cfg_{i}", value=str(i), type="number") for i in range(n)]


# ─── Storage O(1) lookup ─────────────────────────────────────────────────────

class TestStorageLookupComplexity:
    """
    Verify that lookup time stays flat regardless of store size.
    If storage still used a linear scan, lookup in a 5 000-item store
    would be ~500× slower than in a 10-item store.
    """

    def _fill(self, n: int) -> List[str]:
        flags = _bulk_flags(n)
        for f in flags:
            storage.create_flag(f)
        return [f.id for f in flags]

    def _time_lookup(self, ids: List[str], samples: int = 200) -> float:
        start = time.perf_counter()
        for i in range(samples):
            storage.get_flag_by_id(ids[i % len(ids)])
        return (time.perf_counter() - start) / samples

    def test_lookup_small_store(self, isolated_store):
        ids = self._fill(10)
        t   = self._time_lookup(ids)
        assert t < 0.001, f"Small-store lookup too slow: {t*1000:.3f} ms"

    def test_lookup_large_store(self, isolated_store):
        ids = self._fill(2_000)
        t   = self._time_lookup(ids)
        assert t < 0.001, f"Large-store lookup too slow: {t*1000:.3f} ms"

    def test_lookup_scales_sublinearly(self, isolated_store):
        """O(1): doubling the store size should not double the lookup time."""
        ids_small = self._fill(100)
        t_small   = self._time_lookup(ids_small)

        storage._reset()
        storage._ensure_file()

        ids_large = self._fill(2_000)
        t_large   = self._time_lookup(ids_large)

        # Allow up to 10× slowdown for 20× size increase (O(1) ⟹ ~1×)
        ratio = t_large / (t_small + 1e-9)
        assert ratio < 10, (
            f"Lookup degraded {ratio:.1f}× for 20× more items — may not be O(1). "
            f"small={t_small*1000:.3f}ms  large={t_large*1000:.3f}ms"
        )

    def test_name_lookup_o1(self, isolated_store):
        flags = _bulk_flags(1_000)
        for f in flags:
            storage.create_flag(f)
        start = time.perf_counter()
        for i in range(500):
            storage.get_flag_by_name(f"flag_{i % 1_000}")
        elapsed = (time.perf_counter() - start) / 500
        assert elapsed < 0.001, f"Name lookup too slow: {elapsed*1000:.3f} ms"

    def test_config_key_lookup_o1(self, isolated_store):
        configs = _bulk_configs(1_000)
        for c in configs:
            storage.create_config(c)
        start = time.perf_counter()
        for i in range(500):
            storage.get_config_by_key(f"cfg_{i % 1_000}")
        elapsed = (time.perf_counter() - start) / 500
        assert elapsed < 0.001, f"Config key lookup too slow: {elapsed*1000:.3f} ms"


# ─── Eval cache ───────────────────────────────────────────────────────────────

class TestEvalCache:
    """The cache turns repeated evaluate calls from O(flags) to O(1)."""

    def _setup_flags(self, n: int = 20) -> None:
        for f in _bulk_flags(n):
            storage.create_flag(f)

    def test_cache_hit_is_faster_than_miss(self, client, isolated_store):
        """
        Measure the cache at the function level where ASGI overhead does not
        mask the delta.  Cold path = full flag iteration + MD5 hashing.
        Warm path = single OrderedDict lookup.
        """
        import routers.evaluate as ev
        self._setup_flags(50)
        req = __import__("models", fromlist=["EvaluateRequest"]).EvaluateRequest(
            user_id="bench_user", is_beta_user=False
        )

        ROUNDS = 2_000

        # Prime the cold path once so imports / JIT are settled
        bump_eval_cache()
        flags   = storage.get_all_flags()
        configs = storage.get_all_configs()

        # Cold: recompute every iteration
        t0 = time.perf_counter()
        for _ in range(ROUNDS):
            bump_eval_cache()
            key = ev._cache_key(ev._eval_gen, req.user_id, req.is_beta_user, None)
            result = ev._cache_get(key)
            if result is None:
                result = __import__("models", fromlist=["EvaluateResponse"]).EvaluateResponse(
                    user_id=req.user_id,
                    flags={f.name: ev.evaluate_flag(f, req.user_id, req.is_beta_user) for f in flags},
                    configs={c.key: ev.parse_config_value(c.value, c.type) for c in configs},
                )
                ev._cache_set(key, result)
        avg_cold = (time.perf_counter() - t0) / ROUNDS

        # Warm: same key, cache hit every time
        t0 = time.perf_counter()
        for _ in range(ROUNDS):
            ev._cache_get(key)
        avg_warm = (time.perf_counter() - t0) / ROUNDS

        speedup = avg_cold / (avg_warm + 1e-9)
        assert speedup > 5, (
            f"Cache not providing meaningful speedup over direct computation: "
            f"cold={avg_cold*1_000_000:.1f}µs  warm={avg_warm*1_000_000:.1f}µs  "
            f"speedup={speedup:.1f}×  (expected >5×)"
        )

    def test_cache_invalidated_after_flag_toggle(self, client, isolated_store):
        flag_id = client.post("/flags/", json={
            "name": "toggle_me", "enabled": True,
            "targeting": {"type": "everyone"},
        }).json()["id"]

        r1 = client.post("/evaluate/", json={"user_id": "u"}).json()
        assert r1["flags"]["toggle_me"] is True

        # Toggle the flag — must bump the cache generation
        client.patch(f"/flags/{flag_id}", json={"enabled": False})

        r2 = client.post("/evaluate/", json={"user_id": "u"}).json()
        assert r2["flags"]["toggle_me"] is False, (
            "Stale cached result returned after flag mutation"
        )

    def test_cache_isolates_by_user(self, client, isolated_store):
        client.post("/flags/", json={
            "name": "uid_flag", "enabled": True,
            "targeting": {"type": "user_ids", "user_ids": ["vip"]},
        })
        vip     = client.post("/evaluate/", json={"user_id": "vip"}).json()
        regular = client.post("/evaluate/", json={"user_id": "pleb"}).json()
        assert vip["flags"]["uid_flag"]     is True
        assert regular["flags"]["uid_flag"] is False

    def test_cache_isolates_by_beta_flag(self, client, isolated_store):
        client.post("/flags/", json={
            "name": "beta_f", "enabled": True,
            "targeting": {"type": "beta_users"},
        })
        beta = client.post("/evaluate/", json={
            "user_id": "same", "is_beta_user": True}).json()
        norm = client.post("/evaluate/", json={
            "user_id": "same", "is_beta_user": False}).json()
        assert beta["flags"]["beta_f"] is True
        assert norm["flags"]["beta_f"] is False

    def test_cache_bounded_by_max_size(self, client, isolated_store):
        """Fill the cache beyond its max; size must stay at _CACHE_MAX_SIZE."""
        import routers.evaluate as ev
        for i in range(ev._CACHE_MAX_SIZE + 50):
            bump_eval_cache()
            client.post("/evaluate/", json={"user_id": f"u_{i}"})
        with ev._cache_lock:
            size = len(ev._eval_cache)
        assert size <= ev._CACHE_MAX_SIZE, (
            f"Cache grew to {size} - LRU eviction not working"
        )

    def test_cache_cleared_on_config_change(self, client, isolated_store):
        cfg_id = client.post("/configs/", json={
            "key": "msg", "value": "hello", "type": "string",
        }).json()["id"]
        r1 = client.post("/evaluate/", json={"user_id": "u"}).json()
        assert r1["configs"]["msg"] == "hello"

        client.patch(f"/configs/{cfg_id}", json={"value": "world"})
        r2 = client.post("/evaluate/", json={"user_id": "u"}).json()
        assert r2["configs"]["msg"] == "world", (
            "Config update not reflected — eval cache not invalidated"
        )


# ─── ETag conditional GET ─────────────────────────────────────────────────────

class TestETags:
    def test_flags_list_has_etag_header(self, seeded_client):
        r = seeded_client.get("/flags/")
        assert "etag" in r.headers, "ETag header missing from GET /flags/"

    def test_configs_list_has_etag_header(self, seeded_client):
        r = seeded_client.get("/configs/")
        assert "etag" in r.headers, "ETag header missing from GET /configs/"

    def test_conditional_get_returns_304(self, seeded_client):
        etag = seeded_client.get("/flags/").headers["etag"]
        r    = seeded_client.get("/flags/", headers={"if-none-match": etag})
        assert r.status_code == 304
        assert r.content == b"", "304 response must have empty body"

    def test_stale_etag_returns_200(self, seeded_client):
        seeded_client.get("/flags/").headers["etag"]  # warm
        seeded_client.post("/flags/", json={"name": "new_flag"})
        fresh_etag = seeded_client.get("/flags/").headers["etag"]
        r = seeded_client.get("/flags/", headers={"if-none-match": '"stale"'})
        assert r.status_code == 200

    def test_etag_changes_after_mutation(self, client):
        client.post("/flags/", json={"name": "f1"})
        tag1 = client.get("/flags/").headers["etag"]
        client.post("/flags/", json={"name": "f2"})
        tag2 = client.get("/flags/").headers["etag"]
        assert tag1 != tag2, "ETag must change when content changes"

    def test_etag_stable_without_mutation(self, seeded_client):
        t1 = seeded_client.get("/flags/").headers["etag"]
        t2 = seeded_client.get("/flags/").headers["etag"]
        assert t1 == t2, "ETag must be stable between identical reads"

    def test_304_saves_bandwidth(self, seeded_client):
        """304 body is empty; 200 body is non-empty."""
        etag = seeded_client.get("/flags/").headers["etag"]
        r304 = seeded_client.get("/flags/", headers={"if-none-match": etag})
        r200 = seeded_client.get("/flags/")
        assert len(r304.content) == 0
        assert len(r200.content) > 0


# ─── Concurrent broadcast ────────────────────────────────────────────────────

class TestConcurrentBroadcast:
    def test_broadcast_reaches_multiple_ws_clients(self, seeded_client):
        import json
        WS_COUNT = 5
        received = [[] for _ in range(WS_COUNT)]
        ctxs     = [seeded_client.websocket_connect("/ws") for _ in range(WS_COUNT)]
        conns    = [ctx.__enter__() for ctx in ctxs]

        try:
            # Drain initial_state for each
            for ws in conns:
                ws.receive_text()

            # One mutation should reach every client
            seeded_client.post("/flags/", json={"name": "broadcast_test"})

            for i, ws in enumerate(conns):
                msg = json.loads(ws.receive_text())
                received[i].append(msg["event"])
        finally:
            for ws, ctx in zip(conns, ctxs):
                ctx.__exit__(None, None, None)

        for i, events in enumerate(received):
            assert "flag_created" in events, (
                f"WS client {i} did not receive flag_created broadcast"
            )

    def test_broadcast_timing(self, seeded_client):
        """
        With concurrent gather(), sending to 10 WS clients should take
        well under 1 second total in a local test environment.
        """
        import json
        N    = 10
        ctxs = [seeded_client.websocket_connect("/ws") for _ in range(N)]
        conns = [ctx.__enter__() for ctx in ctxs]
        try:
            for ws in conns:
                ws.receive_text()  # drain initial_state

            t0 = time.perf_counter()
            seeded_client.post("/flags/", json={"name": "timing_test"})
            for ws in conns:
                ws.receive_text()
            elapsed = time.perf_counter() - t0

            assert elapsed < 1.0, (
                f"Broadcasting to {N} clients took {elapsed:.3f}s — too slow"
            )
        finally:
            for ctx in ctxs:
                ctx.__exit__(None, None, None)


# ─── Thread-safety stress test ───────────────────────────────────────────────

class TestConcurrencyStress:
    def test_200_concurrent_writers(self, isolated_store):
        """200 threads each write a unique flag; all must survive intact."""
        errors  = []
        N       = 200

        def write(i: int) -> None:
            try:
                storage.create_flag(FeatureFlag(name=f"stress_{i}"))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=write, args=(i,)) for i in range(N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrent write errors: {errors}"
        assert len(storage.get_all_flags()) == N, (
            "Some flags were silently dropped during concurrent writes"
        )

    def test_mixed_read_write_no_corruption(self, isolated_store):
        """Readers and writers run concurrently; no data should corrupt."""
        # Seed 50 flags first
        for f in _bulk_flags(50):
            storage.create_flag(f)

        errors = []

        def reader(_):
            try:
                flags = storage.get_all_flags()
                # Verify each returned object is valid
                for f in flags:
                    assert isinstance(f.name, str)
                    assert isinstance(f.enabled, bool)
            except Exception as e:
                errors.append(("read", e))

        def writer(i):
            try:
                storage.create_flag(FeatureFlag(name=f"new_{i}"))
            except Exception as e:
                errors.append(("write", e))

        threads = (
            [threading.Thread(target=reader, args=(i,)) for i in range(100)]
            + [threading.Thread(target=writer, args=(i,)) for i in range(50)]
        )
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrent mixed errors: {errors[:5]}"


# ─── Write coalescing ─────────────────────────────────────────────────────────

class TestWriteCoalescing:
    """
    Verify that rapid consecutive mutations produce a single disk write
    rather than one write per mutation.
    """

    def test_burst_produces_one_flush(self, isolated_store):
        """20 mutations within the coalescing window → exactly 1 disk write."""
        flush_count = [0]
        original    = storage._flush

        def counting_flush():
            flush_count[0] += 1
            original()

        storage._flush = counting_flush
        try:
            for i in range(20):
                storage.create_flag(FeatureFlag(name=f"burst_{i}"))

            # Timer is still pending — no flush yet
            assert flush_count[0] == 0, (
                f"Flush fired prematurely: {flush_count[0]} times"
            )

            # Drain the pending timer
            storage._flush_now()

            assert flush_count[0] == 1, (
                f"Expected 1 coalesced flush for 20 mutations, got {flush_count[0]}"
            )

            # All 20 flags survived in memory
            assert len(storage.get_all_flags()) == 20
        finally:
            storage._flush = original

    def test_all_data_on_disk_after_flush(self, isolated_store):
        """Data written to disk matches in-memory state after _flush_now()."""
        for i in range(5):
            storage.create_flag(FeatureFlag(name=f"persist_{i}"))
        storage._flush_now()

        # Reload from disk
        storage._reset()
        storage._ensure_file()
        names = {f.name for f in storage.get_all_flags()}
        assert names == {f"persist_{i}" for i in range(5)}

    def test_timer_resets_on_each_mutation(self, isolated_store):
        """Each new mutation should reset the coalesce window."""
        import time
        from storage import _COALESCE_MS
        flush_count = [0]
        original    = storage._flush

        def counting_flush():
            flush_count[0] += 1
            original()

        storage._flush = counting_flush
        try:
            # Write 3 flags with a small gap — all within one coalesce window
            for i in range(3):
                storage.create_flag(FeatureFlag(name=f"reset_{i}"))
                time.sleep(0.002)   # 2 ms — well within 10 ms window

            assert flush_count[0] == 0, "Timer should not have fired yet"
            storage._flush_now()
            assert flush_count[0] == 1
        finally:
            storage._flush = original

    def test_reset_cancels_pending_timer(self, isolated_store):
        """After _reset(), the coalescing timer must not write to disk."""
        flushed = [False]
        original = storage._flush

        def tracking_flush():
            flushed[0] = True
            original()

        storage._flush = tracking_flush
        try:
            storage.create_flag(FeatureFlag(name="should_not_flush"))
            storage._reset()   # cancels the timer
            import time; time.sleep(0.025)  # wait longer than COALESCE_MS
            assert not flushed[0], "Flush fired after _reset() — timer not cancelled"
        finally:
            storage._flush = original


# ─── Hash function ───────────────────────────────────────────────────────────

class TestHashFunction:
    """
    The bucket hash (MD5 in CPython — a C extension) is fast.
    These tests verify correctness and distribution, not speed:
    the bucket memo is what eliminates hash calls on repeat lookups.
    """

    def test_compute_bucket_is_deterministic(self):
        from routers.evaluate import _compute_bucket
        assert _compute_bucket("alice", "flag") == _compute_bucket("alice", "flag")

    def test_compute_bucket_range(self):
        from routers.evaluate import _compute_bucket
        for u in ["a", "user_42", "x" * 200]:
            b = _compute_bucket(u, "f")
            assert 1 <= b <= 100, f"Bucket {b} out of range for user '{u}'"

    def test_different_users_different_buckets(self):
        from routers.evaluate import _compute_bucket
        buckets = [_compute_bucket(f"u_{i}", "flag") for i in range(200)]
        # Expect reasonable variety — not all in the same bucket
        assert len(set(buckets)) > 30, "Suspiciously low bucket diversity"

    def test_percentage_distribution_uniform(self):
        """10 % rollout over 10 000 users should land close to 1 000 ON."""
        from models import FeatureFlag, TargetingConfig
        from routers.evaluate import evaluate_flag
        flag = FeatureFlag(
            name="dist_test",
            enabled=True,
            targeting=TargetingConfig(type="percentage", percentage=10),
        )
        on_count = sum(
            evaluate_flag(flag, f"user_{i}", False)
            for i in range(10_000)
        )
        assert 750 <= on_count <= 1_250, (
            f"Distribution out of range: {on_count}/10000 at 10%"
        )

    def test_memo_eliminates_hash_calls(self):
        """After the first call, subsequent calls for the same (user, flag)
        must skip hashing entirely — verified by counting _compute_bucket calls."""
        from routers.evaluate import _get_bucket, _clear_bucket_memo
        import unittest.mock as mock
        import routers.evaluate as ev

        _clear_bucket_memo()
        with mock.patch.object(ev, '_compute_bucket', wraps=ev._compute_bucket) as m:
            for _ in range(100):
                _get_bucket("same_user", "same_flag")
        assert m.call_count == 1, (
            f"_compute_bucket called {m.call_count} times for 100 identical lookups"
        )


# ─── Bucket memoisation ───────────────────────────────────────────────────────

class TestBucketMemo:
    def test_same_pair_returns_same_bucket(self, isolated_store):
        from routers.evaluate import _get_bucket, _clear_bucket_memo
        _clear_bucket_memo()
        b1 = _get_bucket("alice", "feature_x")
        b2 = _get_bucket("alice", "feature_x")
        assert b1 == b2

    def test_memo_avoids_recomputation(self, isolated_store):
        import time
        from routers.evaluate import _get_bucket, _clear_bucket_memo

        _clear_bucket_memo()
        user, flag = "memo_user", "memo_flag"

        # Cold: first call computes hash
        t0 = time.perf_counter()
        for _ in range(10_000):
            _clear_bucket_memo()
            _get_bucket(user, flag)
        cold = (time.perf_counter() - t0) / 10_000

        # Warm: bucket is memoised
        _clear_bucket_memo()
        _get_bucket(user, flag)   # prime cache
        t0 = time.perf_counter()
        for _ in range(10_000):
            _get_bucket(user, flag)
        warm = (time.perf_counter() - t0) / 10_000

        speedup = cold / (warm + 1e-12)
        assert speedup > 2, (
            f"Bucket memo not providing speedup: "
            f"cold={cold*1e6:.1f}µs  warm={warm*1e6:.1f}µs  "
            f"speedup={speedup:.1f}×"
        )

    def test_memo_bounded_size(self, isolated_store):
        from routers.evaluate import _get_bucket, _clear_bucket_memo, _bucket_memo, _BUCKET_MEMO_MAX
        _clear_bucket_memo()
        for i in range(_BUCKET_MEMO_MAX + 100):
            _get_bucket(f"u_{i}", "flag")
        assert len(_bucket_memo) <= _BUCKET_MEMO_MAX


# ─── WebSocket initial-state cache ───────────────────────────────────────────

class TestWSInitialStateCache:
    def test_same_payload_on_repeat_connects(self, seeded_client):
        import json
        payloads = []
        for _ in range(3):
            with seeded_client.websocket_connect("/ws") as ws:
                payloads.append(ws.receive_text())
        assert payloads[0] == payloads[1] == payloads[2], (
            "Initial-state payload changed between connects without a mutation"
        )

    def test_payload_refreshes_after_flag_mutation(self, seeded_client):
        import json
        with seeded_client.websocket_connect("/ws") as ws:
            before = ws.receive_text()
        seeded_client.post("/flags/", json={"name": "new_ws_flag"})
        with seeded_client.websocket_connect("/ws") as ws:
            after = ws.receive_text()
        assert before != after, "Cached payload not invalidated after flag create"
        flag_names = [f["name"] for f in json.loads(after)["data"]["flags"]]
        assert "new_ws_flag" in flag_names

    def test_payload_refreshes_after_config_mutation(self, seeded_client):
        import json
        cfg_id = seeded_client.post("/configs/", json={
            "key": "ws_cache_test", "value": "v1"
        }).json()["id"]
        with seeded_client.websocket_connect("/ws") as ws:
            before = ws.receive_text()
        seeded_client.patch(f"/configs/{cfg_id}", json={"value": "v2"})
        with seeded_client.websocket_connect("/ws") as ws:
            after = ws.receive_text()
        assert before != after

    def test_cache_hit_is_same_object(self, client):
        """Two connects without mutations share the exact same string object."""
        from websocket_manager import manager
        client.get("/")  # trigger lifespan (cache registration)
        with client.websocket_connect("/ws") as ws:
            ws.receive_text()
        first_cache = manager._initial_state_cache
        with client.websocket_connect("/ws") as ws:
            ws.receive_text()
        second_cache = manager._initial_state_cache
        assert first_cache is second_cache, (
            "Cache object was recreated without a mutation"
        )
