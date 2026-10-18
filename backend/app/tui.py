"""GraphPilot's Textual terminal user interface."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.message import Message
from textual.widgets import Button, Footer, Header, Input, RichLog, Static

from app.agent import run_turn


def _format_items(title: str, items: list[dict[str, Any]], fields: tuple[str, ...]) -> list[str]:
    lines = [title]
    if not items:
        return lines + ["  None found."]
    for item in items:
        values = [str(item[field]) for field in fields if item.get(field) is not None]
        lines.append(f"  - {' — '.join(values)}")
    return lines


def _format_investigation_list(investigations: list[Any]) -> list[str]:
    """Render list-shaped historical tool results without discarding details."""
    lines = ["Historical investigations"]
    records = [item for item in investigations if isinstance(item, Mapping)]
    if not records:
        return lines + ["  None found."]

    for investigation in records:
        lines.append(
            f"  - {investigation.get('investigation_id', investigation.get('id', 'unknown'))} "
            f"[{investigation.get('status', 'unknown')}] "
            f"{investigation.get('summary') or 'No summary'}"
        )
        if investigation.get("created_at"):
            lines.append(f"    Created: {investigation['created_at']}")
        if investigation.get("system_id"):
            lines.append(f"    System: {investigation['system_id']}")
        evidence_ids = investigation.get("evidence_ids") or []
        if evidence_ids:
            lines.append(f"    Evidence: {', '.join(str(item) for item in evidence_ids)}")
        paths = investigation.get("paths") or []
        if paths:
            lines.append("    Paths:")
            for path in paths:
                if not isinstance(path, Mapping):
                    lines.append(f"      - {path}")
                    continue
                nodes = " -> ".join(
                    f"{node.get('label', 'Entity')}:{node.get('id', 'unknown')}"
                    for node in path.get("nodes", [])
                    if isinstance(node, Mapping)
                )
                lines.append(f"      - {path.get('kind', 'graph')}: {nodes}")
        findings = investigation.get("findings") or []
        if findings:
            lines.append(f"    Findings: {len(findings)}")
            for finding in findings:
                if not isinstance(finding, Mapping):
                    continue
                statement = finding.get("statement") or finding.get("description") or "Unspecified finding"
                status = finding.get("fact_status") or finding.get("kind") or "unknown"
                lines.append(f"      - [{status}] {statement}")
    return lines


def format_turn(result: dict[str, Any]) -> list[str]:
    """Convert an orchestrator result into readable terminal lines."""
    lines = [f"GraphPilot: {result.get('message', '')}"]
    status = result.get("status", "unknown").upper()
    lines.append(f"Status: {status}")

    tool_result = result.get("tool_result")
    if not tool_result:
        return lines

    if isinstance(tool_result, list):
        lines.extend(["", *_format_investigation_list(tool_result)])
        return lines
    if not isinstance(tool_result, Mapping):
        lines.extend(["", f"Tool result: {tool_result}"])
        return lines

    if "investigations" in tool_result and isinstance(tool_result.get("investigations"), list):
        lines.extend(["", *_format_investigation_list(tool_result["investigations"])])
        return lines

    action = tool_result.get("action")
    if action:
        lines.extend(
            [
                "",
                "Action",
                f"  - {action.get('action_id')} [{action.get('status')}] "
                f"{action.get('type')}",
                f"  Approval required: {action.get('approval_required')}",
                f"  Rationale: {action.get('rationale') or 'Not recorded'}",
            ]
        )
        return lines

    coord_task = tool_result.get("coordination_task")
    if coord_task:
        lines.extend(
            [
                "",
                "Multi-Agent Coordination",
                f"  Task ID: {coord_task.get('task_id')} (Tenant: {coord_task.get('tenant_id')})",
                f"  Handoff Chain: {' -> '.join(tool_result.get('handoff_roles') or ['coordinator', 'investigator', 'reviewer'])}",
                f"  Status: {coord_task.get('status')} | Review: {coord_task.get('review_status')}",
                f"  Next Action: {coord_task.get('next_action')}",
                f"  Evidence Refs: {', '.join(coord_task.get('evidence_refs') or []) or 'None'}",
            ]
        )
        review_res = coord_task.get("review_result") or {}
        lines.append(f"  Checked Findings: {review_res.get('checked_findings', 0)} | Approved: {review_res.get('approved')}")
        for issue in review_res.get("issues") or []:
            lines.append(f"    - Flagged: {issue.get('claim')} ({issue.get('reason')})")
        return lines

    shortest = tool_result.get("shortest_path")
    if shortest:
        lines.extend(
            [
                "",
                "Shortest Path Analysis",
                f"  Algorithm: {shortest.get('algorithm')} | Hops: {shortest.get('hops')}",
                f"  Route: {' -> '.join(shortest.get('via') or [])}",
            ]
        )
        return lines

    critical = tool_result.get("critical_systems")
    if critical:
        lines.extend(["", f"Critical Systems ({critical.get('algorithm')})"])
        for item in critical.get("systems") or []:
            lines.append(
                f"  - {item.get('name')} [{item.get('id')}] — status: {item.get('status')} — score: {round(float(item.get('score') or 0), 4)}"
            )
        return lines

    if "blast_radius" in tool_result and "findings" not in tool_result:
        sys_info = tool_result.get("system") or {}
        lines.extend(
            [
                "",
                f"Blast Radius: {sys_info.get('name', sys_info.get('id', 'System'))} (max depth: {tool_result.get('depth', 3)})",
            ]
        )
        for dep in tool_result.get("blast_radius") or []:
            via_str = " -> ".join(str(v) for v in (dep.get("via") or []))
            lines.append(
                f"  - [hop {dep.get('hops')}] {dep.get('name')} ({dep.get('status')}) via {via_str}"
            )
        return lines

    if "decisions" in tool_result and "findings" not in tool_result:
        sys_info = tool_result.get("system") or {}
        lines.extend(["", f"Decisions for {sys_info.get('name', sys_info.get('id', 'System'))}"])
        for dec in tool_result.get("decisions") or []:
            lines.append(
                f"  - {dec.get('title')} [{dec.get('status')}] (by {dec.get('decided_by') or 'unknown'} on {dec.get('decided_at')})"
            )
            lines.append(f"    Rationale: {dec.get('rationale')}")
            if dec.get("document_id"):
                lines.append(f"    Source Doc: {dec.get('document_title')} ({dec.get('document_source')})")
            if dec.get("supersedes_id"):
                lines.append(f"    Supersedes: {dec.get('supersedes_title')} [{dec.get('supersedes_id')}]")
        return lines

    entity_ctx = tool_result.get("entity_context")
    if entity_ctx:
        ent = entity_ctx.get("entity") or {}
        lines.extend(
            [
                "",
                f"Entity: {ent.get('name')} ({ent.get('label')} [{ent.get('id')}])",
                f"Status/Role: {ent.get('status') or 'N/A'}",
                "Connections",
            ]
        )
        for conn in entity_ctx.get("connections") or []:
            arrow = "->" if conn.get("direction") == "outgoing" else "<-"
            lines.append(
                f"  - [:{conn.get('relationship')}] {arrow} {conn.get('neighbor_label')}:{conn.get('neighbor_name')} ({conn.get('neighbor_id')})"
            )
        return lines

    system = tool_result.get("system") or {}
    if system:
        lines.extend(
            [
                "",
                f"System: {system.get('name', system.get('id', 'unknown'))} "
                f"[{system.get('id', 'unknown')}]",
                f"Description: {system.get('description') or 'Not recorded'}",
                f"Status: {system.get('status') or 'Not recorded'}",
            ]
        )

    lines.extend(["", "Facts"])
    hypotheses = []
    for finding in tool_result.get("findings") or []:
        if finding.get("kind") == "hypothesis":
            hypotheses.append(finding)
            continue
        entity_ids = ", ".join(str(value) for value in finding.get("entity_ids") or [])
        suffix = f" (entities: {entity_ids})" if entity_ids else ""
        lines.append(f"  - {finding.get('statement', 'Unspecified fact')}{suffix}")

    lines.append("")
    lines.append("Hypotheses")
    if hypotheses:
        for finding in hypotheses:
            entity_ids = ", ".join(str(value) for value in finding.get("entity_ids") or [])
            suffix = f" (entities: {entity_ids})" if entity_ids else ""
            lines.append(f"  - {finding.get('statement', 'Unspecified hypothesis')}{suffix}")
    else:
        lines.append("  None recorded.")

    lines.extend(_format_items("Incidents", tool_result.get("related_incidents") or [], ("title", "severity", "status", "id")))
    lines.extend(_format_items("Dependencies", tool_result.get("dependencies") or [], ("name", "status", "id")))
    lines.extend(_format_items("Experts", tool_result.get("experts") or [], ("name", "role", "id")))
    lines.extend(
        _format_items(
            "Potential Responders",
            tool_result.get("recommended_responders") or [],
            ("name", "role", "reason", "id"),
        )
    )
    lines.extend(_format_items("Evidence", tool_result.get("evidence") or [], ("title", "source", "id")))

    if tool_result.get("decisions"):
        lines.extend(
            _format_items(
                "Decisions",
                tool_result.get("decisions") or [],
                ("title", "status", "decided_by", "document_id", "id"),
            )
        )

    memory_context = tool_result.get("memory_context") or {}
    prior_investigations = memory_context.get("prior_investigations") or []
    lines.append("Prior investigations")
    if prior_investigations:
        for investigation in prior_investigations:
            lines.append(
                f"  - {investigation.get('investigation_id')} "
                f"({investigation.get('created_at') or 'unknown time'}): "
                f"{investigation.get('summary') or 'No summary'} [historical]"
            )
    else:
        lines.append("  None found.")

    lines.append("Memory conflicts")
    conflicts = tool_result.get("memory_conflicts") or []
    if conflicts:
        for conflict in conflicts:
            lines.append(
                f"  - {conflict.get('message', 'Historical finding differs')} "
                f"(investigation: {conflict.get('prior_investigation_id', 'unknown')})"
            )
    else:
        lines.append("  None found.")

    procedure = tool_result.get("procedure") or {}
    lines.append("Procedure")
    lines.append(f"  Completed: {len(procedure.get('completed_steps') or [])}")
    for step in procedure.get("remaining_steps") or []:
        lines.append(f"  - Remaining: {step}")

    lines.append("Paths")
    paths = tool_result.get("paths") or []
    if paths:
        for path in paths:
            nodes = " -> ".join(
                f"{node.get('label', 'Entity')}:{node.get('id', 'unknown')}"
                for node in path.get("nodes", [])
            )
            relationships = ", ".join(
                f"{item.get('source_id')} -[:{item.get('type')}]-> {item.get('target_id')}"
                for item in path.get("relationships", [])
            )
            lines.append(f"  - {path.get('kind', 'graph')}: {nodes}")
            lines.append(f"    {relationships}")
    else:
        lines.append("  None found.")

    unknowns = tool_result.get("unknowns") or []
    lines.append("Unknowns")
    lines.extend(f"  - {unknown}" for unknown in unknowns) if unknowns else lines.append("  None recorded.")
    explanation = tool_result.get("explanation") or {}
    if explanation:
        lines.append("Decision explanation")
        lines.append(f"  Tool: {explanation.get('selected_tool')}")
        lines.append(f"  Why: {explanation.get('selection_reason')}")
        lines.append(f"  Next step: {explanation.get('next_step')}")
    return lines


class ApprovalPanel(Static):
    """Inline approve/reject panel shown when an action is pending."""

    DEFAULT_CSS = """
    ApprovalPanel {
        border: solid $warning;
        padding: 0 2;
        margin: 1 0;
        height: auto;
    }
    ApprovalPanel #approval-label {
        color: $warning;
        margin-bottom: 1;
    }
    ApprovalPanel Button {
        margin: 0 1;
    }
    ApprovalPanel #btn-approve {
        variant: success;
    }
    ApprovalPanel #btn-reject {
        variant: error;
    }
    """

    def __init__(self, action: dict[str, Any]) -> None:
        super().__init__()
        self._action = action

    def compose(self) -> ComposeResult:
        action_id = self._action.get("action_id", "unknown")
        action_type = self._action.get("type", "unknown")
        rationale = self._action.get("rationale") or "No rationale recorded."
        yield Static(
            f"⏳ Pending approval  [{action_id}]  {action_type}\n"
            f"   Rationale: {rationale}",
            id="approval-label",
        )
        with Horizontal():
            yield Button("Approve", id="btn-approve", variant="success")
            yield Button("Reject", id="btn-reject", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Dispatch the approval decision and remove the panel."""
        action_id = self._action.get("action_id", "")
        decision = "approve" if event.button.id == "btn-approve" else "reject"
        self.app.post_message(ApprovalDecision(action_id, decision))
        self.remove()


