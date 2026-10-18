"""Minimal persistent investigation memory backed by FalkorDB."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from redis.exceptions import RedisError

from .connection import get_graph

SAVE_INVESTIGATION = """
MERGE (i:Investigation {id: $investigation_id})
SET i.status = $status,
    i.summary = $summary,
    i.created_at = $created_at,
    i.session_id = $session_id,
    i.system_id = $system_id,
    i.tenant_id = $tenant_id,
    i.outcome = $outcome,
    i.findings_json = $findings_json,
    i.evidence_ids_json = $evidence_ids_json,
    i.paths_json = $paths_json,
    i.recommendations_json = $recommendations_json,
    i.unknowns_json = $unknowns_json
WITH i
MATCH (s:System {id: $system_id})
MERGE (i)-[:ABOUT]->(s)
WITH i
MATCH (p:Playbook {id: $playbook_id})
MERGE (i)-[:FOLLOWED_PLAYBOOK]->(p)
RETURN i.id AS id
"""

SAVE_PLAYBOOK = """
MERGE (p:Playbook {id: $playbook_id})
SET p.name = $name,
    p.description = $description,
    p.steps_json = $steps_json,
    p.success_conditions_json = $success_conditions_json
"""

SAVE_FINDING = """
MERGE (f:Finding {id: $finding_id})
SET f.description = $description,
    f.kind = $kind,
    f.fact_status = $fact_status,
    f.confidence = $confidence,
    f.provenance_json = $provenance_json,
    f.observed_at = $observed_at,
    f.entity_ids_json = $entity_ids_json,
    f.relationships_json = $relationships_json,
    f.path_json = $path_json
WITH f
MATCH (i:Investigation {id: $investigation_id})
WHERE i.tenant_id = $tenant_id
MERGE (i)-[:FOUND]->(f)
RETURN f.id AS id
"""

LINK_EVIDENCE = """
MATCH (i:Investigation {id: $investigation_id})
WHERE i.tenant_id = $tenant_id
MATCH (d:Document {id: $document_id})
MERGE (i)-[:USED_EVIDENCE]->(d)
"""

LINK_FINDING_SYSTEM = """
MATCH (f:Finding {id: $finding_id})
MATCH (s:System {id: $system_id})
MERGE (f)-[:AFFECTS]->(s)
"""

GET_INVESTIGATION = """
MATCH (i:Investigation {id: $investigation_id})
WHERE i.tenant_id = $tenant_id
OPTIONAL MATCH (i)-[:FOUND]->(f:Finding)
RETURN i.id AS id, i.status AS status, i.summary AS summary,
       i.created_at AS created_at, i.session_id AS session_id,
       i.system_id AS system_id, i.outcome AS outcome,
       i.findings_json AS findings_json, i.evidence_ids_json AS evidence_ids_json,
       i.paths_json AS paths_json, i.recommendations_json AS recommendations_json,
       i.unknowns_json AS unknowns_json,
       collect({
           id: f.id, description: f.description, kind: f.kind,
           fact_status: f.fact_status, confidence: f.confidence,
           provenance_json: f.provenance_json, observed_at: f.observed_at,
           entity_ids_json: f.entity_ids_json,
           relationships_json: f.relationships_json, path_json: f.path_json
       }) AS findings
"""

GET_RECENT_INVESTIGATIONS = """
MATCH (i:Investigation {system_id: $system_id, tenant_id: $tenant_id})
OPTIONAL MATCH (i)-[:FOUND]->(f:Finding)
RETURN i.id AS id, i.status AS status, i.summary AS summary,
       i.created_at AS created_at, i.session_id AS session_id,
       i.system_id AS system_id, i.outcome AS outcome,
       i.findings_json AS findings_json, i.evidence_ids_json AS evidence_ids_json,
       i.paths_json AS paths_json, i.recommendations_json AS recommendations_json,
       i.unknowns_json AS unknowns_json,
       collect({
           id: f.id, description: f.description, kind: f.kind,
           fact_status: f.fact_status, confidence: f.confidence,
           provenance_json: f.provenance_json, observed_at: f.observed_at,
           entity_ids_json: f.entity_ids_json,
           relationships_json: f.relationships_json, path_json: f.path_json
       }) AS findings
ORDER BY i.created_at DESC
LIMIT $limit
"""

GET_PLAYBOOKS = """
MATCH (p:Playbook)
RETURN p.id AS id, p.name AS name, p.description AS description,
       p.steps_json AS steps_json, p.success_conditions_json AS success_conditions_json
