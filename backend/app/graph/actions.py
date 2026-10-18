"""Approval-gated, auditable actions backed by FalkorDB."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from redis.exceptions import RedisError

from .connection import get_graph

ACTION_TYPES = {
    "create_follow_up_task",
    "assign_proposed_owner",
    "record_recommendation",
}

PROPOSE_ACTION = """
MERGE (a:Action {id: $action_id})
SET a.tenant_id = $tenant_id, a.type = $type, a.status = 'proposed',
    a.approval_required = true, a.payload_json = $payload_json,
    a.evidence_ids_json = $evidence_ids_json, a.rationale = $rationale,
    a.target_system_id = $target_system_id, a.created_at = $timestamp,
    a.updated_at = $timestamp
RETURN a.id AS id
"""

GET_ACTION = """
MATCH (a:Action {id: $action_id, tenant_id: $tenant_id})
RETURN a.id AS id, a.tenant_id AS tenant_id, a.type AS type, a.status AS status,
       a.approval_required AS approval_required, a.payload_json AS payload_json,
       a.evidence_ids_json AS evidence_ids_json, a.rationale AS rationale,
       a.target_system_id AS target_system_id, a.created_at AS created_at,
       a.updated_at AS updated_at, a.approved_at AS approved_at,
       a.executed_at AS executed_at, a.execution_result_json AS execution_result_json
"""

APPROVE_ACTION = """
MATCH (a:Action {id: $action_id, tenant_id: $tenant_id})
SET a.status = 'approved', a.approved_at = $timestamp, a.updated_at = $timestamp
RETURN a.id AS id
"""

REJECT_ACTION = """
MATCH (a:Action {id: $action_id, tenant_id: $tenant_id})
SET a.status = 'rejected', a.execution_result_json = $result_json,
    a.updated_at = $timestamp
RETURN a.id AS id
"""

EXECUTE_TASK_ACTION = """
MATCH (a:Action {id: $action_id, tenant_id: $tenant_id})
MATCH (s:System {id: $system_id})
MERGE (t:Task {id: $task_id})
SET t.tenant_id = $tenant_id, t.system_id = $system_id, t.status = 'assigned',
    t.assigned_role = 'investigator', t.next_action = 'follow_up',
    t.findings_json = '[]', t.evidence_refs_json = $evidence_refs_json,
    t.review_status = 'pending', t.created_at = $timestamp, t.updated_at = $timestamp
MERGE (a)-[:CREATED_TASK]->(t)
SET a.status = 'executed', a.execution_result_json = $result_json,
    a.executed_at = $timestamp, a.updated_at = $timestamp
RETURN a.id AS id
"""

EXECUTE_RECOMMENDATION = """
MATCH (a:Action {id: $action_id, tenant_id: $tenant_id})
MERGE (r:Recommendation {id: $recommendation_id})
SET r.tenant_id = $tenant_id, r.system_id = $system_id,
    r.text = $recommendation, r.evidence_ids_json = $evidence_ids_json,
    r.created_at = $timestamp
MERGE (a)-[:RECORDED_RECOMMENDATION]->(r)
SET a.status = 'executed', a.execution_result_json = $result_json,
    a.executed_at = $timestamp, a.updated_at = $timestamp
RETURN a.id AS id
"""

EXECUTE_ASSIGN_OWNER = """
MATCH (a:Action {id: $action_id, tenant_id: $tenant_id})
MATCH (t:Task {id: $task_id, tenant_id: $tenant_id})
SET t.proposed_owner_id = $owner_id, t.updated_at = $timestamp,
    a.status = 'executed', a.execution_result_json = $result_json,
    a.executed_at = $timestamp, a.updated_at = $timestamp
