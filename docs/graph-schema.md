# GraphPilot graph schema

GraphPilot uses FalkorDB as a connected engineering knowledge layer. Stable string
IDs make evidence and relationships durable across seed runs and future
investigations. The schema is not a relational migration: `initialize_schema()`
only creates supported FalkorDB uniqueness constraints for node `id` properties.

## Nodes

| Label | Properties |
| --- | --- |
| `Person` | `id`, `name`, `role` |
| `Team` | `id`, `name` |
| `Project` | `id`, `name`, `status` |
| `System` | `id`, `name`, `description`, `status` |
| `Incident` | `id`, `title`, `status`, `severity`, `description` |
| `Document` | `id`, `title`, `source`, `content` |
| `Investigation` | `id`, `status`, `summary`, `created_at`, `session_id`, `system_id`, `outcome` |
| `Finding` | `id`, `description`, `confidence`, `kind`, `fact_status`, `provenance_json`, `observed_at` |
| `Playbook` | `id`, `name`, `description`, `steps_json`, `success_conditions_json` |

## Relationships

`Person -[:MEMBER_OF]-> Team`, `Person -[:WORKED_ON]-> Project`,
`Team -[:OWNS]-> System`, `Project -[:USES]-> System`,
`Incident -[:INVOLVES]-> System`, `Document -[:DESCRIBES]-> System`,
`System -[:DEPENDS_ON]-> System`, `Investigation -[:FOUND]-> Finding`,
`Investigation -[:USED_EVIDENCE]-> Document`, and
`Finding -[:AFFECTS]-> System`. Persisted investigations also use
`Investigation -[:ABOUT]-> System` to make their subject explicit and
`Investigation -[:FOLLOWED_PLAYBOOK]-> Playbook` to record the procedure used.

The direction is intentional: ownership and evidence can be followed toward a
system, while dependencies can be traversed downstream. Investigation and
finding labels are reserved for future persistence and are included in the
stable schema even though the seed focuses on organization context.

## Synthetic dataset

The seed contains five people across Payments, Platform, Security, and Data
Infrastructure; three projects; five connected systems; three incidents; and
three fictional documents. Checkout depends on Payments API and Risk Engine,
and Payments API depends on Event Stream. Projects, incidents, runbooks, and
engineers are connected to make ownership, impact, expertise, and evidence
queries useful.

Seeding uses `MERGE` by stable ID for nodes and relationships and never deletes
existing data. It is therefore safe to repeat locally:

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m app.graph.schema
PYTHONPATH=. .venv/bin/python -m app.graph.seed
```

Use `python` instead of `.venv/bin/python` when the dependencies are installed
in the active environment. Start FalkorDB first with `docker compose up -d`.

## Queries and Python API

All reusable Cypher definitions are in `backend/app/graph/queries.py`; user
values are passed as FalkorDB parameters, never interpolated. For example:

```cypher
MATCH (s:System {id: $system_id})-[:DEPENDS_ON]->(dependency:System)
RETURN dependency.id AS id, dependency.name AS name
```

with `{"system_id": "system-checkout"}`. The Python equivalent is:

```python
from app.graph import get_system_overview, get_system_documents

get_system_documents("system-checkout")
# [{"id": "doc-checkout-runbook", "title": "...", "source": "...", "content": "..."}]
get_system_overview("system-checkout")
# {"id": "...", "owners": [...], "projects": [...], "dependencies": [...], "incidents": [...]}
```

The API returns a dictionary for a found system or overview, `None` for a
missing single result, and lists (possibly empty) for collection queries.
FalkorDB 1.8.0 exposes `graph.query(cypher, params=...)` and parses rows through
`result_set`; the data layer projects scalar properties so callers receive
ordinary Python dictionaries and lists.

## Investigation use

An investigation can start at a degraded system, follow `DEPENDS_ON` to narrow
the blast radius, use `OWNS` and project paths to identify responsible teams
and experts, and use `INVOLVES` plus `DESCRIBES` to ground conclusions in
incidents and source documents. Stable document IDs and source URLs preserve
the evidence trail for a future orchestrator.

The first investigation tool is available without an LLM:

```python
from app.tools import investigate_system

investigation = investigate_system("system-checkout")
# {
#   "system": {"id": "system-checkout", "status": "degraded", ...},
#   "findings": [{"kind": "fact", "entity_ids": [...], ...}, ...],
#   "related_incidents": [...],
#   "dependencies": [...],
#   "experts": [...],
#   "evidence": [{"id": "doc-checkout-runbook", "source": "...", ...}],
#   "unknowns": [...]
# }
```

Findings marked `fact` are directly returned graph facts. Findings marked
`hypothesis` are explicitly labeled inferences and retain the involved entity
IDs and relationship types; the tool does not claim that a dependency caused
an incident.

Investigations also return bounded `paths`. For example:

```text
Incident:incident-checkout-timeouts
  -[:INVOLVES]->
System:system-checkout
  -[:DEPENDS_ON]->
System:system-payments-api
```

This path helps answer, “Which direct dependency should we inspect when
checkout authorization timeouts are under investigation?” It records observed
graph relationships, not proof that the dependency caused the incident.

The investigation also returns a deterministic `recommended_responders`
section. It selects a person already returned by the graph's
`WORKED_ON -> USES` expert traversal and labels the result as a recommendation,
not a verified on-call assignment:

```text
Potential responder: Ava Patel
Basis: Person -[:WORKED_ON]-> Project -[:USES]-> System
```

This supports the incident-commander question, “Who has relevant project
context to start investigating this system?” Availability and current
ownership still need confirmation.

The deterministic first orchestrator routes system investigations by name or
ID:

```python
from app.agent import run_turn