class ApprovalDecision(Message):
    """Internal message: user clicked Approve or Reject on an action panel."""

    def __init__(self, action_id: str, decision: str) -> None:
        super().__init__()
        self.action_id = action_id
        self.decision = decision


class GraphPilotApp(App[None]):
    """Interactive shell for deterministic and Ollama-powered GraphPilot investigations."""

    TITLE = "GraphPilot"
    SUB_TITLE = "Connected engineering investigations, memory & coordination"
    CSS = """
    Screen {
        background: $surface;
    }
    #conversation {
        height: 1fr;
        border: round $primary;
        padding: 1 2;
        scrollbar-size: 1 1;
    }
    #status {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    #message {
        dock: bottom;
        margin: 1 0;
    }
    """
    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("ctrl+l", "clear_log", "Clear"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with Container():
            yield RichLog(
                id="conversation",
                highlight=True,
                markup=False,
                wrap=True,
                min_width=1,
            )
            yield Static(
                "Ready — try: investigate Checkout | path from Ava Patel to Event Stream | rank systems | coordinate Checkout",
                id="status",
            )
            yield Input(
                placeholder="Ask GraphPilot to investigate, find paths, rank systems, coordinate, or propose actions...",
                id="message",
            )
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#conversation", RichLog).write(
            "Welcome to GraphPilot. Try: 'investigate Checkout', 'blast radius for Checkout depth 3', "
            "'path from Ava Patel to Event Stream', 'rank systems', 'decisions for Checkout', "
            "'coordinate Checkout', or 'propose follow-up task for Checkout'."
        )
        self.query_one("#message", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        message = event.value.strip()
        if not message:
            return
        event.input.value = ""
        self.query_one("#conversation", RichLog).write(f"> {message}")
        self.query_one("#status", Static).update("Working...")
        event.input.disabled = True
        self._process_message(message)

    @work(thread=True, exclusive=True)
    def _process_message(self, message: str) -> None:
        try:
            result = run_turn(message)
        except Exception as exc:
            self.call_from_thread(self._show_error, str(exc))
            return
        self.call_from_thread(self._show_result, result)

    def _show_result(self, result: dict[str, Any]) -> None:
        log = self.query_one("#approval-panels", Container).mount(panel)
        for line in format_turn(result):
            log.write(line)

        tool_result = result.get("tool_result")
        action = tool_result.get("action") if isinstance(tool_result, Mapping) else None
        if action and action.get("status") == "proposed":
            panel = ApprovalPanel(action)
            self.query_one(VerticalScroll).mount(panel)
            panel.scroll_visible()

        self.query_one("#status", Static).update(
            f"{result.get('status', 'unknown').title()} — ready for another request"
        )
        self.query_one("#message", Input).disabled = False
        self.query_one("#message", Input).focus()

    def _show_error(self, message: str) -> None:
        self.query_one("#conversation", RichLog).write(f"GraphPilot error: {message}")
        self.query_one("#status", Static).update("Error — ready for another request")
        self.query_one("#message", Input).disabled = False
        self.query_one("#message", Input).focus()

    def on_approval_decision(self, event: ApprovalDecision) -> None:
        """Handle an approval/rejection decision from an ApprovalPanel."""
        command = f"{event.decision} action {event.action_id}"
        self.query_one("#conversation", RichLog).write(f"> {command}")
        self.query_one("#status", Static).update("Executing decision...")
        self.query_one("#message", Input).disabled = True
        self._process_message(command)

    def action_clear_log(self) -> None:
        self.query_one("#conversation", RichLog).clear()


if __name__ == "__main__":
    GraphPilotApp().run()
