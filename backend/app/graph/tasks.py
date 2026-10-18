"""Persistent coordinator, investigator, and reviewer task state."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from redis.exceptions import RedisError

from .connection import get_graph

CREATE_TASK = """
MERGE (t:Task {id: $task_id})
SET t.tenant_id = $tenant_id,
    t.system_id = $system_id,
    t.status = 'assigned',
    t.assigned_role = 'investigator',
    t.findings_json = '[]',
    t.evidence_refs_json = '[]',
    t.review_status = 'pending',
    t.next_action = 'investigate',
    t.created_at = $timestamp,
    t.updated_at = $timestamp
RETURN t.id AS id
"""

GET_TASK = """
MATCH (t:Task {id: $task_id, tenant_id: $tenant_id})
RETURN t.id AS id, t.tenant_id AS tenant_id, t.system_id AS system_id,
       t.status AS status, t.assigned_role AS assigned_role,
       t.findings_json AS findings_json, t.evidence_refs_json AS evidence_refs_json,
       t.review_status AS review_status, t.review_result_json AS review_result_json,
       t.next_action AS next_action, t.created_at AS created_at,
       t.updated_at AS updated_at
"""

SAVE_INVESTIGATOR_HANDOFF = """
MATCH (t:Task {id: $task_id, tenant_id: $tenant_id})
SET t.status = 'investigator_complete',
    t.assigned_role = 'reviewer',
    t.findings_json = $findings_json,
    t.evidence_refs_json = $evidence_refs_json,
    t.next_action = 'review',
    t.updated_at = $timestamp
MERGE (h:Handoff {id: $handoff_id})
SET h.tenant_id = $tenant_id, h.task_id = $task_id, h.from_role = 'investigator',
    h.to_role = 'reviewer', h.created_at = $timestamp
MERGE (t)-[:HAS_HANDOFF]->(h)
RETURN t.id AS id
"""

SAVE_REVIEW = """
MATCH (t:Task {id: $task_id, tenant_id: $tenant_id})
SET t.status = $status,
    t.assigned_role = 'coordinator',
    t.review_status = $review_status,
    t.review_result_json = $review_result_json,
    t.next_action = $next_action,
    t.updated_at = $timestamp
MERGE (h:Handoff {id: $handoff_id})
SET h.tenant_id = $tenant_id, h.task_id = $task_id, h.from_role = 'reviewer',
    h.to_role = 'coordinator', h.created_at = $timestamp
