"""FalkorDB connection factory with optional multigraph tenant isolation."""

from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv
from falkordb import FalkorDB

load_dotenv()


def get_graph(tenant_id: str | None = None) -> Any:
    """Return a FalkorDB graph handle, supporting multigraph tenant isolation."""
    client = FalkorDB(
        host=os.getenv("FALKORDB_HOST", "localhost"),
        port=int(os.getenv("FALKORDB_PORT", "6379")),
    )

    base_graph = os.getenv("FALKORDB_GRAPH", "graphpilot")
    use_multigraph = os.getenv("GRAPHPILOT_MULTIGRAPH_TENANCY", "").lower() in {
        "1",
        "true",
        "yes",
    }
    if use_multigraph and tenant_id and tenant_id.strip() and tenant_id.strip() != "default":
        graph_name = f"{base_graph}:{tenant_id.strip()}"
    else:
        graph_name = base_graph
    return client.select_graph(graph_name)


if __name__ == "__main__":
    graph = get_graph()
    result = graph.query(
        """
        MATCH (s:System {id: 'system-checkout'})
        RETURN s.name
        """
    )
    print("FalkorDB connection successful!")
    print("Query result:", result.result_set)
