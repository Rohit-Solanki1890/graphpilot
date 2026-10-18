"""Repeatable synthetic data for local GraphPilot development."""

from __future__ import annotations

from typing import Any

from .connection import get_graph
from .schema import initialize_schema

NODES = {
    "Person": [
        {"id": "person-ava", "name": "Ava Patel", "role": "Staff Backend Engineer"},
        {"id": "person-ben", "name": "Ben Ortiz", "role": "Site Reliability Engineer"},
        {"id": "person-cleo", "name": "Cleo Nguyen", "role": "Security Engineer"},
        {"id": "person-dan", "name": "Dan Brooks", "role": "Product Engineer"},
        {"id": "person-eli", "name": "Eli Morgan", "role": "Data Engineer"},
    ],
    "Team": [
        {"id": "team-platform", "name": "Platform Engineering"},
        {"id": "team-payments", "name": "Payments"},
        {"id": "team-security", "name": "Security Engineering"},
        {"id": "team-data", "name": "Data Infrastructure"},
    ],
    "Project": [
        {"id": "project-checkout-reliability", "name": "Checkout Reliability", "status": "active"},
        {"id": "project-fraud-signals", "name": "Fraud Signals", "status": "active"},
        {"id": "project-observability", "name": "Observability Refresh", "status": "complete"},
    ],
    "System": [
        {"id": "system-checkout", "name": "Checkout", "description": "Customer payment orchestration.", "status": "degraded"},
        {"id": "system-payments-api", "name": "Payments API", "description": "Payment authorization service.", "status": "healthy"},
        {"id": "system-risk-engine", "name": "Risk Engine", "description": "Fraud and risk scoring service.", "status": "healthy"},
        {"id": "system-event-stream", "name": "Event Stream", "description": "Internal event transport.", "status": "healthy"},
        {"id": "system-observability", "name": "Observability", "description": "Metrics, logs, and traces platform.", "status": "healthy"},
    ],
    "Incident": [
        {"id": "incident-checkout-timeouts", "title": "Checkout authorization timeouts", "status": "investigating", "severity": "SEV-2", "description": "Intermittent authorization timeouts during peak traffic."},
        {"id": "incident-risk-lag", "title": "Risk score event lag", "status": "resolved", "severity": "SEV-3", "description": "Risk events were delayed by consumer backlog."},
        {"id": "incident-metrics-gap", "title": "Missing checkout metrics", "status": "monitoring", "severity": "SEV-3", "description": "A deployment dropped a subset of request labels."},
    ],
    "Document": [
        {"id": "doc-checkout-runbook", "title": "Checkout service runbook", "source": "internal://docs/checkout-runbook", "content": "Check Payments API latency, event stream backlog, and authorization timeout rate."},
        {"id": "doc-risk-architecture", "title": "Risk engine architecture", "source": "internal://docs/risk-architecture", "content": "Checkout sends purchase context to Risk Engine through Payments API events."},
        {"id": "doc-incident-timeouts", "title": "Authorization timeout incident notes", "source": "internal://incidents/checkout-timeouts", "content": "Initial evidence points to downstream event pressure rather than payment provider errors."},
    ],
    "Decision": [
        {
            "id": "decision-async-risk-events",
            "title": "Route risk scoring asynchronously via Event Stream",
            "status": "active",
            "rationale": "Decouple Checkout from synchronous Risk Engine latency spikes during peak traffic.",
            "decided_at": "2026-09-10",
        },
        {
            "id": "decision-checkout-timeout-budget",
            "title": "Enforce 2000ms Checkout authorization timeout budget",
            "status": "active",
            "rationale": "Fail fast and surface downstream Payments API backpressure before queue saturation.",
            "decided_at": "2026-10-01",
        },
        {
            "id": "decision-legacy-timeout-5000ms",
            "title": "Use 5000ms synchronous Checkout timeout",
            "status": "superseded",
            "rationale": "Initial launch timeout threshold prior to high-volume traffic.",
            "decided_at": "2026-03-15",
        },
    ],
}

