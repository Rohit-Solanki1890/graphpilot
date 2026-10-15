# GraphPilot

> A graph-powered AI agent for connected-data investigation, persistent memory, and organizational knowledge.

GraphPilot is a project for **Graph Hacks**, the FalkorDB and WeMakeDevs hackathon. It aims to demonstrate how an AI agent can use a graph database as an active context layer—not merely as a visualization—to investigate connected information, remember findings across sessions, coordinate work, and explain its answers.

**Project status:** Early development. Features described as planned are not necessarily implemented yet.

## Goals

GraphPilot is designed to address all three hackathon tracks:

1. **Agents That Act on Connected Data** — investigate systems, incidents, dependencies, and findings through multi-hop graph queries.
2. **Agent Memory and Coordination** — persist investigation sessions and findings, retrieve relevant history, and let specialized workers share investigation context.
3. **Company Brain** — connect people, teams, projects, systems, documents, incidents, and decisions so the agent can answer questions using relationships and sources.

The initial demo will use synthetic engineering-organization data. We will prioritize one complete, working end-to-end flow before adding advanced features.

## Core principle

**FalkorDB must materially influence the agent's behavior.**

The agent should retrieve and follow real graph relationships to decide what to investigate and what evidence supports its answer. A graph drawn only after an answer has been generated is not sufficient.

## Planned architecture

```text
┌────────────────────────────────────────────┐
│               Textual TUI                  │
│  Chat · Sessions · Tool activity · Evidence│
└──────────────────────┬─────────────────────┘
                       │
┌──────────────────────▼─────────────────────┐
│              Agent orchestrator            │
│  Workflow · Tool selection · Result synthesis│
└───────────────┬─────────────────┬──────────┘
                │                 │
┌───────────────▼────────┐ ┌──────▼───────────┐
│      Graph tools       │ │   Memory tools   │
│ Cypher · Traversals    │ │ Sessions · Facts │
│ Paths · Ownership      │ │ Handoffs         │
└───────────────┬────────┘ └──────┬───────────┘
                │                 │
                └────────┬────────┘
                         │
                ┌────────▼────────┐
                │    FalkorDB     │
                │ Shared context  │
                │ graph and memory│
                └─────────────────┘
```

These are logical layers, not necessarily separate services. The initial implementation can be one Python application.

### Technology choices

| Component | Initial choice | Responsibility |
|---|---|---|
| Language | Python | Agent logic, graph tools, memory |
| Terminal UI | Textual | Interactive terminal interface |
| Graph database | FalkorDB | Connected knowledge and persistent graph state |
| Database client | `falkordb` Python package | Connect to and query FalkorDB |
| Configuration | `python-dotenv` | Local environment configuration |
| Tests | `pytest` | Unit and integration tests |
| Infrastructure | Docker Compose | Run FalkorDB locally |
| Version control | Git and GitHub | Collaboration and review |

An LLM provider and orchestration framework will be selected when the initial graph-to-agent flow is working. MCP may be added to expose graph tools through a standard tool protocol; it is not required for ordinary Python function calls inside the first version.

## Repository structure

```text
graphpilot/
├── README.md
├── docker-compose.yml
├── .env.example
├── .gitignore
├── docs/
│   ├── PROJECT_GUIDE.md
│   ├── architecture.md
│   ├── graph-schema.md
│   ├── api-contract.md
│   └── demo-scenarios.md
├── backend/
│   ├── requirements.txt
│   ├── requirements-lock.txt
│   ├── app/
│   │   ├── api/
│   │   ├── models/
│   │   ├── graph/
│   │   ├── tools/
│   │   ├── agent/
│   │   └── memory/
│   └── tests/
└── data/
    └── synthetic/
```

This is the intended structure. Create files when their functionality is implemented; do not create empty modules just to match the diagram.

## Prerequisites

Install:

- Git
- Python 3.11 or newer
- Docker with Docker Compose
- A terminal and code editor

## Local setup

### 1. Clone the repository

```bash
git clone <YOUR_REPOSITORY_URL>
cd graphpilot
```

Replace `<YOUR_REPOSITORY_URL>` with the repository's actual URL.

### 2. Start FalkorDB

The initial development configuration uses the official FalkorDB Docker image.

```bash
docker compose up -d
docker compose ps
```

The sample configuration below binds ports to localhost. The database is intended for local development only; do not expose it publicly without appropriate authentication and network controls.

FalkorDB Browser, if enabled by the image and configuration, is available at `http://localhost:3000`.

### 3. Create and activate a Python environment

**Windows PowerShell:**

