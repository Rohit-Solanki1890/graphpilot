"""Investigation tools built on the GraphPilot graph data-access layer."""

from __future__ import annotations

from typing import Any

from app.graph import (
    find_system_experts,
    get_blast_radius,
    get_memory_context,
    get_related_incidents,
    get_system_decisions,
    get_system_documents,
    get_system_overview,
    get_system_paths,
)
from .explanation import explain_investigation, standardize_findings


def _result_template() -> dict[str, Any]:
    return {
        "system": None,
        "summary": "",
        "findings": [],
        "related_incidents": [],
        "dependencies": [],
        "experts": [],
        "evidence": [],
        "paths": [],
        "recommended_responders": [],
        "memory_context": {
            "prior_investigations": [],
            "prior_findings": [],
            "playbooks": [],
        },
        "memory_conflicts": [],
        "playbook": None,
        "procedure": {"completed_steps": [], "remaining_steps": []},
        "unknowns": [],
    }


def investigate_system(
    system_id: str,
    *,
    tenant_id: str = "default",
    depth: int = 3,
) -> dict[str, Any]:
    """Return a traceable, graph-grounded investigation for one system."""
    overview = get_system_overview(system_id)
    result = _result_template()
    if overview is None:
        result["summary"] = f"System '{system_id}' was not found in the graph."
        result["unknowns"] = [f"No graph data exists for system '{system_id}'."]
        return result

    experts = find_system_experts(system_id)
    documents = get_system_documents(system_id)
    paths = get_system_paths(system_id)
    memory_context = (
        get_memory_context(system_id)
        if tenant_id == "default"
        else get_memory_context(system_id, tenant_id=tenant_id)
    )
    try:
        decisions = get_system_decisions(system_id)
    except Exception:
        decisions = []
    try:
        blast_radius = get_blast_radius(system_id, depth=depth)
    except Exception:
        blast_radius = []

    incidents = overview.get("incidents") or []
    dependencies = overview.get("dependencies") or []
    owners = overview.get("owners") or []
    projects = overview.get("projects") or []

    result["system"] = {
        key: overview.get(key)
        for key in ("id", "name", "description", "status")
    }
    result["related_incidents"] = incidents
    result["dependencies"] = dependencies
    result["experts"] = experts
    result["evidence"] = documents
    result["paths"] = paths
    if decisions:
        result["decisions"] = decisions
    if blast_radius:
        result["blast_radius"] = blast_radius
    result["memory_context"] = memory_context
    result["playbook"] = (memory_context.get("playbooks") or [None])[0]
    if experts:
        responder = experts[0]
        result["recommended_responders"] = [
            {
                "id": responder.get("id"),
                "name": responder.get("name"),
                "role": responder.get("role"),
                "kind": "recommendation",
                "reason": (
                    "Worked on a project connected to this system; confirm "
                    "availability and ownership before paging."
                ),
                "entity_ids": [system_id, responder.get("id")],
                "relationships": ["(Person)-[:WORKED_ON]->(Project)-[:USES]->(System)"],
            }
        ]

    findings: list[dict[str, Any]] = []
    if overview.get("status") is not None:
        findings.append(
            {
                "kind": "fact",
                "statement": f"System status is '{overview['status']}'.",
                "entity_ids": [system_id],
                "relationships": [],
            }
        )
    for owner in owners:
        findings.append(
            {
                "kind": "fact",
                "statement": f"System is owned by {owner.get('name')}.",
                "entity_ids": [system_id, owner.get("id")],
                "relationships": ["(Team)-[:OWNS]->(System)"],
            }
        )
    for dependency in dependencies:
        findings.append(
            {
                "kind": "fact",
                "statement": f"System depends on {dependency.get('name')}.",
                "entity_ids": [system_id, dependency.get("id")],
                "relationships": ["(System)-[:DEPENDS_ON]->(System)"],
            }
        )
    for hop_dep in blast_radius:
        if (hop_dep.get("hops") or 1) > 1:
            via_str = " -> ".join(str(v) for v in (hop_dep.get("via") or []))
            findings.append(
                {
                    "kind": "fact",
                    "statement": f"Transitive dependency ({hop_dep.get('hops')} hops): {hop_dep.get('name')} via {via_str}.",
                    "entity_ids": hop_dep.get("path_ids") or [system_id, hop_dep.get("id")],
                    "relationships": ["(System)-[:DEPENDS_ON*]->(System)"],
                }
            )
    for incident in incidents:
        findings.append(
            {
                "kind": "fact",
                "statement": f"Related incident: {incident.get('title')}.",
                "entity_ids": [system_id, incident.get("id")],
                "relationships": ["(Incident)-[:INVOLVES]->(System)"],
            }
        )
    for decision in decisions:
        author = decision.get("decided_by") or "unknown author"
        doc_id = decision.get("document_id")
        findings.append(
            {
                "kind": "fact",
                "statement": (
                    f"Recorded decision '{decision.get('title')}' ({decision.get('status')}) "
                    f"by {author}."
                ),
                "entity_ids": [
                    item
                    for item in (system_id, decision.get("id"), decision.get("author_id"), doc_id)
                    if item
                ],
                "relationships": ["(Decision)-[:AFFECTS]->(System)", "(Decision)-[:DECIDED_BY]->(Person)"],
                "evidence_ids": [doc_id] if doc_id else [],
            }
        )
    for path in paths:
        node_ids = [
            node.get("id")
            for node in path.get("nodes", [])
            if isinstance(node, dict) and node.get("id")
        ]
        relationship_types = [
            relationship.get("type")
            for relationship in path.get("relationships", [])
            if isinstance(relationship, dict) and relationship.get("type")
        ]
        findings.append(
            {
                "kind": "fact",
                "statement": f"Observed {path.get('kind', 'graph')} path through connected entities.",
                "entity_ids": node_ids,
                "relationships": relationship_types,
                "path": path,
            }
        )
    if incidents and dependencies:
        findings.append(
            {
                "kind": "hypothesis",
                "statement": (
                    "The dependency path is a possible investigation area for the "
                    "related incidents; the graph does not verify causation."
                ),
                "entity_ids": [system_id]
                + [item.get("id") for item in incidents + dependencies],
                "relationships": [
                    "(Incident)-[:INVOLVES]->(System)",
                    "(System)-[:DEPENDS_ON]->(System)",
                ],
            }
        )
    result["findings"] = findings
    for finding in findings:
        finding["fact_status"] = (
            "hypothesis" if finding.get("kind") == "hypothesis" else "verified"
        )
        finding["provenance"] = {
            "system_id": system_id,
            "evidence_ids": finding.get("evidence_ids") or [item.get("id") for item in documents if item.get("id")],
            "path": finding.get("path"),
        }
    result["findings"] = standardize_findings(
        findings,
        system_id=system_id,
        evidence=documents,
        unknowns=result["unknowns"],
    )

    current_by_entities = {
        tuple(sorted(str(item) for item in finding.get("entity_ids") or [])): finding
        for finding in findings
        if finding.get("entity_ids")
    }
    conflicts = []
    for prior in memory_context.get("prior_findings") or []:
        key = tuple(sorted(str(item) for item in prior.get("entity_ids") or []))
        current = current_by_entities.get(key)
        if not current or not key:
            continue
        prior_status = prior.get("fact_status") or prior.get("kind")
        current_status = current.get("fact_status") or current.get("kind") or (
            "hypothesis" if current.get("kind") == "hypothesis" else "verified"
        )
        if prior_status != current_status or prior.get("description") != current.get("statement"):
            conflicts.append(
                {
                    "kind": "conflict",
                    "prior_investigation_id": prior.get("source_investigation_id"),
                    "entity_ids": list(key),
                    "prior_status": prior_status,
                    "current_status": current_status,
                    "prior_statement": prior.get("description"),
                    "current_statement": current.get("statement"),
                    "message": "Historical and current findings differ; review both sources.",
                }
            )
    result["memory_conflicts"] = conflicts

    unknowns = []
    if not owners:
        unknowns.append("No owning team was found in the graph.")
    if not incidents:
        unknowns.append("No related incidents were found in the graph.")
    if not dependencies:
        unknowns.append("No direct dependencies were found in the graph.")
    if not documents:
        unknowns.append("No documents describing this system were found in the graph.")
    if not experts:
        unknowns.append("No project experts were found in the graph.")
    if conflicts:
        unknowns.append(
            "Prior investigation findings conflict with current observations and require review."
        )
    result["unknowns"] = unknowns

    steps = (result["playbook"] or {}).get("steps") or []
    completed = []
    if system_id and overview.get("status") is not None:
        completed.append(steps[0] if steps else "Verify the target system and current status.")
    if incidents or dependencies:
        completed.append(steps[1] if len(steps) > 1 else "Inspect incidents and dependencies.")
    if owners or experts:
        completed.append(steps[2] if len(steps) > 2 else "Identify owners and experts.")
    if documents or paths:
        completed.append(steps[3] if len(steps) > 3 else "Review evidence and graph paths.")
    if findings:
        completed.append(steps[4] if len(steps) > 4 else "Record facts, hypotheses, and unknowns.")
    result["procedure"] = {
        "playbook_id": (result["playbook"] or {}).get("id"),
        "completed_steps": completed,
        "remaining_steps": [step for step in steps if step not in completed],
    }

    owner_names = ", ".join(owner.get("name", "unknown") for owner in owners) or "unknown"
    result["summary"] = (
        f"{overview.get('name', system_id)} is {overview.get('status', 'without a recorded status')} "
        f"and is owned by {owner_names}. "
        f"The graph contains {len(incidents)} related incident(s), "
        f"{len(dependencies)} direct dependency(ies), and {len(documents)} document(s)."
    )
    result["explanation"] = explain_investigation(
        result,
        tool_name="investigate_system",
        tool_reason="The request targeted a system and required connected graph evidence.",
    )
    return result
