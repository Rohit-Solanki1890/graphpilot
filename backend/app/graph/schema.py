"""Schema initialization for the GraphPilot engineering graph."""

from __future__ import annotations

from typing import Any

from .connection import get_graph

NODE_LABELS = (
    "Person",
    "Team",
    "Project",
    "System",
    "Incident",
    "Document",
    "Decision",
    "Investigation",
    "Finding",
    "Playbook",
    "Task",
    "Handoff",
    "Action",
    "Recommendation",
)


def initialize_schema(graph: Any | None = None) -> Any:
    """Create supported stable-ID constraints without changing graph data."""
    graph = graph or get_graph()
    existing = {
        (constraint.get("label"), tuple(constraint.get("properties") or []))
        for constraint in graph.list_constraints()
        if constraint.get("type") == "UNIQUE"
        and constraint.get("entitytype") in {"NODE", "node"}
    }
    for label in NODE_LABELS:
        if (label, ("id",)) not in existing:
            graph.create_node_unique_constraint(label, "id")
    return graph


if __name__ == "__main__":
    initialize_schema()
    print("GraphPilot schema initialized.")
