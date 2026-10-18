from types import SimpleNamespace

import pytest

from app.graph import queries
from app.graph.schema import NODE_LABELS, initialize_schema
from app.graph.seed import NODES, RELATIONSHIPS, seed_graph
from app.tools import investigation


class FakeGraph:
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.queries = []
        self.constraints = []

    def list_constraints(self):
        return self.constraints

    def create_node_unique_constraint(self, label, property_name):
        self.constraints.append(
            {
                "type": "UNIQUE",
                "label": label,
                "properties": [property_name],
                "entitytype": "NODE",
            }
        )

    def query(self, cypher, params=None):
        self.queries.append((cypher, params))
        for marker, rows in self.responses.items():
            if marker in cypher:
                return SimpleNamespace(result_set=rows)
        return SimpleNamespace(result_set=[])


def test_query_results_are_plain_dicts_and_empty_results_are_clean():
    graph = FakeGraph({"MATCH (s:System": [["system-checkout", "Checkout", "Payments", "healthy"]]})

    assert queries.get_system("system-checkout", graph) == {
        "id": "system-checkout",
        "name": "Checkout",
        "description": "Payments",
        "status": "healthy",
    }
    assert queries.get_system("missing", FakeGraph()) is None
    assert queries.get_system_projects("missing", FakeGraph()) == []
    assert queries.get_system_paths("missing", FakeGraph()) == []


def test_data_access_validates_ids_and_passes_parameters():
    graph = FakeGraph()

    with pytest.raises(ValueError):
        queries.get_system("  ", graph)

    queries.get_system_dependencies("system-checkout", graph)
    assert graph.queries[0][1] == {"system_id": "system-checkout"}
    assert "$system_id" in graph.queries[0][0]


def test_initialize_schema_is_idempotent():
    graph = FakeGraph()

    initialize_schema(graph)
    initialize_schema(graph)

    assert len(graph.constraints) == len(NODE_LABELS)


def test_seed_uses_merge_and_stable_relationships_without_deleting():
    graph = FakeGraph()

    seed_graph(graph)
    first_call_count = len(graph.queries)
    seed_graph(graph)

    assert sum(map(len, NODES.values())) + len(RELATIONSHIPS) == first_call_count
    assert all("MERGE" in query for query, _ in graph.queries)
    assert not any("DELETE" in query for query, _ in graph.queries)
    relationship_queries = graph.queries[-len(RELATIONSHIPS):]
    assert any("DEPENDS_ON" in query for query, _ in relationship_queries)
    assert any("INVOLVES" in query for query, _ in relationship_queries)


@pytest.mark.parametrize(
    ("function", "marker", "row", "expected"),
    [
        ("get_system_owner", "<-[:OWNS]-", ["team-payments", "Payments"], [{"id": "team-payments", "name": "Payments"}]),
        ("get_system_dependencies", "DEPENDS_ON", ["system-api", "API", "API service", "healthy"], [{"id": "system-api", "name": "API", "description": "API service", "status": "healthy"}]),
        ("get_related_incidents", "INVOLVES", ["incident-1", "Timeouts", "open", "SEV-2", "Slow"], [{"id": "incident-1", "title": "Timeouts", "status": "open", "severity": "SEV-2", "description": "Slow"}]),
        ("get_system_projects", "USES", ["project-1", "Checkout", "active"], [{"id": "project-1", "name": "Checkout", "status": "active"}]),
        ("find_system_experts", "WORKED_ON", ["person-1", "Ava", "Engineer"], [{"id": "person-1", "name": "Ava", "role": "Engineer"}]),
        ("get_system_documents", "DESCRIBES", ["doc-1", "Runbook", "internal://runbook", "Evidence"], [{"id": "doc-1", "title": "Runbook", "source": "internal://runbook", "content": "Evidence"}]),
    ],
)
def test_major_data_access_operations(function, marker, row, expected):
    graph = FakeGraph({marker: [row]})
    assert getattr(queries, function)("system-checkout", graph) == expected


def test_overview_returns_connected_graph_shape():
    row = [
        "system-checkout",
        "Checkout",
        "Payment orchestration",
        "degraded",
        [{"id": "team-payments", "name": "Payments"}],
        [{"id": "project-checkout", "name": "Checkout", "status": "active"}],
        [{"id": "system-api", "name": "Payments API", "status": "healthy"}],
        [{"id": "incident-1", "title": "Timeouts", "status": "open", "severity": "SEV-2"}],
    ]
    assert queries.get_system_overview("system-checkout", FakeGraph({"OPTIONAL MATCH": [row]})) == {
        "id": "system-checkout",
        "name": "Checkout",
        "description": "Payment orchestration",
        "status": "degraded",
        "owners": [{"id": "team-payments", "name": "Payments"}],
        "projects": [{"id": "project-checkout", "name": "Checkout", "status": "active"}],
        "dependencies": [{"id": "system-api", "name": "Payments API", "status": "healthy"}],
        "incidents": [{"id": "incident-1", "title": "Timeouts", "status": "open", "severity": "SEV-2"}],
    }


