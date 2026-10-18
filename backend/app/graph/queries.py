"""Parameterized Cypher queries, FalkorDB graph algorithms, and data-access API."""

from __future__ import annotations

from typing import Any, Iterable

from redis.exceptions import RedisError

from .connection import get_graph

FIND_SYSTEM = """
MATCH (s:System {id: $system_id})
RETURN s.id AS id, s.name AS name, s.description AS description, s.status AS status
"""

FIND_SYSTEM_BY_NAME = """
MATCH (s:System)
WHERE toLower(s.name) = toLower($system_name)
RETURN s.id AS id, s.name AS name, s.description AS description, s.status AS status
ORDER BY s.id
"""

FIND_SYSTEM_OWNER = """
MATCH (s:System {id: $system_id})<-[:OWNS]-(t:Team)
RETURN t.id AS id, t.name AS name
ORDER BY t.id
"""

FIND_SYSTEM_DEPENDENCIES = """
MATCH (s:System {id: $system_id})-[:DEPENDS_ON]->(dependency:System)
RETURN dependency.id AS id, dependency.name AS name,
       dependency.description AS description, dependency.status AS status
ORDER BY dependency.id
"""

FIND_SYSTEM_INCIDENTS = """
MATCH (incident:Incident)-[:INVOLVES]->(s:System {id: $system_id})
RETURN incident.id AS id, incident.title AS title, incident.status AS status,
       incident.severity AS severity, incident.description AS description
ORDER BY incident.id
"""

FIND_SYSTEM_PROJECTS = """
MATCH (project:Project)-[:USES]->(s:System {id: $system_id})
RETURN project.id AS id, project.name AS name, project.status AS status
ORDER BY project.id
"""

FIND_SYSTEM_EXPERTS = """
MATCH (person:Person)-[:WORKED_ON]->(project:Project)-[:USES]->(s:System {id: $system_id})
RETURN DISTINCT person.id AS id, person.name AS name, person.role AS role
ORDER BY person.id
"""

FIND_PEOPLE_FOR_INCIDENT = """
MATCH (incident:Incident {id: $incident_id})-[:INVOLVES]->(system:System)
MATCH (project:Project)-[:USES]->(system)
MATCH (person:Person)-[:WORKED_ON]->(project)
WITH incident, project, person,
     collect(DISTINCT {
         id: system.id,
         name: system.name
     }) AS related_systems
RETURN
    incident.id AS incident_id,
    incident.title AS incident_title,
    incident.status AS incident_status,
    incident.severity AS incident_severity,
    project.id AS project_id,
    project.name AS project_name,
    person.id AS person_id,
    person.name AS employee_name,
    person.role AS role,
    related_systems,
    ['INVOLVES', 'USES', 'WORKED_ON'] AS evidence_relationships
ORDER BY project.id, person.id
"""

FIND_SYSTEM_DOCUMENTS = """
MATCH (document:Document)-[:DESCRIBES]->(s:System {id: $system_id})
RETURN document.id AS id, document.title AS title, document.source AS source,
       document.content AS content
ORDER BY document.id
"""

FIND_SYSTEM_PATHS = """
MATCH (incident:Incident)-[:INVOLVES]->(system:System {id: $system_id})
OPTIONAL MATCH (system)-[:DEPENDS_ON]->(dependency:System)
WITH incident, system, dependency
WHERE dependency IS NOT NULL
RETURN 'incident_dependency' AS kind,
       [
           {id: incident.id, label: 'Incident'},
           {id: system.id, label: 'System'},
           {id: dependency.id, label: 'System'}
       ] AS nodes,
       [
           {source_id: incident.id, target_id: system.id, type: 'INVOLVES', direction: 'outgoing'},
           {source_id: system.id, target_id: dependency.id, type: 'DEPENDS_ON', direction: 'outgoing'}
       ] AS relationships
UNION ALL
MATCH (incident:Incident)-[:INVOLVES]->(system:System {id: $system_id})
MATCH (owner:Team)-[:OWNS]->(system)
RETURN 'incident_owner' AS kind,
       [
           {id: incident.id, label: 'Incident'},
           {id: system.id, label: 'System'},
           {id: owner.id, label: 'Team'}
       ] AS nodes,
       [
           {source_id: incident.id, target_id: system.id, type: 'INVOLVES', direction: 'outgoing'},
           {source_id: owner.id, target_id: system.id, type: 'OWNS', direction: 'incoming'}
       ] AS relationships
UNION ALL
MATCH (incident:Incident)-[:INVOLVES]->(system:System {id: $system_id})
MATCH (project:Project)-[:USES]->(system)
MATCH (person:Person)-[:WORKED_ON]->(project)
RETURN 'incident_project_expert' AS kind,
       [
           {id: incident.id, label: 'Incident'},
           {id: system.id, label: 'System'},
           {id: project.id, label: 'Project'},
           {id: person.id, label: 'Person'}
       ] AS nodes,
       [
           {source_id: incident.id, target_id: system.id, type: 'INVOLVES', direction: 'outgoing'},
           {source_id: project.id, target_id: system.id, type: 'USES', direction: 'incoming'},
           {source_id: person.id, target_id: project.id, type: 'WORKED_ON', direction: 'incoming'}
       ] AS relationships
ORDER BY kind
"""