RETURN a.id AS id
"""


def _graph(graph: Any | None) -> Any:
    return graph if graph is not None else get_graph()


def _query(graph: Any, query: str, params: dict[str, Any]) -> Any:
    try:
        return graph.query(query, params=params)
    except RedisError as exc:
        raise RuntimeError("FalkorDB action query failed") from exc


def _tenant(tenant_id: str) -> str:
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise ValueError("tenant_id must be a non-empty string")
    return tenant_id.strip()


def _decode(value: Any, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _record(row: Any) -> dict[str, Any]:
    values = list(row)
    return {
        "action_id": values[0],
        "tenant_id": values[1],
        "type": values[2],
        "status": values[3],
        "approval_required": values[4],
        "payload": _decode(values[5], {}),
        "evidence_ids": _decode(values[6], []),
        "rationale": values[7],
        "target_system_id": values[8],
        "created_at": values[9],
        "updated_at": values[10],
        "approved_at": values[11],
        "executed_at": values[12],
        "execution_result": _decode(values[13], {}),
    }


def _validate_payload(action_type: str, payload: dict[str, Any]) -> None:
    if action_type not in ACTION_TYPES:
        raise ValueError(f"Unsupported action type: {action_type}")
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    if action_type == "create_follow_up_task" and not payload.get("title"):
        raise ValueError("create_follow_up_task requires a title")
    if action_type == "assign_proposed_owner" and (
        not payload.get("owner_id") or not payload.get("task_id")
    ):
        raise ValueError("assign_proposed_owner requires task_id and owner_id")
    if action_type == "record_recommendation" and not payload.get("recommendation"):
        raise ValueError("record_recommendation requires a recommendation")


def propose_action(
    action_type: str,
    payload: dict[str, Any],
    *,
    target_system_id: str,
    evidence_ids: list[str] | None = None,
    rationale: str = "",
    tenant_id: str = "default",
    graph: Any | None = None,
) -> dict[str, Any]:
    _validate_payload(action_type, payload)
    tenant_id = _tenant(tenant_id)
    timestamp = datetime.now(timezone.utc).isoformat()
    action_id = f"action-{uuid4().hex}"
    _query(
        _graph(graph),
        PROPOSE_ACTION,
        {
            "action_id": action_id,
            "tenant_id": tenant_id,
            "type": action_type,
            "payload_json": json.dumps(payload, separators=(",", ":"), sort_keys=True),
            "evidence_ids_json": json.dumps(evidence_ids or []),
            "rationale": rationale,
            "target_system_id": target_system_id,
            "timestamp": timestamp,
        },
    )
    return get_action(action_id, tenant_id=tenant_id, graph=graph)  # type: ignore[return-value]


def get_action(action_id: str, *, tenant_id: str = "default", graph: Any | None = None) -> dict[str, Any] | None:
    tenant_id = _tenant(tenant_id)
    result = _query(_graph(graph), GET_ACTION, {"action_id": action_id, "tenant_id": tenant_id})
    rows = getattr(result, "result_set", ()) or ()
    return _record(rows[0]) if rows else None


def execute_action(
    action_id: str,
    *,
    approve: bool = False,
    tenant_id: str = "default",
    graph: Any | None = None,
) -> dict[str, Any]:
    tenant_id = _tenant(tenant_id)
    graph = _graph(graph)
    action = get_action(action_id, tenant_id=tenant_id, graph=graph)
    if action is None:
        raise LookupError(f"Action '{action_id}' was not found for tenant '{tenant_id}'.")
    if action["status"] != "proposed":
        return action
    timestamp = datetime.now(timezone.utc).isoformat()
    if not approve:
        _query(
            graph,
            REJECT_ACTION,
            {
                "action_id": action_id,
                "tenant_id": tenant_id,
                "result_json": json.dumps({"reason": "Human approval was not granted."}),
                "timestamp": timestamp,
            },
        )
        return get_action(action_id, tenant_id=tenant_id, graph=graph)  # type: ignore[return-value]
    _query(graph, APPROVE_ACTION, {"action_id": action_id, "tenant_id": tenant_id, "timestamp": timestamp})
    action_type = action["type"]
    if action_type == "create_follow_up_task":
        payload = action["payload"]
        query = EXECUTE_TASK_ACTION
        params = {
            "action_id": action_id,
            "tenant_id": tenant_id,
            "system_id": action["target_system_id"],
            "task_id": f"task-{uuid4().hex}",
            "evidence_refs_json": json.dumps(action["evidence_ids"]),
            "result_json": json.dumps({"created": True, "title": payload["title"]}),
            "timestamp": timestamp,
        }
    elif action_type == "assign_proposed_owner":
        payload = action["payload"]
        query = EXECUTE_ASSIGN_OWNER
        params = {
            "action_id": action_id,
            "tenant_id": tenant_id,
            "task_id": payload.get("task_id"),
            "owner_id": payload["owner_id"],
            "result_json": json.dumps({"assigned": True, "owner_id": payload["owner_id"]}),
            "timestamp": timestamp,
        }
    else:
        payload = action["payload"]
        query = EXECUTE_RECOMMENDATION
        params = {
            "action_id": action_id,
            "tenant_id": tenant_id,
            "recommendation_id": f"recommendation-{action_id.removeprefix('action-')}",
            "system_id": action["target_system_id"],
            "recommendation": payload["recommendation"],
            "evidence_ids_json": json.dumps(action["evidence_ids"]),
            "result_json": json.dumps({"recorded": True, "type": action_type}),
            "timestamp": timestamp,
        }
    _query(graph, query, params)
    return get_action(action_id, tenant_id=tenant_id, graph=graph)  # type: ignore[return-value]