def test_system_paths_return_explicit_bounded_graph_paths():
    path = {
        "kind": "incident_dependency",
        "nodes": [
            {"id": "incident-1", "label": "Incident"},
            {"id": "system-checkout", "label": "System"},
            {"id": "system-api", "label": "System"},
        ],
        "relationships": [
            {"source_id": "incident-1", "target_id": "system-checkout", "type": "INVOLVES", "direction": "outgoing"},
            {"source_id": "system-checkout", "target_id": "system-api", "type": "DEPENDS_ON", "direction": "outgoing"},
        ],
    }
    graph = FakeGraph({"UNION ALL": [[path["kind"], path["nodes"], path["relationships"]]]})

    assert queries.get_system_paths("system-checkout", graph) == [path]
    query, params = graph.queries[0]
    assert "$system_id" in query
    assert "OPTIONAL MATCH (system)-[:DEPENDS_ON]->(dependency:System)" in query
    assert params == {"system_id": "system-checkout"}


def test_investigate_system_returns_traceable_facts_and_hypothesis(monkeypatch):
    monkeypatch.setattr(
        investigation,
        "get_system_overview",
        lambda system_id: {
            "id": system_id,
            "name": "Checkout",
            "description": "Payment orchestration",
            "status": "degraded",
            "owners": [{"id": "team-payments", "name": "Payments"}],
            "projects": [{"id": "project-checkout", "name": "Checkout", "status": "active"}],
            "dependencies": [{"id": "system-api", "name": "Payments API", "status": "healthy"}],
            "incidents": [{"id": "incident-timeout", "title": "Authorization timeouts", "status": "open", "severity": "SEV-2"}],
        },
    )
    monkeypatch.setattr(
        investigation,
        "find_system_experts",
        lambda system_id: [{"id": "person-ava", "name": "Ava Patel", "role": "Engineer"}],
    )
    monkeypatch.setattr(
        investigation,
        "get_system_documents",
        lambda system_id: [{"id": "doc-runbook", "title": "Runbook", "source": "internal://runbook", "content": "Check API latency."}],
    )
    monkeypatch.setattr(
        investigation,
        "get_system_paths",
        lambda system_id: [
            {
                "kind": "incident_dependency",
                "nodes": [
                    {"id": "incident-timeout", "label": "Incident"},
                    {"id": "system-checkout", "label": "System"},
                    {"id": "system-api", "label": "System"},
                ],
                "relationships": [
                    {"source_id": "incident-timeout", "target_id": "system-checkout", "type": "INVOLVES", "direction": "outgoing"},
                    {"source_id": "system-checkout", "target_id": "system-api", "type": "DEPENDS_ON", "direction": "outgoing"},
                ],
            }
        ],
    )
    monkeypatch.setattr(
        investigation,
        "get_memory_context",
        lambda system_id: {
            "prior_investigations": [],
            "prior_findings": [],
            "playbooks": [],
        },
    )

    result = investigation.investigate_system("system-checkout")

    assert result["system"]["id"] == "system-checkout"
    assert result["related_incidents"][0]["id"] == "incident-timeout"
    assert result["dependencies"][0]["id"] == "system-api"
    assert result["experts"][0]["id"] == "person-ava"
    assert result["recommended_responders"][0]["id"] == "person-ava"
    assert result["recommended_responders"][0]["kind"] == "recommendation"
    assert result["evidence"][0]["id"] == "doc-runbook"
    assert result["paths"][0]["kind"] == "incident_dependency"
    assert result["paths"][0]["relationships"][1]["type"] == "DEPENDS_ON"
    assert any(finding["kind"] == "fact" for finding in result["findings"])
    path_finding = next(finding for finding in result["findings"] if "path" in finding)
    assert path_finding["entity_ids"] == ["incident-timeout", "system-checkout", "system-api"]
    assert path_finding["relationships"] == ["INVOLVES", "DEPENDS_ON"]
    hypothesis = next(finding for finding in result["findings"] if finding["kind"] == "hypothesis")
    assert "does not verify causation" in hypothesis["statement"]
    assert "incident-timeout" in hypothesis["entity_ids"]