FIND_SYSTEM_OVERVIEW = """
MATCH (s:System {id: $system_id})
OPTIONAL MATCH (owner:Team)-[:OWNS]->(s)
OPTIONAL MATCH (project:Project)-[:USES]->(s)
OPTIONAL MATCH (s)-[:DEPENDS_ON]->(dependency:System)
OPTIONAL MATCH (incident:Incident)-[:INVOLVES]->(s)
RETURN s.id AS id, s.name AS name, s.description AS description, s.status AS status,
       collect(DISTINCT {id: owner.id, name: owner.name}) AS owners,
       collect(DISTINCT {id: project.id, name: project.name, status: project.status}) AS projects,
       collect(DISTINCT {id: dependency.id, name: dependency.name, status: dependency.status}) AS dependencies,
       collect(DISTINCT {id: incident.id, title: incident.title, status: incident.status,
                         severity: incident.severity}) AS incidents
"""

RESOLVE_ENTITY = """
MATCH (n)
WHERE n.id = $target
   OR toLower(coalesce(n.name, '')) = toLower($target)
   OR toLower(coalesce(n.title, '')) = toLower($target)
RETURN n.id AS id,
       labels(n)[0] AS label,
       coalesce(n.name, n.title, n.id) AS name,
       coalesce(n.status, n.role, '') AS status,
       coalesce(n.description, n.rationale, n.content, '') AS description
ORDER BY n.id
LIMIT 1
"""

FIND_SYSTEM_DECISIONS = """
MATCH (d:Decision)-[:AFFECTS]->(s:System {id: $system_id})
OPTIONAL MATCH (d)-[:DECIDED_BY]->(p:Person)
OPTIONAL MATCH (d)-[:DOCUMENTED_IN]->(doc:Document)
OPTIONAL MATCH (d)-[:SUPERSEDES]->(old:Decision)
RETURN d.id AS id,
       d.title AS title,
       d.status AS status,
       d.rationale AS rationale,
       d.decided_at AS decided_at,
       p.id AS author_id,
       p.name AS decided_by,
       doc.id AS document_id,
       doc.title AS document_title,
       doc.source AS document_source,
       old.id AS supersedes_id,
       old.title AS supersedes_title
ORDER BY d.decided_at DESC, d.id ASC
"""

ALGO_SHORTEST_PATH = """
MATCH (a {id: $source_id}), (b {id: $target_id})
CALL algo.SPpaths({
    sourceNode: a,
    targetNode: b,
    relTypes: ['MEMBER_OF', 'WORKED_ON', 'OWNS', 'USES', 'DEPENDS_ON', 'INVOLVES', 'DESCRIBES', 'AFFECTS', 'DECIDED_BY', 'DOCUMENTED_IN', 'SUPERSEDES'],
    relDirection: 'both',
    weightProp: 'weight',
    pathCount: 1
})
YIELD path, pathWeight
RETURN [n IN nodes(path) | {id: n.id, label: labels(n)[0], name: coalesce(n.name, n.title, n.id)}] AS nodes,
       [r IN relationships(path) | {type: type(r)}] AS relationships,
       pathWeight AS hops
"""

CYPHER_SHORTEST_PATH = """
MATCH (a {id: $source_id}), (b {id: $target_id})
MATCH path = shortestPath((a)-[*..6]-(b))
RETURN [n IN nodes(path) | {id: n.id, label: labels(n)[0], name: coalesce(n.name, n.title, n.id)}] AS nodes,
       [r IN relationships(path) | {type: type(r)}] AS relationships,
       length(path) AS hops
LIMIT 1
"""

