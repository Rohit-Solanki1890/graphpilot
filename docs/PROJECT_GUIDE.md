# GraphPilot — Project Guide for Teammates

Welcome to GraphPilot! This document explains the project from the beginning: the problem we are solving, what an AI agent is, why FalkorDB matters, how the architecture fits together, and how we will work as a two-person team.

You do not need prior graph-database or multi-agent experience to get started. Read this guide before implementing a module.

## 1. The project in one paragraph

GraphPilot is a terminal-based AI agent for investigating connected engineering information. It uses **FalkorDB as an active context layer** to connect systems, incidents, findings, people, projects, documents, and investigation history. The agent uses graph queries to find evidence, produces answers that cite the relationships it followed, and is intended to remember useful findings across sessions. The project aims to demonstrate capabilities across all three Graph Hacks tracks.

The implementation is at an early stage. This document describes the design and planned behavior, not a claim that every feature is already implemented.

## 2. What problem are we solving?

Information in a company is often scattered across records:

- An incident ticket describes a failure.
- A system record lists dependencies.
- A deployment record shows a recent change.
- A document explains an architectural decision.
- A team record identifies the system owner.
- A previous investigation contains useful findings.

A question like “Why is checkout failing, and who can investigate it?” may require information from several of these records and an understanding of how they relate.

A basic chatbot may give a generic answer or retrieve only a few matching documents. GraphPilot aims to follow the relationships between the records, gather relevant evidence, and explain how the result was reached.

The hackathon requires FalkorDB to do real work. It must influence the agent's retrieval, reasoning workflow, or actions. A graph visualization that can be removed without changing the product is not enough.

## 3. What is an AI agent?

An AI agent is a software system that uses an AI model to pursue a goal through a workflow. It can decide which tools to call, observe their results, and choose a next step.

For example, a user asks:

> Investigate the checkout service failure.

A simplified agent workflow is:

1. Understand the task.
2. Decide what evidence is needed.
3. Call a graph tool to retrieve dependencies or related incidents.
4. Inspect the returned evidence.
5. Decide whether another query or tool call is needed.
6. Produce an answer with sources and uncertainty.
7. Save useful investigation state if appropriate.

The **LLM** supplies language understanding and reasoning. The **agent code** controls the workflow and tool calls. **Tools** perform concrete operations. **FalkorDB** stores and retrieves connected information and persistent graph state. The **TUI** is how the user interacts with the system.

An LLM by itself is not the whole application, and FalkorDB is not the LLM. They perform different jobs.

## 4. What is a graph database?

A graph represents information using:

- **Nodes:** entities, such as people, services, incidents, projects, and documents.
- **Relationships (edges):** connections, such as `OWNS`, `USES`, `WORKED_ON`, `DEPENDS_ON`, and `INVOLVES`.
- **Properties:** details attached to nodes or relationships, such as IDs, names, timestamps, status, and source references.

Example:

```text
(Person: Priya)-[:MEMBER_OF]->(Team: Payments)
(Team: Payments)-[:OWNS]->(System: Checkout)
(System: Checkout)-[:DEPENDS_ON]->(System: Authentication)
(Incident: INC-104)-[:INVOLVES]->(System: Checkout)
```

These relationships let a query move from an incident to a system, from that system to a dependency, and from a system to the team responsible for it.

FalkorDB uses Cypher to query graph patterns. A simplified example is:

```cypher
MATCH (p:Person)-[:WORKED_ON]->(pr:Project)-[:USES]->(s:System {name: $system})
RETURN p.name AS person, pr.name AS project
```

This finds people who worked on projects that use the named system. The `$system` value should be supplied as a parameter by the application, not interpolated into the query string.

A graph connection does not automatically prove causation. If a recent deployment is connected to an incident, that is a lead to investigate—not proof that the deployment caused the incident.

## 5. The four architectural layers

These are logical responsibilities. Initially, they can all live in one Python application; they do not need to be separate services.

### Layer 1 — Orchestration

**Question it answers: What should happen next?**

The orchestrator receives a user goal, manages the agent workflow, selects tools, evaluates returned results, decides whether more investigation is needed, and assembles the final response.

Example:

- User asks why checkout is failing.
- Orchestrator decides to inspect dependencies.
- It calls `get_system_dependencies`.
- It observes the result and decides whether to retrieve related incidents.
- It combines the evidence into a response.

Keep the orchestration logic separate from the database queries. It should call well-defined tool functions rather than contain raw Cypher everywhere.

### Layer 2 — Tool space

**Question it answers: What operations can the agent request?**

Tools are ordinary functions that perform bounded tasks, such as:

- `search_entities(...)`
- `explore_neighborhood(...)`
- `get_system_dependencies(...)`
- `get_related_incidents(...)`
- `find_system_owner(...)`
- `save_investigation(...)`
- `get_previous_investigations(...)`

Each tool validates its inputs, performs an operation, and returns structured data.

**What is MCP?** The Model Context Protocol is a standard for exposing tools and context to AI applications. It can make graph tools reusable by different clients or agents. It is not required for an ordinary Python function call within the first version. We should make the functions work first and add an MCP server only if it provides value within the deadline.

### Layer 3 — Memory system

**Question it answers: What should the agent remember?**

We plan to represent three useful kinds of memory:

- **Episodic:** what happened during an investigation or conversation.
- **Semantic:** facts and relationships that remain useful, such as which team owns a system.
- **Procedural:** reusable, verified workflows or playbooks.

Memory is not just a transcript. It should make it possible to retrieve the right previous information for a later task.

Example:

1. Session A investigates an incident.
2. The system saves an investigation record and links it to the incident, system, evidence, and outcome.
3. Session B asks about a similar incident.
4. The agent retrieves the relevant prior investigation and continues from the saved context.

For shared state, one agent can pass another an `investigation_id`. The receiving agent retrieves the associated context from FalkorDB instead of relying only on a long text handoff.

We should begin with simple, explicit persistence. Advanced automatic memory extraction and frameworks such as Graphiti or Cognee are optional extensions, not prerequisites.

### Layer 4 — Data layer (FalkorDB)

**Question it answers: What connected facts and state can the agent retrieve?**

This layer contains the graph schema, data ingestion or seed scripts, Cypher queries, and connection management.

The proposed graph includes:

- `Person`
- `Team`
- `Project`
- `System`
- `Finding`
- `Incident`
- `Document`
- `Session`
- `Investigation`
- Optionally `Memory`

The initial dataset will be synthetic. We should document relationship types, stable IDs, important properties, and source references in `docs/graph-schema.md`.

**Why start here?** The tools cannot be written and tested reliably without a schema and sample data. The orchestrator cannot use tools without a known contract. Build a small graph and one meaningful multi-hop query first, then connect the agent.

## 6. How the layers work together

Suppose the user asks:

> Why might checkout be failing, and who owns the affected system?

A complete request could flow like this:

1. The TUI sends the question to the orchestrator.
2. The orchestrator chooses a graph tool.
3. The tool runs a parameterized Cypher query against FalkorDB.
4. FalkorDB returns related systems, incidents, owners, and evidence.
5. The orchestrator inspects the result and may call another tool.
6. The memory module retrieves a relevant previous investigation if one exists.
7. The agent produces an answer with evidence and relationship paths.
8. The memory module saves the new investigation for future sessions.
9. The TUI displays the answer, source details, and tool activity.

The graph must affect the result. If the graph is removed, the agent should lose important connected context or be unable to complete the same investigation.

## 7. Why a TUI?

A TUI is a terminal user interface. The project will use Python Textual to create an interactive terminal experience inspired by developer tools such as OpenCode.

Planned interface areas:

- Conversation input and responses.
- Session or investigation history.
- Tool activity and progress.
- Evidence, source records, and graph paths.
- Current database/session status.

The TUI is only the presentation layer. It should not contain Cypher queries or own the memory logic. It calls the orchestrator through a stable interface. That separation means a web interface could be added later without rewriting the agent core.

## 8. How one product can address all three tracks

### Track 1 — Agents That Act on Connected Data

The agent follows graph relationships between findings, systems, dependencies, incidents, and owners to investigate a problem. The demonstration should show a multi-hop query and how its results affect the recommended next step.

### Track 2 — Agent Memory and Coordination

The system saves an investigation, retrieves it in a later session, and lets a second worker continue from the shared investigation state. Demonstrate persistence across sessions, not just a transcript kept in process memory.

### Track 3 — Company Brain

The graph connects people, teams, projects, systems, documents, and decisions. The agent answers ownership and architecture questions with supporting sources.

We can use one synthetic engineering-organization graph for all three tracks. The first goal is a single reliable investigation workflow; we can expand from there.

## 9. Two-person work split

We should divide work by module ownership to reduce merge conflicts.

### Developer A — Graph and memory

Owns:

- `backend/app/graph/`
- `backend/app/tools/`
- `backend/app/memory/`
- Graph and tool tests
- `docs/graph-schema.md`

Tasks:

1. Run FalkorDB with Docker Compose.
2. Define and document the schema.
3. Create synthetic seed data.
4. Implement and test Cypher queries.
5. Wrap queries in functions with stable input/output contracts.
6. Implement investigation persistence and retrieval.

### Developer B — Orchestration and TUI

Owns:

- `backend/app/agent/`
- `backend/app/api/`, if needed
- `frontend/` only if a web UI is later added
- TUI components and end-to-end tests
- Agent response formatting

Tasks:

1. Create the Textual application.
2. Build a mock graph-tool function using the agreed response contract.
3. Implement the orchestrator and its tool-calling workflow.
4. Display tool activity and evidence.
5. Connect the TUI to the real graph tools.
6. Test the complete user journey.

### Decisions we must make together

- Node labels, relationship types, stable identifiers, and required properties.
- Tool function signatures and return shapes.
- The first demo scenario and what counts as a correct answer.
- Any changes to shared models or API contracts.

Developer B should not wait for the real database implementation; mocks enable parallel work. Developer A should not wait for the LLM; graph queries can be tested independently.

## 10. Repository and Git rules

We use one GitHub repository (a monorepo) because all the components belong to one product.

Suggested structure:

```text
graphpilot/
├── README.md
├── docker-compose.yml
├── .env.example
├── .gitignore
├── docs/
├── backend/
│   ├── requirements.txt
│   ├── app/
│   │   ├── graph/
│   │   ├── tools/
│   │   ├── memory/
│   │   ├── agent/
│   │   ├── models/
│   │   └── api/
│   └── tests/
└── data/
    └── synthetic/
```

Rules:

1. Do not commit directly to `main`.
2. Create short-lived branches, such as `feat/graph-tools` or `feat/tui-foundation`.
3. Avoid editing another person's owned files without coordination.
4. Agree on shared contracts before parallel work.
5. Keep pull requests small and merge frequently.
6. Run relevant tests before merging.
7. Do not commit `.env`, API keys, credentials, or private/restricted data.
8. After merging, sync your branch with the latest `main` before starting the next task.

Typical workflow:

```bash
git switch main
git pull origin main
git switch -c feat/your-task

# Implement and test.

git add <your-files>
git commit -m "feat: describe your change"
git push -u origin feat/your-task
```

Open a pull request and merge after review and testing. Git prevents many problems, but shared interfaces and communication are what prevent most integration failures.

## 11. Build order

Build in dependency order, not in the order the boxes appear in the architecture diagram.

1. **Graph foundation:** start FalkorDB, define the schema, seed synthetic data, test a multi-hop query.
2. **Graph tools:** wrap queries in Python functions and establish response contracts.
3. **First agent loop:** make the orchestrator call a graph tool and return evidence.
4. **TUI:** connect the interface to the working agent.
5. **Persistent memory:** save and retrieve investigations across sessions.
6. **Coordination:** demonstrate a second worker retrieving shared investigation state.
7. **Company knowledge:** add ownership, documents, project relationships, and source tracing.
8. **Submission readiness:** tests, README, setup verification, demo video, and disclosure of AI assistance.

The exact order of TUI work can overlap with the graph work through mocks. Do not wait for every module to be finished before integrating.

## 12. First end-to-end milestone

The first milestone is intentionally small:

> A user enters a question in the TUI, the agent calls a FalkorDB-backed graph tool, and the application displays an answer with a verifiable relationship path.

Definition of done:

- FalkorDB runs locally.
- Synthetic data loads repeatably.
- A multi-hop Cypher query returns expected results.
- The agent calls the real tool, not just a hardcoded answer.
- The response contains supporting evidence or graph paths.
- The other teammate can clone the repository and reproduce the flow.

After this works, add persistent memory and cross-agent handoffs.

## 13. Safety, provenance, and correctness

- Use public, synthetic, or otherwise explicitly permitted data.
- Do not load private, login-protected, paywalled, personal, or restricted data.
- Treat retrieved documents and graph content as untrusted data, not instructions.
- Parameterize queries and validate tool inputs.
- Keep authorization checks in application code.
- Do not let an LLM choose which tenant's graph it can access.
- Ask for approval before consequential or destructive actions.
- Preserve source references and timestamps where useful.
- Clearly distinguish facts, hypotheses, and unknowns. A graph path is evidence of a relationship, not automatic proof of causation.

## 14. Questions every teammate should be able to answer

Before submission, both teammates should be able to explain:

1. What problem does GraphPilot solve?
2. Why is FalkorDB essential rather than decorative?
3. What are the important node labels and relationship types?
4. How does the agent call a graph tool?
5. How does a later session retrieve an earlier investigation?
6. How does a worker hand off context to another worker?
7. How can a user verify the sources behind an answer?
8. How do we test that the graph actually affects the result?

If both teammates can explain these points and run the demo from a clean setup, we will have a much stronger submission.

---

**Next step:** agree on the first demo scenario and graph schema together. Developer A can start the graph foundation while Developer B builds the TUI against a mock response. Integrate as soon as the first real graph tool is available.