def test_investigate_system_missing_result_is_consistent(monkeypatch):
    monkeypatch.setattr(investigation, "get_system_overview", lambda system_id: None)

    result = investigation.investigate_system("system-missing")

    assert result == {
        "system": None,
        "summary": "System 'system-missing' was not found in the graph.",
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
        "unknowns": ["No graph data exists for system 'system-missing'."],
    }


def test_investigation_flags_changed_historical_finding(monkeypatch):
    monkeypatch.setattr(
        investigation,
        "get_system_overview",
        lambda system_id: {
            "id": system_id,
            "name": "Checkout",
            "description": "Payment orchestration",
            "status": "healthy",
            "owners": [],
            "projects": [],
            "dependencies": [],
            "incidents": [],
        },
    )
    monkeypatch.setattr(investigation, "find_system_experts", lambda system_id: [])
    monkeypatch.setattr(investigation, "get_system_documents", lambda system_id: [])
    monkeypatch.setattr(investigation, "get_system_paths", lambda system_id: [])
    monkeypatch.setattr(
        investigation,
        "get_memory_context",
        lambda system_id: {
            "prior_investigations": [{"investigation_id": "investigation-old"}],
            "prior_findings": [{
                "source_investigation_id": "investigation-old",
                "entity_ids": ["system-checkout"],
                "fact_status": "verified",
                "description": "System status is degraded.",
            }],
            "playbooks": [{
                "id": "playbook-system-incident",
                "steps": ["Verify the target system and current status."],
            }],
        },
    )

    result = investigation.investigate_system("system-checkout")

    assert result["memory_conflicts"][0]["prior_investigation_id"] == "investigation-old"
    assert "require review" in result["unknowns"][-1]
    assert result["procedure"]["completed_steps"]


def test_find_shortest_path_and_pagerank():
    graph = FakeGraph(
        {
            "MATCH (n)": [
                ["person-ava", "Person", "Ava Patel", "Staff Backend Engineer", ""],
            ],
            "CALL algo.SPpaths": [
                [
                    [
                        {"id": "person-ava", "label": "Person", "name": "Ava Patel"},
                        {"id": "project-checkout-reliability", "label": "Project", "name": "Checkout Reliability"},
                        {"id": "system-checkout", "label": "System", "name": "Checkout"},
                    ],
                    [{"type": "WORKED_ON"}, {"type": "USES"}],
                    2,
                ]
            ],
            "CALL algo.pageRank": [
                ["system-event-stream", "Event Stream", "healthy", 0.42],
                ["system-payments-api", "Payments API", "healthy", 0.31],
            ],
        }
    )
    path_res = queries.find_shortest_path("Ava Patel", "Checkout", graph)
    assert path_res["outcome"] == "answered_with_path"
    assert path_res["algorithm"] == "algo.SPpaths"
    assert path_res["hops"] == 2
    assert "Person:Ava Patel" in path_res["via"]

    ranked = queries.rank_critical_systems(limit=2, graph=graph)
    assert ranked["algorithm"] == "algo.pageRank"
    assert ranked["systems"][0]["id"] == "system-event-stream"


def test_blast_radius_and_system_decisions():
    graph = FakeGraph(
        {
            "DEPENDS_ON*1..3": [
                [
                    "system-event-stream",
                    "Event Stream",
                    "healthy",
                    2,
                    ["Checkout", "Payments API", "Event Stream"],
                    ["system-checkout", "system-payments-api", "system-event-stream"],
                    ["Platform Engineering"],
                    ["incident-risk-lag"],
                ]
            ],
            "MATCH (d:Decision)-[:AFFECTS]->": [
                [
                    "decision-checkout-timeout-budget",
                    "Enforce 2000ms Checkout authorization timeout budget",
                    "active",
                    "Fail fast during peak traffic.",
                    "2026-10-01",
                    "person-ben",
                    "Ben Ortiz",
                    "doc-checkout-runbook",
                    "Checkout service runbook",
                    "internal://docs/checkout-runbook",
                    "decision-legacy-timeout-5000ms",
                    "Use 5000ms synchronous Checkout timeout",
                ]
            ],
        }
    )
    blast = queries.get_blast_radius("system-checkout", depth=3, graph=graph)
    assert len(blast) == 1
    assert blast[0]["hops"] == 2
    assert blast[0]["id"] == "system-event-stream"

    decisions = queries.get_system_decisions("system-checkout", graph=graph)
    assert len(decisions) == 1
    assert decisions[0]["decided_by"] == "Ben Ortiz"
    assert decisions[0]["supersedes_id"] == "decision-legacy-timeout-5000ms"