ALGO_PAGERANK_SYSTEMS = """
CALL algo.pageRank('System', 'DEPENDS_ON')
YIELD node, score
RETURN node.id AS id, node.name AS name, node.status AS status, score
ORDER BY score DESC, id ASC
LIMIT $limit
"""

CENTRALITY_FALLBACK_SYSTEMS = """
MATCH (s:System)
OPTIONAL MATCH (upstream:System)-[:DEPENDS_ON*1..3]->(s)
OPTIONAL MATCH (proj:Project)-[:USES]->(s)
WITH s, count(DISTINCT upstream) AS dependent_systems, count(DISTINCT proj) AS dependent_projects
RETURN s.id AS id,
       s.name AS name,
       s.status AS status,
       (dependent_systems * 0.35 + dependent_projects * 0.15 + 0.15) AS score
ORDER BY score DESC, id ASC
LIMIT $limit
"""

EXPLORE_ENTITY_NEIGHBORHOOD = """
MATCH (n {id: $entity_id})-[r]-(m)
RETURN type(r) AS relationship,
       CASE WHEN startNode(r) = n THEN 'outgoing' ELSE 'incoming' END AS direction,
       m.id AS neighbor_id,
       labels(m)[0] AS neighbor_label,
       coalesce(m.name, m.title, m.id) AS neighbor_name,
       coalesce(m.status, m.role, '') AS neighbor_status
ORDER BY relationship, neighbor_id
LIMIT 25
"""

_ALLOWED_DEPTHS = {1: "1..1", 2: "1..2", 3: "1..3", 4: "1..4"}


