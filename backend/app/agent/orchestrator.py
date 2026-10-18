"""Deterministic and Ollama-backed orchestration layer for GraphPilot."""

from __future__ import annotations

import os
import re
from typing import Any

from app.graph import (
    create_task,
    execute_action,
    explore_entity_context,
    find_shortest_path,
    get_blast_radius,
    get_investigation,
    get_recent_investigations,
    get_system,
    get_system_by_name,
    get_system_decisions,
    get_system_documents,
    investigator_handoff,
    propose_action,
    rank_critical_systems,
    review_task,
    save_investigation,
)
from app.tools import investigate_system

_INVESTIGATE_PATTERN = re.compile(
    r"^\s*(?:please\s+)?investigate\s+(?:system\s+)?(?P<target>.+?)(?:\s+depth\s+(?P<depth>[1-4]))?\s*[?.]?\s*$",
    re.IGNORECASE,
)
_RECALL_PATTERN = re.compile(
    r"^\s*(?:recall|show)\s+investigation\s+(?P<id>\S+)\s*$",
    re.IGNORECASE,
)
_LIST_PATTERN = re.compile(
    r"^\s*(?:list|show)\s+(?:recent\s+)?investigations\s+(?:for\s+)?(?P<target>.+?)\s*$",
    re.IGNORECASE,
)
_PROPOSE_PATTERN = re.compile(
    r"^\s*propose\s+(?:follow-up\s+task|follow\s+up\s+task|action)\s+(?:for\s+)?(?P<target>.+?)\s*$",
    re.IGNORECASE,
)
_DECIDE_ACTION_PATTERN = re.compile(
    r"^\s*(?P<decision>approve|reject)\s+action\s+(?P<id>\S+)\s*$",
    re.IGNORECASE,
)
_COORDINATE_PATTERN = re.compile(
    r"^\s*coordinate\s+(?:investigation\s+(?:for\s+)?|task\s+(?:for\s+)?)?(?P<target>.+?)\s*$",
    re.IGNORECASE,
)
_PATH_PATTERN = re.compile(
    r"^\s*(?:(?:find\s+)?path\s+(?:from|between)\s+(?P<src1>.+?)\s+(?:to|and)\s+(?P<dst1>.+?)|how\s+is\s+(?P<src2>.+?)\s+connected\s+to\s+(?P<dst2>.+?))\s*[?.]?\s*$",
    re.IGNORECASE,
)
_RANK_PATTERN = re.compile(
    r"^\s*(?:rank\s+(?:critical\s+)?systems|which\s+systems\s+are\s+(?:most\s+)?(?:critical|load-bearing))\s*[?.]?\s*$",
    re.IGNORECASE,
)
_BLAST_RADIUS_PATTERN = re.compile(
    r"^\s*(?:show\s+)?blast\s+radius\s+(?:for\s+)?(?P<target>.+?)(?:\s+depth\s+(?P<depth>[1-4]))?\s*[?.]?\s*$",
    re.IGNORECASE,
)
_DECISIONS_PATTERN = re.compile(
    r"^\s*(?:show\s+|trace\s+|list\s+)?decisions\s+(?:for\s+)?(?P<target>.+?)\s*[?.]?\s*$",
    re.IGNORECASE,
)
_EXPLORE_PATTERN = re.compile(
    r"^\s*explore\s+(?P<target>.+?)\s*[?.]?\s*$",
    re.IGNORECASE,
)


def _response(
    message: str,
    *,
    status: str,
    tool_result: dict[str, Any] | list[Any] | None = None,
    tool_name: str | None = None,
) -> dict[str, Any]:
    return {
        "message": message,
        "tool_used": tool_name if tool_result is not None else None,
        "tool_result": tool_result,
        "status": status,
    }


def _resolve_system(target: str) -> dict[str, Any] | None:
    """Resolve an exact ID first, then a case-insensitive system name."""
    system = get_system(target)
    return system if system is not None else get_system_by_name(target)


def run_turn(user_message: str) -> dict[str, Any]:
    """Route a turn, optionally using Ollama with deterministic fallback."""
    if os.getenv("GRAPHPILOT_AGENT_MODE", "").lower() == "ollama":
        try:
            from .ollama_agent import run_ollama_turn

            return run_ollama_turn(
                user_message,
                model=os.getenv("GRAPHPILOT_OLLAMA_MODEL", "qwen3:4b"),
            )
        except Exception as exc:
            fallback = _run_deterministic_turn(user_message)
            fallback["llm_fallback"] = str(exc)
            return fallback
    return _run_deterministic_turn(user_message)


