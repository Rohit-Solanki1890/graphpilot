from types import SimpleNamespace

from app.graph.memory import (
    get_investigation,
    get_recent_investigations,
    get_memory_context,
    save_investigation,
)


class MemoryGraph:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.queries = []

    def query(self, query, params=None):
        self.queries.append((query, params))
        return SimpleNamespace(result_set=self.rows)


def sample_result():
    return {
        "summary": "Checkout is degraded.",
        "system": {"id": "system-checkout"},
        "findings": [
            {
                "kind": "fact",
                "statement": "System status is degraded.",
                "entity_ids": ["system-checkout"],
                "relationships": [],
            },
            {
                "kind": "hypothesis",
                "statement": "Payments API may be involved.",
                "entity_ids": ["system-checkout", "system-payments-api"],
                "relationships": ["DEPENDS_ON"],
                "path": {"kind": "incident_dependency"},
            },
        ],
        "evidence": [{"id": "doc-checkout-runbook"}],
        "paths": [{"kind": "incident_dependency"}],
        "recommended_responders": [{"id": "person-ava", "kind": "recommendation"}],
        "unknowns": ["Deployment timing is unknown."],
    }


def test_save_investigation_writes_findings_evidence_and_paths_idempotently():
    graph = MemoryGraph()

    saved = save_investigation(
        "system-checkout",
        sample_result(),
        graph,
        investigation_id="investigation-test",
        created_at="2026-10-15T12:00:00+00:00",
    )

    assert saved["investigation_id"] == "investigation-test"
    assert saved["is_historical"] is True
    assert len(graph.queries) == 8
    assert "MERGE (p:Playbook" in graph.queries[0][0]
    assert "MERGE (i:Investigation" in graph.queries[1][0]
    assert "MERGE (f:Finding" in graph.queries[2][0]
    assert any(params.get("document_id") == "doc-checkout-runbook" for _, params in graph.queries)
    assert any(params.get("system_id") == "system-checkout" for _, params in graph.queries)


def test_retrieve_investigation_preserves_fact_and_hypothesis():
    rows = [[
        "investigation-test",
        "completed",
        "Checkout is degraded.",
        "2026-10-15T12:00:00+00:00",
        "session-test",
        "system-checkout",
        "Checkout is degraded.",
        "[]",
        '["doc-1"]',
        '[{"kind":"incident_dependency"}]',
        '[{"id":"person-ava","kind":"recommendation"}]',
        '["unknown"]',
        [
            {
                "id": "investigation-test-finding-0",
                "description": "Observed fact",
                "kind": "fact",
                "confidence": None,
                "entity_ids_json": '["system-checkout"]',
                "relationships_json": "[]",
                "path_json": "",
            },
            {
                "id": "investigation-test-finding-1",
                "description": "Historical hypothesis",
                "kind": "hypothesis",
                "confidence": None,
                "entity_ids_json": '["system-checkout"]',
                "relationships_json": '["DEPENDS_ON"]',
                "path_json": '{"kind":"incident_dependency"}',
            },
        ],
    ]]

    memory = get_investigation("investigation-test", MemoryGraph(rows))

    assert memory["is_historical"] is True
    assert [finding["kind"] for finding in memory["findings"]] == ["fact", "hypothesis"]
    assert memory["evidence_ids"] == ["doc-1"]
    assert memory["recommended_responders"][0]["id"] == "person-ava"
    assert memory["unknowns"] == ["unknown"]


def test_empty_memory_results_are_clean():
    graph = MemoryGraph()
    assert get_investigation("missing", graph) is None
    assert get_recent_investigations("system-checkout", graph) == []


def test_recent_memory_includes_findings_and_context_preserves_history():
    rows = [[
        "investigation-test",
        "completed",
        "Checkout is degraded.",
        "2026-10-15T12:00:00+00:00",
        "session-test",
        "system-checkout",
        "completed",
        "[]",
        "[]",
        "[]",
        "[]",
        "[]",
        [{
            "id": "finding-1",
            "description": "Historical hypothesis",
            "kind": "hypothesis",
            "fact_status": "hypothesis",
            "confidence": 0.6,
            "provenance_json": '{"evidence_ids":["doc-1"]}',
            "observed_at": "2026-10-15T12:00:00+00:00",
            "entity_ids_json": '["system-checkout"]',
            "relationships_json": "[]",
            "path_json": "",
        }],
    ]]
    graph = MemoryGraph(rows)

    context = get_memory_context("system-checkout", graph)

    assert context["prior_investigations"][0]["findings"][0]["fact_status"] == "hypothesis"
    assert context["prior_findings"][0]["is_historical"] is True
    assert context["prior_findings"][0]["source_investigation_id"] == "investigation-test"
    assert context["playbooks"]