def _validate_id(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("system_id must be a non-empty string")
    return value.strip()


def _run(query: str, system_id: str, graph: Any | None = None) -> Any:
    validated_id = _validate_id(system_id)
    graph = graph if graph is not None else get_graph()
    try:
        return graph.query(query, params={"system_id": validated_id})
    except RedisError as exc:
        raise RuntimeError(f"FalkorDB query failed for system '{system_id}'") from exc


def _rows(result: Any, fields: Iterable[str]) -> list[dict[str, Any]]:
    fields = tuple(fields)
    converted = []
    for row in getattr(result, "result_set", ()) or ():
        values = list(row) if isinstance(row, (list, tuple)) else [row]
        converted.append({key: _plain(value) for key, value in zip(fields, values)})
    return converted


def _plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def get_system(system_id: str, graph: Any | None = None) -> dict[str, Any] | None:
    rows = _rows(_run(FIND_SYSTEM, system_id, graph), ("id", "name", "description", "status"))
    return rows[0] if rows else None


def get_system_by_name(system_name: str, graph: Any | None = None) -> dict[str, Any] | None:
    if not isinstance(system_name, str) or not system_name.strip():
        raise ValueError("system_name must be a non-empty string")
    graph = graph if graph is not None else get_graph()
    try:
        result = graph.query(
            FIND_SYSTEM_BY_NAME,
            params={"system_name": system_name.strip()},
        )
    except RedisError as exc:
        raise RuntimeError(f"FalkorDB query failed for system name '{system_name}'") from exc
    rows = _rows(result, ("id", "name", "description", "status"))
    return rows[0] if rows else None


def get_system_owner(system_id: str, graph: Any | None = None) -> list[dict[str, Any]]:
    return _rows(_run(FIND_SYSTEM_OWNER, system_id, graph), ("id", "name"))


def get_system_dependencies(system_id: str, graph: Any | None = None) -> list[dict[str, Any]]:
    return _rows(
        _run(FIND_SYSTEM_DEPENDENCIES, system_id, graph),
        ("id", "name", "description", "status"),
    )


def get_related_incidents(system_id: str, graph: Any | None = None) -> list[dict[str, Any]]:
    return _rows(
        _run(FIND_SYSTEM_INCIDENTS, system_id, graph),
        ("id", "title", "status", "severity", "description"),
    )


def get_system_projects(system_id: str, graph: Any | None = None) -> list[dict[str, Any]]:
    return _rows(_run(FIND_SYSTEM_PROJECTS, system_id, graph), ("id", "name", "status"))


def find_system_experts(system_id: str, graph: Any | None = None) -> list[dict[str, Any]]:
    return _rows(_run(FIND_SYSTEM_EXPERTS, system_id, graph), ("id", "name", "role"))


def get_system_documents(system_id: str, graph: Any | None = None) -> list[dict[str, Any]]:
    return _rows(
        _run(FIND_SYSTEM_DOCUMENTS, system_id, graph),
        ("id", "title", "source", "content"),
    )


def get_system_paths(system_id: str, graph: Any | None = None) -> list[dict[str, Any]]:
    """Return bounded, explicit paths from incidents through system context."""
    return _rows(_run(FIND_SYSTEM_PATHS, system_id, graph), ("kind", "nodes", "relationships"))


def get_system_overview(system_id: str, graph: Any | None = None) -> dict[str, Any] | None:
    fields = ("id", "name", "description", "status", "owners", "projects", "dependencies", "incidents")
    rows = _rows(_run(FIND_SYSTEM_OVERVIEW, system_id, graph), fields)
    return rows[0] if rows else None


def get_people_for_incident(
    incident_id: str,
    graph: Any | None = None,
) -> list[dict[str, Any]]:
    """Find people who worked on projects using systems involved in an incident."""
    if not isinstance(incident_id, str) or not incident_id.strip():
        raise ValueError("incident_id must be a non-empty string")

    validated_id = incident_id.strip()
    graph = graph if graph is not None else get_graph()

    try:
        result = graph.query(
            FIND_PEOPLE_FOR_INCIDENT,
            params={"incident_id": validated_id},
        )
    except RedisError as exc:
        raise RuntimeError(
            f"FalkorDB query failed for incident '{validated_id}'"
        ) from exc

    return _rows(
        result,
        (
            "incident_id",
            "incident_title",
            "incident_status",
            "incident_severity",
            "project_id",
            "project_name",
            "person_id",
            "employee_name",
            "role",
            "related_systems",
            "evidence_relationships",
        ),
    )


def resolve_entity(target: str, graph: Any | None = None) -> dict[str, Any] | None:
    """Resolve any graph entity (System, Person, Team, Project, Incident, Document, Decision) by ID or name."""
    if not isinstance(target, str) or not target.strip():
        raise ValueError("target must be a non-empty string")
    cleaned = target.strip()
    graph = graph if graph is not None else get_graph()
    try:
        result = graph.query(RESOLVE_ENTITY, params={"target": cleaned})
    except RedisError as exc:
        raise RuntimeError(f"FalkorDB entity resolution failed for '{cleaned}'") from exc
    rows = _rows(result, ("id", "label", "name", "status", "description"))
    return rows[0] if rows else None


def get_blast_radius(
    system_id: str,
    *,
    depth: int = 3,
    graph: Any | None = None,
) -> list[dict[str, Any]]:
    """Traverse multi-hop DEPENDS_ON relationships (*1..depth) to reveal transitive dependencies."""
    validated_id = _validate_id(system_id)
    if not isinstance(depth, int) or depth < 1 or depth > 4:
        raise ValueError("depth must be an integer between 1 and 4")
    bound = _ALLOWED_DEPTHS[depth]
    query = f"""
    MATCH path = (s:System {{id: $system_id}})-[:DEPENDS_ON*{bound}]->(dep:System)
    OPTIONAL MATCH (owner:Team)-[:OWNS]->(dep)
    OPTIONAL MATCH (inc:Incident)-[:INVOLVES]->(dep)
    RETURN dep.id AS id,
           dep.name AS name,
           dep.status AS status,
           length(path) AS hops,
           [n IN nodes(path) | coalesce(n.name, n.id)] AS via,
           [n IN nodes(path) | n.id] AS path_ids,
           collect(DISTINCT owner.name) AS owners,
           collect(DISTINCT inc.id) AS incident_ids
    ORDER BY hops ASC, id ASC
    """
    graph = graph if graph is not None else get_graph()
    try:
        result = graph.query(query, params={"system_id": validated_id})
    except RedisError as exc:
        raise RuntimeError(f"FalkorDB blast radius query failed for '{validated_id}'") from exc
    return _rows(
        result,
        ("id", "name", "status", "hops", "via", "path_ids", "owners", "incident_ids"),
    )


def get_system_decisions(
    system_id: str,
    graph: Any | None = None,
) -> list[dict[str, Any]]:
    """Retrieve architectural and operational decisions affecting a system with source provenance."""
    return _rows(
        _run(FIND_SYSTEM_DECISIONS, system_id, graph),
        (
            "id",
            "title",
            "status",
            "rationale",
            "decided_at",
            "author_id",
            "decided_by",
            "document_id",
            "document_title",
            "document_source",
            "supersedes_id",
            "supersedes_title",
        ),
    )


def find_shortest_path(
    source_id_or_name: str,
    target_id_or_name: str,
    graph: Any | None = None,
) -> dict[str, Any]:
    """Find the shortest relationship path between two entities using algo.SPpaths with shortestPath fallback."""
    if not isinstance(source_id_or_name, str) or not source_id_or_name.strip():
        raise ValueError("source_id_or_name must be a non-empty string")
    if not isinstance(target_id_or_name, str) or not target_id_or_name.strip():
        raise ValueError("target_id_or_name must be a non-empty string")
    graph = graph if graph is not None else get_graph()

    source = resolve_entity(source_id_or_name, graph)
    target = resolve_entity(target_id_or_name, graph)
    if source is None or target is None:
        missing = []
        if source is None:
            missing.append(source_id_or_name.strip())
        if target is None:
            missing.append(target_id_or_name.strip())
        return {
            "outcome": "unknown_entity",
            "missing_entities": missing,
            "source": source,
            "target": target,
            "algorithm": "algo.SPpaths",
            "hops": 0,
            "nodes": [],
            "relationships": [],
            "via": [],
        }

    params = {"source_id": source["id"], "target_id": target["id"]}
    algorithm_used = "algo.SPpaths"
    rows = []
    try:
        res = graph.query(ALGO_SHORTEST_PATH, params=params)
        rows = _rows(res, ("nodes", "relationships", "hops"))
    except Exception:
        rows = []

    if not rows:
        algorithm_used = "shortestPath"
        try:
            res = graph.query(CYPHER_SHORTEST_PATH, params=params)
            rows = _rows(res, ("nodes", "relationships", "hops"))
        except RedisError as exc:
            raise RuntimeError("FalkorDB shortest-path query failed") from exc

    if not rows:
        return {
            "outcome": "not_in_graph",
            "source": source,
            "target": target,
            "algorithm": algorithm_used,
            "hops": 0,
            "nodes": [],
            "relationships": [],
            "via": [],
        }

    best = rows[0]
    nodes = best.get("nodes") or []
    via = [f"{n.get('label', 'Entity')}:{n.get('name', n.get('id', 'unknown'))}" for n in nodes if isinstance(n, dict)]
    return {
        "outcome": "answered_with_path",
        "source": source,
        "target": target,
        "algorithm": algorithm_used,
        "hops": best.get("hops", max(0, len(nodes) - 1)),
        "nodes": nodes,
        "relationships": best.get("relationships") or [],
        "via": via,
    }


def rank_critical_systems(
    limit: int = 5,
    graph: Any | None = None,
) -> dict[str, Any]:
    """Rank load-bearing systems using FalkorDB algo.pageRank with structural centrality fallback."""
    if not isinstance(limit, int) or limit < 1 or limit > 50:
        raise ValueError("limit must be between 1 and 50")
    graph = graph if graph is not None else get_graph()
    algorithm = "algo.pageRank"
    rows = []
    try:
        res = graph.query(ALGO_PAGERANK_SYSTEMS, params={"limit": limit})
        rows = _rows(res, ("id", "name", "status", "score"))
    except Exception:
        rows = []

    if not rows:
        algorithm = "dependency_centrality"
        try:
            res = graph.query(CENTRALITY_FALLBACK_SYSTEMS, params={"limit": limit})
            rows = _rows(res, ("id", "name", "status", "score"))
        except RedisError as exc:
            raise RuntimeError("FalkorDB critical systems ranking failed") from exc

    return {
        "algorithm": algorithm,
        "systems": rows,
    }


def explore_entity_context(
    entity_id_or_name: str,
    graph: Any | None = None,
) -> dict[str, Any]:
    """Resolve any entity in the Company Brain graph and return its connected neighborhood."""
    graph = graph if graph is not None else get_graph()
    entity = resolve_entity(entity_id_or_name, graph)
    if entity is None:
        return {
            "outcome": "unknown_entity",
            "entity": None,
            "connections": [],
        }
    try:
        res = graph.query(EXPLORE_ENTITY_NEIGHBORHOOD, params={"entity_id": entity["id"]})
    except RedisError as exc:
        raise RuntimeError(f"FalkorDB neighborhood query failed for '{entity['id']}'") from exc
    connections = _rows(
        res,
        ("relationship", "direction", "neighbor_id", "neighbor_label", "neighbor_name", "neighbor_status"),
    )
    return {
        "outcome": "answered_with_path" if connections else "not_in_graph",
        "entity": entity,
        "connections": connections,
    }