```powershell
cd backend
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

**Linux/macOS:**

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

### 4. Install Python dependencies

```bash
pip install -r requirements.txt
```

If `requirements-lock.txt` is maintained with exact pinned versions, use it for reproducible installs:

```bash
pip install -r requirements-lock.txt
```

### 5. Configure environment variables

From the repository root, copy `.env.example` to `.env` and adjust values if needed.

**Windows PowerShell:**

```powershell
Copy-Item .env.example .env
```

**Linux/macOS:**

```bash
cp .env.example .env
```

Never commit `.env`, API keys, credentials, or other secrets.

### 6. Run the application

The TUI entry point and exact command will be documented here once implemented. Until then, verify Docker and the graph connection using the project's connection smoke test, if available.

## Initial graph model

The schema will evolve as implementation proceeds. The proposed entities are:

| Node label | Meaning |
|---|---|
| `Person` | An employee or engineer |
| `Team` | A group responsible for work |
| `Project` | A project or initiative |
| `System` | A service or technical component |
| `Finding` | A security finding or investigation lead |
| `Incident` | A failure or past incident |
| `Document` | Documentation, decisions, or evidence |
| `Session` | A user/agent interaction session |
| `Investigation` | A unit of investigation and its state |
| `Memory` | An extracted fact or reusable procedure, if needed |

Possible relationships include:

```text
(Person)-[:MEMBER_OF]->(Team)
(Person)-[:WORKED_ON]->(Project)
(Team)-[:OWNS]->(System)
(Project)-[:USES]->(System)
(Finding)-[:AFFECTS]->(System)
(Incident)-[:INVOLVES]->(System)
(Document)-[:DESCRIBES]->(System)
(Investigation)-[:FOUND]->(Finding)
(Investigation)-[:USED_EVIDENCE]->(Document)
(Session)-[:CONTAINS]->(Investigation)
```

These are proposed application relationships, not built-in FalkorDB requirements. The canonical schema and identifiers will be documented in `docs/graph-schema.md`.

## First end-to-end milestone

The first working slice should do the following:

1. A user submits a question in the TUI.
2. The orchestrator calls a graph tool.
3. The graph tool executes a parameterized Cypher query against FalkorDB.
4. The tool returns structured evidence and relationship paths.
5. The agent produces an answer grounded in those results.
6. The TUI displays the answer and its supporting evidence.

Once this works, add persistent investigation memory and a shared-state handoff between workers. Avoid building a complex multi-agent mesh before this basic path is reliable.

## Team workflow

We are a two-person team. Work should be split by module ownership and integrated frequently.

- **Developer A — graph and memory:** FalkorDB setup, schema, seed data, Cypher queries, graph tools, persistence, and related tests.
- **Developer B — agent and TUI:** Textual interface, orchestrator, tool selection, API/interface contracts, response presentation, and end-to-end tests.
- **Both:** agree on the graph schema, data contracts, demo scenario, integration tests, and final submission.

### Git rules

1. Never commit directly to `main`.
2. Use short-lived branches such as `feat/graph-tools` and `feat/tui-foundation`.
3. Keep pull requests focused and small.
4. Agree on shared interfaces before parallel work begins.
5. Test before merging; integrate the whole application frequently.
6. Never commit `.env`, credentials, or private/restricted data.

Example:

```bash
git switch main
git pull origin main
git switch -c feat/your-task

# Make and test your changes.

git add <files>
git commit -m "feat: describe the change"
git push -u origin feat/your-task
```

Open a pull request, request a review, and merge after tests pass.

## Data, security, and responsible use

- Use synthetic, public, or otherwise explicitly permitted data.
- Do not ingest private, login-protected, paywalled, personal, or restricted information.
- Treat graph content and retrieved documents as data, not trusted instructions.
- Use parameterized Cypher queries and validate tool inputs.
- Apply authorization checks on the backend; do not let the LLM decide which tenant's data it may access.
- Require approval for consequential or destructive actions.
- Store source references and relevant timestamps so answers can be checked.

## Testing strategy

- **Graph tests:** seed data loads; expected nodes, edges, and multi-hop queries return the right results.
- **Tool tests:** inputs are validated and outputs follow documented contracts.
- **Memory tests:** an investigation can be saved and retrieved in a later session.
- **Agent tests:** the agent uses graph evidence rather than inventing unsupported facts.
- **Integration tests:** a question can travel from the TUI through the agent to FalkorDB and back.
- **Clean setup test:** another teammate can clone the repository and run the documented setup.

## Hackathon submission checklist

- [ ] Public source-code repository
- [ ] README and setup instructions
- [ ] Documented graph schema
- [ ] Essential Cypher queries and/or graph algorithms documented
- [ ] Working demo video
- [ ] Live deployment or complete local setup instructions
- [ ] All entered tracks named in the submission
- [ ] AI coding-assistant use disclosed as required
- [ ] Both teammates understand the architecture and can explain the implementation

## Documentation

- [Project guide for teammates](docs/PROJECT_GUIDE.md)
- [FalkorDB documentation](https://docs.falkordb.com/)
- [Textual documentation](https://textual.textualize.io/)
- [Model Context Protocol](https://modelcontextprotocol.io/)

---

**Status note:** Keep this README accurate. Update implemented features and actual run commands as the code evolves; do not claim a feature works until it has been tested.