MERGE (t)-[:HAS_HANDOFF]->(h)
RETURN t.id AS id
"""

GET_DOCUMENTS = """
MATCH (d:Document)
WHERE d.id IN $document_ids
RETURN d.id AS id, d.title AS title, d.source AS source, d.content AS content
"""


def _graph(graph: Any | None) -> Any:
    return graph if graph is not None else get_graph()


def _query(graph: Any, query: str, params: dict[str, Any]) -> Any:
    last_error: RedisError | None = None
    for attempt in range(2):
        try:
            return graph.query(query, params=params)
        except RedisError as exc:
            last_error = exc
            if attempt == 0:
                time.sleep(0.05)
    raise RuntimeError("FalkorDB shared task query failed after retry") from last_error


def _json(value: Any) -> str:
    return json.dumps(value or [], separators=(",", ":"), sort_keys=True)


def _decode(value: Any, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _tenant(tenant_id: str) -> str:
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise ValueError("tenant_id must be a non-empty string")
    return tenant_id.strip()


def _task(row: Any) -> dict[str, Any]:
    values = list(row)
    return {
        "task_id": values[0],
        "tenant_id": values[1],
        "system_id": values[2],
        "status": values[3],
        "assigned_role": values[4],
        "findings": _decode(values[5], []),
        "evidence_refs": _decode(values[6], []),
        "review_status": values[7],
        "review_result": _decode(values[8], {}),
        "next_action": values[9],
        "created_at": values[10],
        "updated_at": values[11],
    }


def create_task(system_id: str, *, tenant_id: str = "default", graph: Any | None = None) -> dict[str, Any]:
    if not isinstance(system_id, str) or not system_id.strip():
        raise ValueError("system_id must be a non-empty string")
    tenant_id = _tenant(tenant_id)
    timestamp = datetime.now(timezone.utc).isoformat()
    task_id = f"task-{uuid4().hex}"
    _query(
        _graph(graph),
        CREATE_TASK,
        {
            "task_id": task_id,
            "tenant_id": tenant_id,
            "system_id": system_id.strip(),
            "timestamp": timestamp,
        },
    )
    return get_task(task_id, tenant_id=tenant_id, graph=graph)  # type: ignore[return-value]


def get_task(task_id: str, *, tenant_id: str = "default", graph: Any | None = None) -> dict[str, Any] | None:
    if not isinstance(task_id, str) or not task_id.strip():
        raise ValueError("task_id must be a non-empty string")
    tenant_id = _tenant(tenant_id)
    result = _query(
        _graph(graph),
        GET_TASK,
        {"task_id": task_id.strip(), "tenant_id": tenant_id},
    )
    rows = getattr(result, "result_set", ()) or ()
    return _task(rows[0]) if rows else None


def investigator_handoff(
    task_id: str,
    findings: list[dict[str, Any]],
    evidence_refs: list[str],
    *,
    tenant_id: str = "default",
    graph: Any | None = None,
) -> dict[str, Any]:
    tenant_id = _tenant(tenant_id)
    if not isinstance(findings, list) or not isinstance(evidence_refs, list):
        raise ValueError("findings and evidence_refs must be lists")
    timestamp = datetime.now(timezone.utc).isoformat()
    _query(
        _graph(graph),
        SAVE_INVESTIGATOR_HANDOFF,
        {
            "task_id": task_id,
            "tenant_id": tenant_id,
            "findings_json": _json(findings),
            "evidence_refs_json": _json(evidence_refs),
            "handoff_id": f"handoff-{uuid4().hex}",
            "timestamp": timestamp,
        },
    )
    task = get_task(task_id, tenant_id=tenant_id, graph=graph)
    if task is None:
        raise LookupError(f"Task '{task_id}' was not found for tenant '{tenant_id}'.")
    return task


def review_task(
    task_id: str,
    *,
    tenant_id: str = "default",
    graph: Any | None = None,
) -> dict[str, Any]:
    tenant_id = _tenant(tenant_id)
    graph = _graph(graph)
    task = get_task(task_id, tenant_id=tenant_id, graph=graph)
    if task is None:
        raise LookupError(f"Task '{task_id}' was not found for tenant '{tenant_id}'.")
    documents = {}
    refs = task["evidence_refs"]
    if refs:
        result = _query(graph, GET_DOCUMENTS, {"document_ids": refs})
        documents = {row[0]: row for row in (getattr(result, "result_set", ()) or ())}
    issues = []
    for finding in task["findings"]:
        claim = str(finding.get("claim") or finding.get("statement") or "")
        finding_refs = finding.get("evidence_refs") or refs
        for ref in finding_refs:
            document = documents.get(ref)
            if document is None:
                issues.append({"claim": claim, "source_id": ref, "reason": "Cited source was not found."})
                continue
            content = str(document[3] or "").lower()
            terms = [term for term in claim.lower().split() if len(term) > 4]
            if terms and not any(term in content for term in terms):
                issues.append({"claim": claim, "source_id": ref, "reason": "Cited source does not support the claim."})
    review = {
        "approved": not issues,
        "issues": issues,
        "checked_findings": len(task["findings"]),
    }
    timestamp = datetime.now(timezone.utc).isoformat()
    _query(
        graph,
        SAVE_REVIEW,
        {
            "task_id": task_id,
            "tenant_id": tenant_id,
            "status": "reviewed" if not issues else "needs_revision",
            "review_status": "approved" if not issues else "flagged",
            "review_result_json": json.dumps(review, separators=(",", ":"), sort_keys=True),
            "next_action": "close" if not issues else "revise_findings",
            "handoff_id": f"handoff-{uuid4().hex}",
            "timestamp": timestamp,
        },
    )
    return get_task(task_id, tenant_id=tenant_id, graph=graph)  # type: ignore[return-value]
