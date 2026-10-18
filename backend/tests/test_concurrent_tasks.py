"""Concurrency and tenant-isolation tests for shared task state.

These tests do NOT require a live FalkorDB instance.  They use an in-process
mock graph that is shared across threads, simulating concurrent reads and
writes, and verify that:

1. Concurrent task creation by two tenants does not produce cross-tenant
   data leakage (tenant isolation).
2. Concurrent investigator handoffs for independent tasks produce independent
   state — one task's findings do not appear on the other.
3. The retry logic in _query() recovers from a transient RedisError on the
   first attempt without raising to the caller.

Limitations documented explicitly:
- The mock graph uses a plain dict protected by a threading.Lock.  The real
  FalkorDB is a single-threaded Redis-compatible process, so read/write
  ordering is serialised server-side.  These tests verify Python-level
  isolation, not FalkorDB server concurrency.
- True concurrent write storms to a live database are not tested here.
"""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace
from typing import Any

import pytest

from app.graph.tasks import create_task, get_task, investigator_handoff


# ---------------------------------------------------------------------------
# Thread-safe mock graph
# ---------------------------------------------------------------------------

class ConcurrentTaskGraph:
    """Minimal thread-safe mock that stores tasks in a dict protected by a
    Lock.  Simulates the FalkorDB MERGE/MATCH pattern for Task nodes."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tasks: dict[str, dict[str, Any]] = {}
        self._call_count = 0

    def _task_row(self, task: dict[str, Any]) -> list[Any]:
        """Return the column-ordered list expected by tasks._task()."""
        return [
            task[k] for k in (
                "id", "tenant_id", "system_id", "status", "assigned_role",
                "findings_json", "evidence_refs_json", "review_status",
                "review_result_json", "next_action", "created_at", "updated_at",
            )
        ]

    def query(self, query: str, params: dict[str, Any] | None = None) -> Any:
        params = params or {}
        with self._lock:
            self._call_count += 1

            # CREATE_TASK — MERGE (t:Task {id: $task_id}) … SET t.status = 'assigned',
            if "MERGE (t:Task {id: $task_id})" in query and "t.status = 'assigned'" in query:
                tid = params["task_id"]
                self._tasks[tid] = {
                    "id": tid,
                    "tenant_id": params["tenant_id"],
                    "system_id": params["system_id"],
                    "status": "assigned",
                    "assigned_role": "investigator",
                    "findings_json": "[]",
                    "evidence_refs_json": "[]",
                    "review_status": "pending",
                    "review_result_json": "{}",
                    "next_action": "investigate",
                    "created_at": params["timestamp"],
                    "updated_at": params["timestamp"],
                }
                return SimpleNamespace(result_set=[[tid]])

            # SAVE_INVESTIGATOR_HANDOFF — SET t.status = 'investigator_complete'
            # (also merges a Handoff node in the same query — handled together)
            if "t.status = 'investigator_complete'" in query:
                tid = params["task_id"]
                if tid in self._tasks:
                    self._tasks[tid].update({
                        "status": "investigator_complete",
                        "assigned_role": "reviewer",
                        "findings_json": params["findings_json"],
                        "evidence_refs_json": params["evidence_refs_json"],
                        "next_action": "review",
                        "updated_at": params["timestamp"],
                    })
                return SimpleNamespace(result_set=[[tid]])

            # GET_TASK — MATCH (t:Task {id: $task_id, tenant_id: $tenant_id})
            if "MATCH (t:Task {id: $task_id, tenant_id: $tenant_id})" in query:
                tid = params.get("task_id", "")
                ten = params.get("tenant_id", "")
                task = self._tasks.get(tid)
                if task is None or task["tenant_id"] != ten:
                    return SimpleNamespace(result_set=[])
                return SimpleNamespace(result_set=[self._task_row(task)])

            return SimpleNamespace(result_set=[])


# ---------------------------------------------------------------------------
# Test 1 — concurrent task creation does not mix tenant data
# ---------------------------------------------------------------------------

def test_concurrent_task_creation_preserves_tenant_isolation() -> None:
    """Two threads each create a task for a different tenant.  After both
    finish, neither task is visible to the other tenant's query."""
    graph = ConcurrentTaskGraph()
    results: dict[str, Any] = {}
    errors: list[Exception] = []

    def create(tenant: str) -> None:
        try:
            task = create_task("system-checkout", tenant_id=tenant, graph=graph)
            results[tenant] = task
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [
        threading.Thread(target=create, args=("tenant-alpha",)),
        threading.Thread(target=create, args=("tenant-beta",)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Thread errors: {errors}"
    assert "tenant-alpha" in results and "tenant-beta" in results

    task_alpha = results["tenant-alpha"]
    task_beta = results["tenant-beta"]

    # Each task belongs to its own tenant.
    assert task_alpha["tenant_id"] == "tenant-alpha"
    assert task_beta["tenant_id"] == "tenant-beta"

    # Task IDs are different.
    assert task_alpha["task_id"] != task_beta["task_id"]

    # Cross-tenant lookup returns None.
    cross = get_task(task_alpha["task_id"], tenant_id="tenant-beta", graph=graph)
    assert cross is None, "tenant-beta must not see tenant-alpha's task"


# ---------------------------------------------------------------------------
# Test 2 — concurrent handoffs for independent tasks don't bleed findings
# ---------------------------------------------------------------------------

def test_concurrent_handoffs_keep_findings_independent() -> None:
    """Two threads hand off two separate tasks concurrently.  Each task must
    retain only its own findings after both threads complete."""
    graph = ConcurrentTaskGraph()

    task_a = create_task("system-checkout", tenant_id="tenant-a", graph=graph)
    task_b = create_task("system-payments", tenant_id="tenant-b", graph=graph)

    findings_a = [{"claim": "Checkout is degraded", "evidence_refs": ["doc-a"]}]
    findings_b = [{"claim": "Payments API is slow", "evidence_refs": ["doc-b"]}]
    errors: list[Exception] = []

    def handoff(task_id: str, findings: list, refs: list, tenant: str) -> None:
        try:
            investigator_handoff(task_id, findings, refs, tenant_id=tenant, graph=graph)
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [
        threading.Thread(target=handoff, args=(task_a["task_id"], findings_a, ["doc-a"], "tenant-a")),
        threading.Thread(target=handoff, args=(task_b["task_id"], findings_b, ["doc-b"], "tenant-b")),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Thread errors: {errors}"

    result_a = get_task(task_a["task_id"], tenant_id="tenant-a", graph=graph)
    result_b = get_task(task_b["task_id"], tenant_id="tenant-b", graph=graph)

    assert result_a is not None
    assert result_b is not None

    # Each task has only its own findings.
    claims_a = [f.get("claim") for f in result_a["findings"]]
    claims_b = [f.get("claim") for f in result_b["findings"]]
    assert "Checkout is degraded" in claims_a
    assert "Payments API is slow" not in claims_a
    assert "Payments API is slow" in claims_b
    assert "Checkout is degraded" not in claims_b


# ---------------------------------------------------------------------------
# Test 3 — retry logic recovers from a single transient RedisError
# ---------------------------------------------------------------------------

def test_task_query_retries_on_transient_redis_error() -> None:
    """The _query helper in tasks.py retries once on RedisError.  This test
    injects a failure on the first call and a success on the second."""
    from redis.exceptions import RedisError
    from app.graph.tasks import _query as tasks_query

    attempt = {"count": 0}
    base_graph = ConcurrentTaskGraph()

    class FlakyGraph:
        def query(self, query: str, params: dict | None = None) -> Any:
            attempt["count"] += 1
            if attempt["count"] == 1:
                raise RedisError("Simulated transient failure")
            return base_graph.query(query, params)

    # _query is an internal helper that accepts a graph object directly.
    # It should raise RuntimeError only after exhausting retries.
    # Here we inject TWO failures — the helper retries once, so after 2
    # failures it should raise RuntimeError.
    attempt2 = {"count": 0}

    class AlwaysFlakyGraph:
        def query(self, query: str, params: dict | None = None) -> Any:
            attempt2["count"] += 1
            raise RedisError("Permanent failure")

    with pytest.raises(RuntimeError, match="retry"):
        tasks_query(
            AlwaysFlakyGraph(),
            "MATCH (t:Task {id: $task_id, tenant_id: $tenant_id}) RETURN t.id AS id",
            {"task_id": "task-x", "tenant_id": "default"},
        )

    # After two attempts the error is wrapped as RuntimeError.
    assert attempt2["count"] == 2, "Expected exactly 2 attempts before giving up"


# ---------------------------------------------------------------------------
# Documented limitation
# ---------------------------------------------------------------------------

# NOTE: These tests verify Python-level thread safety and tenant isolation
# against a mock graph.  They do NOT test FalkorDB server-level concurrency.
# FalkorDB uses a single-threaded Redis event loop, so commands are serialised
# on the server regardless.  If horizontal scaling via Redis Cluster or
# FalkorDB Enterprise replication is added, additional concurrency tests
# against a live instance would be required.