RELATIONSHIPS = (
    ("person-ava", "MEMBER_OF", "team-payments"),
    ("person-ben", "MEMBER_OF", "team-platform"),
    ("person-cleo", "MEMBER_OF", "team-security"),
    ("person-dan", "MEMBER_OF", "team-payments"),
    ("person-eli", "MEMBER_OF", "team-data"),
    ("person-ava", "WORKED_ON", "project-checkout-reliability"),
    ("person-ben", "WORKED_ON", "project-checkout-reliability"),
    ("person-dan", "WORKED_ON", "project-fraud-signals"),
    ("person-cleo", "WORKED_ON", "project-fraud-signals"),
    ("person-eli", "WORKED_ON", "project-observability"),
    ("team-payments", "OWNS", "system-checkout"),
    ("team-payments", "OWNS", "system-payments-api"),
    ("team-security", "OWNS", "system-risk-engine"),
    ("team-platform", "OWNS", "system-event-stream"),
    ("team-platform", "OWNS", "system-observability"),
    ("project-checkout-reliability", "USES", "system-checkout"),
    ("project-checkout-reliability", "USES", "system-payments-api"),
    ("project-fraud-signals", "USES", "system-checkout"),
    ("project-fraud-signals", "USES", "system-risk-engine"),
    ("project-observability", "USES", "system-observability"),
    ("system-checkout", "DEPENDS_ON", "system-payments-api"),
    ("system-checkout", "DEPENDS_ON", "system-risk-engine"),
    ("system-payments-api", "DEPENDS_ON", "system-event-stream"),
    ("system-observability", "DEPENDS_ON", "system-event-stream"),
    ("incident-checkout-timeouts", "INVOLVES", "system-checkout"),
    ("incident-checkout-timeouts", "INVOLVES", "system-payments-api"),
    ("incident-risk-lag", "INVOLVES", "system-risk-engine"),
    ("incident-risk-lag", "INVOLVES", "system-event-stream"),
    ("incident-metrics-gap", "INVOLVES", "system-observability"),
    ("doc-checkout-runbook", "DESCRIBES", "system-checkout"),
    ("doc-risk-architecture", "DESCRIBES", "system-risk-engine"),
    ("doc-incident-timeouts", "DESCRIBES", "system-checkout"),
    ("decision-async-risk-events", "AFFECTS", "system-checkout"),
    ("decision-async-risk-events", "AFFECTS", "system-risk-engine"),
    ("decision-async-risk-events", "DECIDED_BY", "person-ava"),
    ("decision-async-risk-events", "DOCUMENTED_IN", "doc-risk-architecture"),
    ("decision-checkout-timeout-budget", "AFFECTS", "system-checkout"),
    ("decision-checkout-timeout-budget", "AFFECTS", "system-payments-api"),
    ("decision-checkout-timeout-budget", "DECIDED_BY", "person-ben"),
    ("decision-checkout-timeout-budget", "DOCUMENTED_IN", "doc-checkout-runbook"),
    ("decision-checkout-timeout-budget", "SUPERSEDES", "decision-legacy-timeout-5000ms"),
)


def _label_for(identifier: str) -> str:
    for label, records in NODES.items():
        if any(record["id"] == identifier for record in records):
            return label
    raise ValueError(f"Unknown seed identifier: {identifier}")


def seed_graph(graph: Any | None = None) -> Any:
    """Insert the synthetic graph using MERGE, without deleting existing data."""
    graph = graph or get_graph()
    initialize_schema(graph)
    for label, records in NODES.items():
        for record in records:
            properties = ", ".join(f"{key}: ${key}" for key in record)
            graph.query(
                f"MERGE (n:{label} {{id: $id}}) SET n += {{{properties}}}",
                params=record,
            )
    for source, relation, target in RELATIONSHIPS:
        source_label = _label_for(source)
        target_label = _label_for(target)
        graph.query(
            f"MATCH (a:{source_label} {{id: $source_id}}), (b:{target_label} {{id: $target_id}}) "
            f"MERGE (a)-[r:{relation}]->(b) SET r.weight = 1",
            params={"source_id": source, "target_id": target},
        )
    return graph


if __name__ == "__main__":
    seed_graph()
    print("Synthetic GraphPilot graph seeded.")