def _run_deterministic_turn(user_message: str) -> dict[str, Any]:
    """Route one supported user request without using an LLM."""
    if not isinstance(user_message, str) or not user_message.strip():
        return _response(
            "Please ask me to investigate a system by name or ID.",
            status="unsupported",
        )

    recall = _RECALL_PATTERN.match(user_message)
    if recall:
        memory = get_investigation(recall.group("id"))
        if memory is None:
            return _response(
                f"Investigation '{recall.group('id')}' was not found.",
                status="not_found",
            )
        return _response(
            f"Recalled historical investigation {memory['investigation_id']} for "
            f"{memory['system_id']}. Historical findings are not newly verified.",
            status="success",
            tool_result=memory,
            tool_name="get_investigation",
        )

    listing = _LIST_PATTERN.match(user_message)
    if listing:
        target = listing.group("target").strip()
        system = _resolve_system(target)
        if system is None:
            return _response(
                f"I could not find a system named or identified as '{target}'.",
                status="not_found",
            )
        memories = get_recent_investigations(system["id"])
        return _response(
            f"Found {len(memories)} historical investigation(s) for {system['name']}.",
            status="success",
            tool_result={"system_id": system["id"], "investigations": memories},
            tool_name="get_recent_investigations",
        )

    propose_match = _PROPOSE_PATTERN.match(user_message)
    if propose_match:
        target = propose_match.group("target").strip()
        system = _resolve_system(target)
        if system is None:
            return _response(
                f"I could not find a system named or identified as '{target}'.",
                status="not_found",
            )
        try:
            docs = get_system_documents(system["id"])
            evidence_ids = [d["id"] for d in docs if d.get("id")]
        except Exception:
            evidence_ids = []
        action = propose_action(
            "create_follow_up_task",
            {"title": f"Follow up on {system['name']} incident & dependency paths"},
            target_system_id=system["id"],
            evidence_ids=evidence_ids,
            rationale=(
                f"Connected graph evidence for {system['name']} ({system['id']}) "
                f"requires an engineer-reviewed follow-up task."
            ),
        )
        return _response(
            f"Proposed action {action['action_id']} for {system['name']}; "
            f"explicit human approval is required before execution.",
            status="success",
            tool_result={"action": action},
            tool_name="propose_action",
        )

    decide_match = _DECIDE_ACTION_PATTERN.match(user_message)
    if decide_match:
        decision = decide_match.group("decision").lower()
        action_id = decide_match.group("id").strip()
        try:
            action = execute_action(action_id, approve=(decision == "approve"))
        except LookupError as exc:
            return _response(str(exc), status="not_found")
        verb = "Approved and executed" if decision == "approve" else "Rejected"
        return _response(
            f"{verb} action {action['action_id']} (status: {action['status']}).",
            status="success",
            tool_result={"action": action},
            tool_name="execute_action",
        )

    coordinate_match = _COORDINATE_PATTERN.match(user_message)
    if coordinate_match:
        target = coordinate_match.group("target").strip()
        system = _resolve_system(target)
        if system is None:
            return _response(
                f"I could not find a system named or identified as '{target}'.",
                status="not_found",
            )
        task = create_task(system["id"])
        inv = investigate_system(system["id"])
        evidence_refs = [
            doc["id"] for doc in (inv.get("evidence") or []) if isinstance(doc, dict) and doc.get("id")
        ]
        claims = []
        for finding in inv.get("findings") or []:
            if finding.get("kind") == "fact" and evidence_refs:
                claims.append(
                    {
                        "claim": finding.get("statement", ""),
                        "evidence_refs": evidence_refs,
                    }
                )
        if not claims and evidence_refs:
            claims.append(
                {
                    "claim": f"{system['name']} check latency and event stream backlog",
                    "evidence_refs": evidence_refs,
                }
            )
        handed_off = investigator_handoff(task["task_id"], claims, evidence_refs)
        reviewed = review_task(task["task_id"])
        return _response(
            f"Completed Coordinator -> Investigator -> Reviewer handoff for {system['name']} "
            f"(task {reviewed['task_id']}, review_status: {reviewed['review_status']}).",
            status="success",
            tool_result={
                "coordination_task": reviewed,
                "handoff_roles": ["coordinator", "investigator", "reviewer"],
                "system": system,
            },
            tool_name="coordinate_task",
        )

    path_match = _PATH_PATTERN.match(user_message)
    if path_match:
        src = (path_match.group("src1") or path_match.group("src2") or "").strip()
        dst = (path_match.group("dst1") or path_match.group("dst2") or "").strip()
        path_res = find_shortest_path(src, dst)
        if path_res["outcome"] == "unknown_entity":
            missing = ", ".join(path_res.get("missing_entities") or [])
            return _response(
                f"Could not resolve entity in graph: {missing}.",
                status="not_found",
                tool_result=path_res,
                tool_name="find_shortest_path",
            )
        if path_res["outcome"] == "not_in_graph":
            return _response(
                f"No relationship path connects '{src}' and '{dst}' in the graph.",
                status="success",
                tool_result=path_res,
                tool_name="find_shortest_path",
            )
        via_chain = " -> ".join(path_res.get("via") or [])
        return _response(
            f"Shortest path ({path_res['hops']} hop(s) via {path_res['algorithm']}): {via_chain}.",
            status="success",
            tool_result={"shortest_path": path_res},
            tool_name="find_shortest_path",
        )

    if _RANK_PATTERN.match(user_message):
        ranked = rank_critical_systems()
        top_names = ", ".join(
            f"{item['name']} ({round(float(item.get('score') or 0), 3)})"
            for item in (ranked.get("systems") or [])[:3]
        )
        return _response(
            f"Ranked critical systems using {ranked['algorithm']}: {top_names}.",
            status="success",
            tool_result={"critical_systems": ranked},
            tool_name="rank_critical_systems",
        )

    blast_match = _BLAST_RADIUS_PATTERN.match(user_message)
    if blast_match:
        target = blast_match.group("target").strip()
        depth = int(blast_match.group("depth") or 3)
        system = _resolve_system(target)
        if system is None:
            return _response(
                f"I could not find a system named or identified as '{target}'.",
                status="not_found",
            )
        deps = get_blast_radius(system["id"], depth=depth)
        return _response(
            f"Blast radius for {system['name']} (depth {depth}) reached {len(deps)} dependency(ies).",
            status="success",
            tool_result={
                "system": system,
                "depth": depth,
                "blast_radius": deps,
            },
            tool_name="get_blast_radius",
        )

    decisions_match = _DECISIONS_PATTERN.match(user_message)
    if decisions_match:
        target = decisions_match.group("target").strip()
        system = _resolve_system(target)
        if system is None:
            return _response(
                f"I could not find a system named or identified as '{target}'.",
                status="not_found",
            )
        decisions = get_system_decisions(system["id"])
        return _response(
            f"Found {len(decisions)} recorded decision(s) affecting {system['name']}.",
            status="success",
            tool_result={"system": system, "decisions": decisions},
            tool_name="get_system_decisions",
        )

    explore_match = _EXPLORE_PATTERN.match(user_message)
    if explore_match:
        target = explore_match.group("target").strip()
        context = explore_entity_context(target)
        if context["outcome"] == "unknown_entity":
            return _response(
                f"Entity '{target}' was not found in the graph.",
                status="not_found",
            )
        entity = context["entity"]
        return _response(
            f"Resolved {entity['label']} '{entity['name']}' [{entity['id']}] with "
            f"{len(context['connections'])} connected relationship(s).",
            status="success",
            tool_result={"entity_context": context},
            tool_name="explore_entity_context",
        )

    match = _INVESTIGATE_PATTERN.match(user_message)
    if match is None:
        return _response(
            "I support requests such as 'investigate Checkout' or "
            "'investigate system-checkout'.",
            status="unsupported",
        )

    target = match.group("target").strip()
    system = _resolve_system(target)
    if system is None:
        return _response(
            f"I could not find a system named or identified as '{target}'.",
            status="not_found",
        )

    result = investigate_system(system["id"])
    saved = save_investigation(system["id"], result)
    result["investigation_id"] = saved["investigation_id"]
    summary = result["summary"]
    message = (
        f"{summary} Findings are grounded in graph data; hypotheses are labeled "
        f"explicitly. Saved investigation {saved['investigation_id']}."
    )
    responders = result.get("recommended_responders") or []
    if responders:
        message += f" Potential responder: {responders[0].get('name')}."
    prior_count = len(result.get("memory_context", {}).get("prior_investigations", []))
    if prior_count:
        message += f" Reused {prior_count} prior investigation(s) for context."
    if result.get("memory_conflicts"):
        message += " Conflicting historical findings were flagged for review."
    return _response(
        message,
        status="success",
        tool_result=result,
        tool_name="investigate_system",
    )
