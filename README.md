# GraphPilot

> A graph-powered AI agent for connected-data investigation, persistent multi-agent memory, and organizational intelligence on **FalkorDB**.

GraphPilot is a submission for **Graph Hacks: Context for AI Agents** ([WeMakeDevs × FalkorDB Hackathon](https://www.wemakedevs.org/hackathons/falkordb)).
It demonstrates how an AI agent uses **FalkorDB** as its active context layer to traverse multi-hop system dependencies, run graph algorithms (`algo.SPpaths` and `algo.pageRank`), persist episodic/semantic/procedural memory across sessions, coordinate handoffs between specialized agent roles, trace architectural decisions back to their source documents, and gate consequential actions behind human approval.

## Hackathon Tracks Covered

| Track | How GraphPilot Qualifies |
| :--- | :--- |
| **Track 01: Agents That Act on Connected Data** | Variable-length multi-hop blast radius (`*1..depth`), FalkorDB graph algorithms (`CALL algo.SPpaths`, `CALL algo.pageRank`), 17-tool FastMCP server (`mcp_server.py`), 11-tool bounded Ollama registry (`ollama_agent.py`), approval-gated actions (`actions.py`), and claim-level path explanations (`explanation.py`). |
| **Track 02: Agent Memory and Coordination** | 3-tier memory stored as FalkorDB nodes (`Investigation` episodic, `Finding` semantic with conflict detection, `Playbook` procedural), Coordinator → Investigator → Reviewer handoffs (`tasks.py`), thread-safe concurrency with retry logic (`test_concurrent_tasks.py`), and tenant isolation (`tenant_id` predicates + optional `select_graph("graphpilot:<tenant>")` multigraph isolation). |
| **Track 03: Company Brain** | Connects `Person`, `Team`, `Project`, `System`, `Incident`, `Document`, and `Decision` nodes in one graph; answers ownership (`OWNS`), expertise (`WORKED_ON -> USES`), and decision provenance (`DECIDED_BY`, `DOCUMENTED_IN`, `SUPERSEDES`) with verifiable source citations. |

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                        Textual TUI                           │
│  Chat · Evidence · Graph Paths · Handoffs · Approval Widget  │
└──────────────────────────────┬───────────────────────────────┘
                               │
┌──────────────────────────────▼───────────────────────────────┐
│                      Agent Orchestrator                      │
│        Deterministic Router  ←→  Ollama Tool Loop            │
│               (env GRAPHPILOT_AGENT_MODE=ollama)             │
└───────────────┬──────────────────────────────┬───────────────┘
                │ validated tool dispatch only │
┌───────────────▼──────────────┐  ┌────────────▼───────────────┐
│   Graph & Algorithm Tools    │  │  Memory, Tasks & Actions   │
│ investigate_system           │  │ save/get/list_investigation│
│ get_blast_radius (*1..depth) │  │ get_memory_context         │
│ find_shortest_path (SPpaths) │  │ get_playbooks              │
│ rank_critical_systems (PR)   │  │ create/handoff/review_task │
│ get_system_decisions         │  │ propose/execute_action     │
│ resolve_entity / overview    │  │                            │
└───────────────┬──────────────┘  └────────────┬───────────────┘
                └──────────────┬───────────────┘
                               │
                    ┌──────────▼──────────┐
                    │      FalkorDB       │
                    │  Systems · People   │
                    │  Teams · Projects   │
                    │  Incidents · Docs   │
                    │  Decisions · Tasks  │
                    │  Memory · Actions   │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │   FastMCP Server    │
                    │   17 Typed Tools    │
                    │  (stdio transport)  │
                    └─────────────────────┘
```

## Graph Data Model

### Node Labels

| Label | Key Properties | Track Role |
| :--- | :--- | :--- |
| `Person` | `id`, `name`, `role` | Company Brain (Track 03) |
| `Team` | `id`, `name` | Company Brain (Track 03) |
| `Project` | `id`, `name`, `status` | Company Brain (Track 03) |
| `System` | `id`, `name`, `description`, `status` | Connected Data & Company Brain (Tracks 01 & 03) |
| `Incident` | `id`, `title`, `status`, `severity`, `description` | Connected Data & Company Brain (Tracks 01 & 03) |
| `Document` | `id`, `title`, `source`, `content` | Source Evidence (Tracks 01, 02 & 03) |
| `Decision` | `id`, `title`, `status`, `rationale`, `decided_at` | Decision Provenance (Track 03) |
| `Investigation` | `id`, `status`, `summary`, `created_at`, `session_id`, `system_id`, `outcome`, `tenant_id` | Episodic Memory (Track 02) |
| `Finding` | `id`, `description`, `kind`, `fact_status`, `confidence`, `provenance_json`, `observed_at`, `entity_ids_json` | Semantic Memory (Track 02) |
| `Playbook` | `id`, `name`, `description`, `steps_json`, `success_conditions_json` | Procedural Memory (Track 02) |
| `Task` | `id`, `tenant_id`, `system_id`, `status`, `assigned_role`, `review_status`, `next_action` | Multi-Agent Shared State (Track 02) |
| `Handoff` | `id`, `tenant_id`, `task_id`, `from_role`, `to_role`, `created_at` | Agent Coordination Audit (Track 02) |
| `Action` | `id`, `tenant_id`, `type`, `status`, `approval_required`, `payload_json`, `evidence_ids_json` | Controlled Action Execution (Track 01) |
| `Recommendation` | `id`, `tenant_id`, `system_id`, `text`, `evidence_ids_json`, `created_at` | Action Outcome (Track 01) |

### Relationships

```text
(Person)-[:MEMBER_OF {weight: 1}]->(Team)
(Person)-[:WORKED_ON {weight: 1}]->(Project)
(Team)-[:OWNS {weight: 1}]->(System)
(Project)-[:USES {weight: 1}]->(System)
(System)-[:DEPENDS_ON {weight: 1}]->(System)
(Incident)-[:INVOLVES {weight: 1}]->(System)
(Document)-[:DESCRIBES {weight: 1}]->(System)
(Decision)-[:AFFECTS {weight: 1}]->(System)
(Decision)-[:DECIDED_BY {weight: 1}]->(Person)
(Decision)-[:DOCUMENTED_IN {weight: 1}]->(Document)
(Decision)-[:SUPERSEDES {weight: 1}]->(Decision)
(Investigation)-[:ABOUT]->(System)
(Investigation)-[:FOUND]->(Finding)
(Investigation)-[:USED_EVIDENCE]->(Document)
(Investigation)-[:FOLLOWED_PLAYBOOK]->(Playbook)
(Finding)-[:AFFECTS]->(System)
(Task)-[:HAS_HANDOFF]->(Handoff)
(Action)-[:CREATED_TASK]->(Task)
(Action)-[:RECORDED_RECOMMENDATION]->(Recommendation)
```

## Core Cypher Queries & FalkorDB Graph Algorithms (Rule 10 Reference)

All queries and graph algorithms live in `backend/app/graph/queries.py`, `backend/app/graph/memory.py`, `backend/app/graph/tasks.py`, and `backend/app/graph/actions.py`. The LLM never writes raw Cypher; it selects from validated Python/MCP tools that execute these parameterized operations:

### 1. Variable-Length Multi-Hop Blast Radius (`*1..depth`)
Reveals both direct (1-hop) and transitive (2..4-hop) downstream dependencies (e.g., `Checkout -> Payments API -> Event Stream`), along with owning teams and active incidents at each hop:
```cypher
MATCH path = (s:System {id: $system_id})-[:DEPENDS_ON*1..3]->(dep:System)
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
```

### 2. Shortest-Path Graph Algorithm (`CALL algo.SPpaths` + `shortestPath`)
Discovers and explains the shortest relationship route connecting any two entities across people, projects, teams, systems, incidents, documents, and decisions:
```cypher
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
```

### 3. Load-Bearing System Ranking (`CALL algo.pageRank`)
Identifies structurally critical systems across the dependency graph:
```cypher
CALL algo.pageRank('System', 'DEPENDS_ON')
YIELD node, score
RETURN node.id AS id, node.name AS name, node.status AS status, score
ORDER BY score DESC, id ASC
LIMIT $limit
```

### 4. Decision Provenance & Temporal Superseding (Company Brain)
Traces architectural decisions affecting a system back to the engineer who decided them, the source document where they are recorded, and any older decision they superseded:
```cypher
MATCH (d:Decision)-[:AFFECTS]->(s:System {id: $system_id})
OPTIONAL MATCH (d)-[:DECIDED_BY]->(p:Person)
OPTIONAL MATCH (d)-[:DOCUMENTED_IN]->(doc:Document)
OPTIONAL MATCH (d)-[:SUPERSEDES]->(old:Decision)
RETURN d.id AS id, d.title AS title, d.status AS status, d.rationale AS rationale,
       d.decided_at AS decided_at, p.id AS author_id, p.name AS decided_by,
       doc.id AS document_id, doc.title AS document_title, doc.source AS document_source,
       old.id AS supersedes_id, old.title AS supersedes_title
ORDER BY d.decided_at DESC, d.id ASC
```

### 5. Multi-Hop Incident-to-Expert Evidence Paths (`UNION ALL`)
Constructs explicit node-and-edge provenance paths linking incidents to dependencies, owning teams, and experienced project contributors (`FIND_SYSTEM_PATHS` in `backend/app/graph/queries.py`).

## Setup & Installation

### 1. Start FalkorDB
```bash
git clone https://github.com/Rohit-Solanki1890/graphpilot.git
cd graphpilot
docker compose up -d
```

### 2. Create Virtual Environment & Install Dependencies
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate          # Linux/macOS
# or: .\.venv\Scripts\Activate.ps1  # Windows PowerShell
pip install -r requirements.txt
```

### 3. Initialize Schema and Seed Synthetic Organization Graph
```bash
cd backend
PYTHONPATH=. .venv/bin/python -m app.graph.schema
PYTHONPATH=. .venv/bin/python -m app.graph.seed
```

### 4. Run the Application (Deterministic or Ollama Mode)
```bash
# Deterministic mode (no LLM required):
cd backend
PYTHONPATH=. .venv/bin/python -m app.tui

# Ollama LLM tool-calling mode (requires `ollama pull qwen3:4b`):
cd backend
GRAPHPILOT_AGENT_MODE=ollama PYTHONPATH=. .venv/bin/python -m app.tui

# FastMCP Server (17 typed tools over stdio):
cd backend
PYTHONPATH=. .venv/bin/python -m app.mcp_server
```

## Complete 3-Track Demo Flow in the TUI

Run these commands inside the TUI to demonstrate all three tracks:

1. **Full Multi-Hop Investigation + Decision Provenance (Tracks 01 & 03)**:
   ```text
   investigate Checkout
   ```
2. **Depth-1 vs. Depth-3 Blast Radius Contrast (Track 01)**:
   ```text
   blast radius for Checkout depth 1
   blast radius for Checkout depth 3
   ```
   *(Depth 1 returns only `Payments API` and `Risk Engine`; Depth 3 discovers the transitive dependency `Checkout -> Payments API -> Event Stream` and its linked incident `incident-risk-lag`.)*
3. **FalkorDB Graph Algorithms — Shortest Path & PageRank (Track 01)**:
   ```text
   path from Ava Patel to Event Stream
   rank critical systems
   ```
4. **Company Brain Decision Provenance & Entity Exploration (Track 03)**:
   ```text
   decisions for Checkout
   explore Ava Patel
   ```
5. **Cross-Session Episodic, Semantic & Procedural Memory (Track 02)**:
   ```text
   list investigations for Checkout
   recall investigation <id>
   ```
6. **Multi-Agent Coordinator → Investigator → Reviewer Handoff (Track 02)**:
   ```text
   coordinate Checkout
   ```
7. **Approval-Gated Action Execution (Track 01)**:
   ```text
   propose follow-up task for Checkout
   ```
   Click **Approve** (or type `approve action <id>`) to execute the action in FalkorDB and create the follow-up `Task` node, or click **Reject** to block execution with a full audit trail.

## Testing

```bash
cd backend
pytest tests/ -v
```