run_turn("Investigate Checkout")
# {
#   "message": "Checkout is degraded ...",
#   "tool_used": "investigate_system",
#   "tool_result": {"system": {...}, "findings": [...], ...},
#   "status": "success"
# }
```

Unsupported requests return `status: "unsupported"` and missing systems return
`status: "not_found"` without invoking the investigation tool.

## Optional Ollama agent loop

The existing deterministic router remains the default. To enable the optional
local Ollama tool-calling loop with `qwen3:4b`:

```bash
cd backend
GRAPHPILOT_AGENT_MODE=ollama \
PYTHONPATH=. .venv/bin/python -m app.tui
```

The loop exposes only four validated tools:
`investigate_system`, `get_system_overview`, `get_recent_investigations`, and
`get_investigation`. Python resolves names, validates arguments, dispatches the
existing graph functions, and sends their structured results back to Ollama.
The model never executes Python or arbitrary Cypher. If Ollama is unavailable,
the orchestrator falls back to the deterministic router and includes an
`llm_fallback` message in the response.

## Persistent investigation memory

Every successful `run_turn("investigate ...")` persists a snapshot in
FalkorDB. The `Investigation` node stores its stable ID, UTC `created_at`,
system ID, status, summary, serialized findings, evidence IDs, graph paths,
and unknowns. Each finding is a `Finding` node linked by `FOUND`, with its
`kind` (`fact` or `hypothesis`), description, entity IDs, relationships, and
optional path. Known document IDs are linked with `USED_EVIDENCE`; findings
are linked to referenced systems with `AFFECTS`.

Historical records are deliberately marked `is_historical: True` when
retrieved. Their facts and hypotheses are preserved as past observations and
are not silently treated as newly verified graph facts.

Milestone 2 adds three memory layers without changing the organization graph:

- **Episodic memory** stores each investigation session, outcome, findings,
  evidence IDs, paths, unknowns, and creation time.
- **Semantic memory** stores finding status (`verified`, `hypothesis`,
  `disproved`, or `unknown` when supplied), provenance, observed time, and
  supporting entity IDs/relationships.
- **Procedural memory** stores the `Playbook` used by an investigation, its
  ordered steps, and success conditions. The investigation result reports
  completed and remaining steps.

Before a new investigation is built, GraphPilot retrieves recent historical
investigations for the same system and the available playbooks. Historical
findings remain marked as historical context. If a current finding has the
same entity set but a different statement or status, the result adds a
`memory_conflicts` entry and an unknown requiring review; it does not overwrite
either observation or promote the old result to a current fact.

For example, a first investigation may save a hypothesis that
`system-payments-api` could be involved in a checkout timeout. A later
investigation returns that prior finding under `memory_context.prior_findings`
with its source investigation ID and `fact_status: "hypothesis"`. If the new
graph observation differs, the UI shows a memory conflict instead of silently
claiming that either version is correct.

```python
from app.agent import run_turn

saved = run_turn("investigate Checkout")
# saved["tool_result"]["investigation_id"] -> "investigation-..."

run_turn("recall investigation investigation-...")
run_turn("list investigations for Checkout")
```

The same operations can be run in separate backend processes:

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m app.graph.seed
PYTHONPATH=. .venv/bin/python -c \
  "from app.agent import run_turn; print(run_turn('investigate Checkout')['tool_result']['investigation_id'])"
PYTHONPATH=. .venv/bin/python -c \
  "from app.agent import run_turn; print(run_turn('list investigations for Checkout'))"
```

## Terminal UI

Launch the Textual interface from the backend directory:

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m app.tui
```

Enter requests such as `investigate Checkout`. The interface runs the
orchestrator in a worker thread, shows the status while FalkorDB is queried,
and presents facts, hypotheses, incidents, dependencies, experts, evidence,
and unknowns in separate sections. Use `Ctrl+L` to clear the conversation and
`Ctrl+C` to quit.

FalkorDB 1.8.0 supports node unique constraints through
`create_node_unique_constraint`; the initializer checks `list_constraints()`
before creating them. No unsupported relational foreign keys or migrations are
assumed. The Docker image remains the source of the server version, so use a
compatible FalkorDB image when deploying beyond local development.


## Decision provenance and FalkorDB graph algorithms

GraphPilot also models `Decision` nodes (`id`, `title`, `status`, `rationale`, `decided_at`) linked via:
- `(Decision)-[:AFFECTS]->(System)`
- `(Decision)-[:DECIDED_BY]->(Person)`
- `(Decision)-[:DOCUMENTED_IN]->(Document)`
- `(Decision)-[:SUPERSEDES]->(Decision)`

In addition to parameterized Cypher traversals, `backend/app/graph/queries.py` exposes:
- `get_blast_radius(system_id, depth=3)` using variable-length `[:DEPENDS_ON*1..3]` patterns.
- `find_shortest_path(source, target)` using `CALL algo.SPpaths(...)` with `shortestPath` fallback.
- `rank_critical_systems(limit=5)` using `CALL algo.pageRank('System', 'DEPENDS_ON')` with centrality fallback.