ORDER BY p.id
"""

DEFAULT_PLAYBOOK = {
    "id": "playbook-system-incident",
    "name": "System incident investigation",
    "description": "Trace incidents through systems, dependencies, owners, experts, and evidence.",
    "steps": [
        "Verify the target system and current status.",
        "Inspect related incidents and direct dependencies.",
        "Identify the owning team and experienced project contributors.",
        "Review source documents and explicit graph paths.",
        "Record unknowns and label hypotheses separately from verified facts.",
    ],
    "success_conditions": [
        "At least one current system fact is verified.",
        "Every hypothesis retains supporting entity IDs or paths.",
        "Unknown or conflicting evidence is surfaced for review.",
    ],
}


def _graph(graph: Any | None) -> Any:
    return graph if graph is not None else get_graph()


def _query(graph: Any, query: str, params: dict[str, Any]) -> Any:
    try:
        return graph.query(query, params=params)
    except RedisError as exc:
        raise RuntimeError("FalkorDB investigation memory query failed") from exc


def _json(value: Any) -> str:
    return json.dumps(value or [], separators=(",", ":"), sort_keys=True)


def _decode(value: Any, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _validate_system_id(system_id: str) -> str:
    if not isinstance(system_id, str) or not system_id.strip():
        raise ValueError("system_id must be a non-empty string")
    return system_id.strip()


def _validate_tenant_id(tenant_id: str) -> str:
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise ValueError("tenant_id must be a non-empty string")
    return tenant_id.strip()


def _record(row: dict[str, Any]) -> dict[str, Any]:
    findings = row.get("findings") or _decode(row.get("findings_json"), [])
    if findings and isinstance(findings[0], dict) and "description" in findings[0]:
        findings = [
            {
                "id": item.get("id"),
                "kind": item.get("kind"),
                "fact_status": item.get("fact_status") or item.get("kind"),
                "description": item.get("description"),
                "confidence": item.get("confidence"),
                "provenance": _decode(item.get("provenance_json"), {}),
                "observed_at": item.get("observed_at"),
                "entity_ids": _decode(item.get("entity_ids_json"), []),
                "relationships": _decode(item.get("relationships_json"), []),
                "path": _decode(item.get("path_json"), None),
            }
            for item in findings
            if item.get("id")
        ]
    return {
        "investigation_id": row.get("id"),
        "created_at": row.get("created_at"),
        "session_id": row.get("session_id"),
        "system_id": row.get("system_id"),
        "status": row.get("status"),
        "summary": row.get("summary"),
        "outcome": row.get("outcome"),
        "findings": findings,
        "evidence_ids": _decode(row.get("evidence_ids_json"), []),
        "paths": _decode(row.get("paths_json"), []),
        "recommended_responders": _decode(row.get("recommendations_json"), []),
        "unknowns": _decode(row.get("unknowns_json"), []),
        "is_historical": True,
    }


def save_investigation(
    system_id: str,
    result: dict[str, Any],
    graph: Any | None = None,
    *,
    investigation_id: str | None = None,
    created_at: str | None = None,
    session_id: str | None = None,
    tenant_id: str = "default",
) -> dict[str, Any]:
    """Persist one investigation snapshot and return its stable memory record."""
    system_id = _validate_system_id(system_id)
    tenant_id = _validate_tenant_id(tenant_id)
    investigation_id = investigation_id or f"investigation-{uuid4().hex}"
    created_at = created_at or datetime.now(timezone.utc).isoformat()
    session_id = session_id or f"session-{uuid4().hex}"
    playbook = result.get("playbook") or DEFAULT_PLAYBOOK
    findings = result.get("findings") or []
    evidence_ids = [
        item.get("id")
        for item in result.get("evidence") or []
        if isinstance(item, dict) and item.get("id")
    ]
    paths = result.get("paths") or []
    params = {
        "investigation_id": investigation_id,
        "tenant_id": tenant_id,
        "status": "completed" if result.get("system") else "not_found",
        "summary": result.get("summary", ""),
        "created_at": created_at,
        "session_id": session_id,
        "system_id": system_id,
        "tenant_id": tenant_id,
        "outcome": result.get("outcome") or result.get("summary", ""),
        "findings_json": _json(findings),
        "evidence_ids_json": _json(evidence_ids),
        "paths_json": _json(paths),
        "recommendations_json": _json(result.get("recommended_responders")),
        "unknowns_json": _json(result.get("unknowns")),
        "playbook_id": playbook["id"],
    }
    graph = _graph(graph)
    _query(
        graph,
        SAVE_PLAYBOOK,
        {
            "playbook_id": playbook["id"],
            "name": playbook["name"],
            "description": playbook["description"],
            "steps_json": _json(playbook.get("steps")),
            "success_conditions_json": _json(playbook.get("success_conditions")),
        },
    )
    _query(graph, SAVE_INVESTIGATION, params)
    for index, finding in enumerate(findings):
        finding_id = f"{investigation_id}-finding-{index}"
        entity_ids = [item for item in finding.get("entity_ids") or [] if item]
        _query(
            graph,
            SAVE_FINDING,
            {
                "finding_id": finding_id,
                "investigation_id": investigation_id,
                "description": finding.get("statement", ""),
                "kind": finding.get("kind", "fact"),
                "fact_status": finding.get("fact_status") or (
                    "hypothesis" if finding.get("kind") == "hypothesis" else "verified"
                ),
                "confidence": finding.get("confidence"),
                "provenance_json": _json(
                    finding.get("provenance")
                    or {
                        "investigation_id": investigation_id,
                        "evidence_ids": evidence_ids,
                        "path": finding.get("path"),
                    }
                ),
                "observed_at": created_at,
                "entity_ids_json": _json(entity_ids),
                "relationships_json": _json(finding.get("relationships")),
                "path_json": _json(finding.get("path")) if finding.get("path") else "",
            },
        )
        for entity_id in entity_ids:
            if str(entity_id).startswith("system-"):
                _query(
                    graph,
                    LINK_FINDING_SYSTEM,
                    {"finding_id": finding_id, "system_id": entity_id},
                )
    for evidence_id in evidence_ids:
        _query(
            graph,
            LINK_EVIDENCE,
            {
                "investigation_id": investigation_id,
                "tenant_id": tenant_id,
                "document_id": evidence_id,
            },
        )
    return {
        "investigation_id": investigation_id,
        "created_at": created_at,
        "session_id": session_id,
        "system_id": system_id,
        "status": params["status"],
        "summary": params["summary"],
        "outcome": params["outcome"],
        "findings": findings,
        "evidence_ids": evidence_ids,
        "paths": paths,
        "recommended_responders": result.get("recommended_responders") or [],
        "unknowns": result.get("unknowns") or [],
        "playbook": playbook,
        "is_historical": True,
    }


def get_investigation(
    investigation_id: str,
    graph: Any | None = None,
    *,
    tenant_id: str = "default",
) -> dict[str, Any] | None:
    if not isinstance(investigation_id, str) or not investigation_id.strip():
        raise ValueError("investigation_id must be a non-empty string")
    tenant_id = _validate_tenant_id(tenant_id)
    result = _query(
        _graph(graph),
        GET_INVESTIGATION,
        {"investigation_id": investigation_id.strip(), "tenant_id": tenant_id},
    )
    rows = getattr(result, "result_set", ()) or ()
    if not rows:
        return None
    values = list(rows[0])
    fields = (
        "id", "status", "summary", "created_at", "session_id", "system_id", "outcome",
        "findings_json", "evidence_ids_json", "paths_json", "recommendations_json",
        "unknowns_json", "findings",
    )
    return _record(dict(zip(fields, values)))


def get_recent_investigations(
    system_id: str,
    graph: Any | None = None,
    *,
    limit: int = 10,
    tenant_id: str = "default",
) -> list[dict[str, Any]]:
    system_id = _validate_system_id(system_id)
    tenant_id = _validate_tenant_id(tenant_id)
    if not isinstance(limit, int) or limit < 1 or limit > 100:
        raise ValueError("limit must be between 1 and 100")
    result = _query(
        _graph(graph),
        GET_RECENT_INVESTIGATIONS,
        {"system_id": system_id, "tenant_id": tenant_id, "limit": limit},
    )
    fields = (
        "id", "status", "summary", "created_at", "session_id", "system_id", "outcome",
        "findings_json", "evidence_ids_json", "paths_json", "recommendations_json",
        "unknowns_json", "findings",
    )
    return [_record(dict(zip(fields, row))) for row in (getattr(result, "result_set", ()) or ())]


def get_playbooks(graph: Any | None = None) -> list[dict[str, Any]]:
    result = _query(_graph(graph), GET_PLAYBOOKS, {})
    records = []
    for row in getattr(result, "result_set", ()) or ():
        values = list(row)
        records.append(
            {
                "id": values[0],
                "name": values[1],
                "description": values[2],
                "steps": _decode(values[3], []),
                "success_conditions": _decode(values[4], []),
            }
        )
    return records or [DEFAULT_PLAYBOOK]


def get_memory_context(
    system_id: str,
    graph: Any | None = None,
    *,
    limit: int = 5,
    tenant_id: str = "default",
) -> dict[str, Any]:
    """Retrieve prior investigations and procedural guidance for a new investigation."""
    tenant_id = _validate_tenant_id(tenant_id)
    investigations = get_recent_investigations(
        _validate_system_id(system_id), graph, limit=limit, tenant_id=tenant_id
    )
    prior_findings = []
    for investigation in investigations:
        for finding in investigation.get("findings") or []:
            prior_findings.append(
                {
                    **finding,
                    "source_investigation_id": investigation["investigation_id"],
                    "source_created_at": investigation.get("created_at"),
                    "is_historical": True,
                }
            )
    return {
        "prior_investigations": investigations,
        "prior_findings": prior_findings,
        "playbooks": get_playbooks(graph),
    }
