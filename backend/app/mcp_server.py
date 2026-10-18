"""Typed MCP tools for GraphPilot's investigation, graph algorithm, and coordination workflows."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from app.graph import (
    create_task,
    execute_action,
    explore_entity_context,
    find_shortest_path,
    get_action,
    get_blast_radius,
    get_investigation,
    get_memory_context,
    get_recent_investigations,
    get_system_decisions,
    get_system_overview,
    get_task,
    investigator_handoff,
    propose_action,
    rank_critical_systems,
    review_task,
)
from app.tools import investigate_system

mcp = FastMCP("GraphPilot")


@mcp.tool()
def investigate_system_tool(system_id: str, tenant_id: str = "default") -> dict[str, Any]:
    """Investigate one known system and return graph facts, paths, decisions, evidence, and hypotheses."""
    return investigate_system(system_id, tenant_id=tenant_id)


@mcp.tool()
def get_system_overview_tool(system_id: str, tenant_id: str = "default") -> dict[str, Any] | None:
    """Read the bounded owner, project, dependency, incident, and expert overview for a system."""
    return get_system_overview(system_id)


@mcp.tool()
def resolve_entity_tool(entity_id_or_name: str) -> dict[str, Any]:
    """Resolve any Person, Team, Project, System, Incident, Document, or Decision and list its connections."""
    return explore_entity_context(entity_id_or_name)


@mcp.tool()
def find_shortest_path_tool(source: str, target: str) -> dict[str, Any]:
    """Run FalkorDB shortest-path analysis (algo.SPpaths / shortestPath) between any two entities."""
    return find_shortest_path(source, target)


@mcp.tool()
def rank_critical_systems_tool(limit: int = 5) -> dict[str, Any]:
    """Run FalkorDB PageRank (algo.pageRank) over System DEPENDS_ON edges to rank load-bearing systems."""
    return rank_critical_systems(limit=limit)


@mcp.tool()
def get_blast_radius_tool(system_id: str, depth: int = 3) -> list[dict[str, Any]]:
    """Traverse multi-hop DEPENDS_ON relationships (*1..depth) to surface transitive dependencies."""
    return get_blast_radius(system_id, depth=depth)


@mcp.tool()
def get_system_decisions_tool(system_id: str) -> list[dict[str, Any]]:
    """Trace architectural and operational decisions affecting a system back to authors and documents."""
    return get_system_decisions(system_id)


@mcp.tool()
def get_memory_context_tool(
    system_id: str, tenant_id: str = "default", limit: int = 5
) -> dict[str, Any]:
    """Retrieve tenant-scoped historical investigations and procedural playbooks."""
    return get_memory_context(system_id, limit=limit, tenant_id=tenant_id)


@mcp.tool()
def get_investigation_tool(investigation_id: str, tenant_id: str = "default") -> dict[str, Any] | None:
    """Recall one historical investigation without treating it as a new graph fact."""
    return get_investigation(investigation_id, tenant_id=tenant_id)


@mcp.tool()
def get_recent_investigations_tool(
    system_id: str, tenant_id: str = "default", limit: int = 10
) -> list[dict[str, Any]]:
    """List recent tenant-scoped investigations for a system."""
    return get_recent_investigations(system_id, tenant_id=tenant_id, limit=limit)


@mcp.tool()
def create_coordination_task(system_id: str, tenant_id: str = "default") -> dict[str, Any]:
    """Coordinator: create a persistent investigator/reviewer task for a system."""
    return create_task(system_id, tenant_id=tenant_id)


@mcp.tool()
def get_coordination_task(task_id: str, tenant_id: str = "default") -> dict[str, Any] | None:
    """Read a tenant-scoped shared task so a handoff can resume after restart."""
    return get_task(task_id, tenant_id=tenant_id)


@mcp.tool()
def submit_investigator_handoff(
    task_id: str,
    findings: list[dict[str, Any]],
    evidence_refs: list[str],
    tenant_id: str = "default",
) -> dict[str, Any]:
    """Investigator: persist claims and source IDs, then hand the task to the reviewer."""
    return investigator_handoff(
        task_id, findings, evidence_refs, tenant_id=tenant_id
    )


@mcp.tool()
def review_coordination_task(task_id: str, tenant_id: str = "default") -> dict[str, Any]:
    """Reviewer: check cited documents and flag unsupported claims before coordinator closure."""
    return review_task(task_id, tenant_id=tenant_id)


@mcp.tool()
def propose_controlled_action(
    action_type: str,
    target_system_id: str,
    payload: dict[str, Any],
    evidence_ids: list[str] | None = None,
    rationale: str = "",
    tenant_id: str = "default",
) -> dict[str, Any]:
    """Propose a validated action; proposals never execute without approval."""
    return propose_action(
        action_type,
        payload,
        target_system_id=target_system_id,
        evidence_ids=evidence_ids,
        rationale=rationale,
        tenant_id=tenant_id,
    )


@mcp.tool()
def get_controlled_action(action_id: str, tenant_id: str = "default") -> dict[str, Any] | None:
    """Read a tenant-scoped proposed or executed action and its audit status."""
    return get_action(action_id, tenant_id=tenant_id)


@mcp.tool()
def approve_controlled_action(
    action_id: str, approved: bool = False, tenant_id: str = "default"
) -> dict[str, Any]:
    """Approve or reject an action explicitly; approved actions execute in Python."""
    return execute_action(action_id, approve=approved, tenant_id=tenant_id)


if __name__ == "__main__":
    mcp.run()
