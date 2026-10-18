"""Optional Ollama tool-calling agent for GraphPilot."""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from redis.exceptions import RedisError

from app.graph import (
    create_task,
    explore_entity_context,
    find_shortest_path,
    get_blast_radius,
    get_investigation,
    get_people_for_incident,
    get_recent_investigations,
    get_system,
    get_system_by_name,
    get_system_decisions,
    get_system_overview,
    investigator_handoff,
    propose_action,
    rank_critical_systems,
    resolve_entity,
    review_task,
)
from app.tools import investigate_system

ToolFunction = Callable[[dict[str, Any]], dict[str, Any] | list[dict[str, Any]] | None]

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "investigate_system",
            "description": "Investigate an engineering system using graph facts, multi-hop paths, incidents, decisions, experts, and evidence.",
            "parameters": {
                "type": "object",
                "properties": {"system_id_or_name": {"type": "string"}},
                "required": ["system_id_or_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_system_overview",
            "description": "Retrieve the current connected graph overview for an engineering system.",
            "parameters": {
                "type": "object",
                "properties": {"system_id_or_name": {"type": "string"}},
                "required": ["system_id_or_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recent_investigations",
            "description": "List historical investigations saved for a system.",
            "parameters": {
                "type": "object",
                "properties": {"system_id": {"type": "string"}},
                "required": ["system_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_investigation",
            "description": "Recall one historical investigation by its ID.",
            "parameters": {
                "type": "object",
                "properties": {"investigation_id": {"type": "string"}},
                "required": ["investigation_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_people_for_incident",
            "description": (
                "Find people who worked on projects using systems involved "
                "in a specific incident. Requires the exact incident ID. "
                "This does not establish that those people caused the incident."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "incident_id": {
                        "type": "string",
                        "description": "The exact ID of an incident found in graph data.",
                    }
                },
                "required": ["incident_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resolve_entity",
            "description": "Resolve any Person, Team, Project, System, Incident, Document, or Decision by name or ID and inspect its direct relationships.",
            "parameters": {
                "type": "object",
                "properties": {"entity_id_or_name": {"type": "string"}},
                "required": ["entity_id_or_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_shortest_path",
            "description": "Run FalkorDB shortest-path analysis (algo.SPpaths / shortestPath) to explain how any two entities in the company graph are connected.",
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "target": {"type": "string"},
                },
                "required": ["source", "target"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rank_critical_systems",
            "description": "Run FalkorDB PageRank (algo.pageRank) over system dependencies to identify structurally load-bearing systems.",
            "parameters": {
                "type": "object",
                "properties": {"limit": {"type": "integer"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_blast_radius",
            "description": "Traverse variable-length DEPENDS_ON paths (*1..depth) for a system to find direct and transitive dependencies.",
            "parameters": {
                "type": "object",
                "properties": {
                    "system_id_or_name": {"type": "string"},
                    "depth": {"type": "integer"},
                },
                "required": ["system_id_or_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_system_decisions",
            "description": "Trace architectural and operational decisions affecting a system back to their authors, documents, and superseded decisions.",
            "parameters": {
                "type": "object",
                "properties": {"system_id_or_name": {"type": "string"}},
                "required": ["system_id_or_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_follow_up_action",
            "description": "Propose an approval-gated follow-up task for a system grounded in graph evidence.",
            "parameters": {
                "type": "object",
                "properties": {
                    "system_id_or_name": {"type": "string"},
                    "title": {"type": "string"},
                    "rationale": {"type": "string"},
                },
                "required": ["system_id_or_name", "title"],
            },
        },
    },
]


def _required_string(arguments: dict[str, Any], name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _resolve_system(value: str) -> dict[str, Any] | None:
    return get_system(value) or get_system_by_name(value)


def _investigate(arguments: dict[str, Any]) -> dict[str, Any]:
    target = _required_string(arguments, "system_id_or_name")
    system = _resolve_system(target)
    if system is None:
        return {"status": "not_found", "message": f"System '{target}' was not found."}
    result = investigate_system(system["id"])
    from app.graph import save_investigation

    saved = save_investigation(system["id"], result)
    result["investigation_id"] = saved["investigation_id"]
    return result


def _people_for_incident(arguments: dict[str, Any]) -> list[dict[str, Any]]:
    incident_id = _required_string(arguments, "incident_id")
    return get_people_for_incident(incident_id)


def _overview(arguments: dict[str, Any]) -> dict[str, Any]:
    target = _required_string(arguments, "system_id_or_name")
    system = _resolve_system(target)
    return get_system_overview(system["id"]) if system else {
        "status": "not_found",
        "message": f"System '{target}' was not found.",
    }


def _recent(arguments: dict[str, Any]) -> list[dict[str, Any]] | dict[str, str]:
    system_id = _required_string(arguments, "system_id")
    return get_recent_investigations(system_id)


def _recall(arguments: dict[str, Any]) -> dict[str, Any] | None:
    return get_investigation(_required_string(arguments, "investigation_id"))


def _resolve_entity_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    target = _required_string(arguments, "entity_id_or_name")
    return explore_entity_context(target)


def _shortest_path_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    source = _required_string(arguments, "source")
    target = _required_string(arguments, "target")
    return {"shortest_path": find_shortest_path(source, target)}


def _rank_systems_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    limit = int(arguments.get("limit") or 5)
    return {"critical_systems": rank_critical_systems(limit=max(1, min(limit, 20)))}


def _blast_radius_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    target = _required_string(arguments, "system_id_or_name")
    depth = int(arguments.get("depth") or 3)
    system = _resolve_system(target)
    if system is None:
        return {"status": "not_found", "message": f"System '{target}' was not found."}
    return {
        "system": system,
        "depth": max(1, min(depth, 4)),
        "blast_radius": get_blast_radius(system["id"], depth=max(1, min(depth, 4))),
    }


def _decisions_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    target = _required_string(arguments, "system_id_or_name")
    system = _resolve_system(target)
    if system is None:
        return {"status": "not_found", "message": f"System '{target}' was not found."}
    return {
        "system": system,
        "decisions": get_system_decisions(system["id"]),
    }


def _propose_action_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    target = _required_string(arguments, "system_id_or_name")
    title = _required_string(arguments, "title")
    rationale = str(arguments.get("rationale") or "Proposed by agent from graph evidence.")
    system = _resolve_system(target)
    if system is None:
        return {"status": "not_found", "message": f"System '{target}' was not found."}
    action = propose_action(
        "create_follow_up_task",
        {"title": title},
        target_system_id=system["id"],
        rationale=rationale,
    )
    return {"action": action}


TOOL_REGISTRY: dict[str, ToolFunction] = {
    "investigate_system": _investigate,
    "get_system_overview": _overview,
    "get_recent_investigations": _recent,
    "get_investigation": _recall,
    "get_people_for_incident": _people_for_incident,
    "resolve_entity": _resolve_entity_tool,
    "find_shortest_path": _shortest_path_tool,
    "rank_critical_systems": _rank_systems_tool,
    "get_blast_radius": _blast_radius_tool,
    "get_system_decisions": _decisions_tool,
    "propose_follow_up_action": _propose_action_tool,
}

_TOOL_REASONS: dict[str, str] = {
    "investigate_system": "The request targeted a system and required full connected graph evidence.",
    "get_system_overview": "The request needed a high-level connected view of the system.",
    "get_recent_investigations": "The request asked for historical investigation records.",
    "get_investigation": "The request recalled one specific historical investigation.",
    "get_people_for_incident": "The request asked who worked on projects connected to a specific incident.",
    "resolve_entity": "The request asked to resolve an entity and inspect its graph neighborhood.",
    "find_shortest_path": "The request asked how two entities are connected across the graph.",
    "rank_critical_systems": "The request asked to rank load-bearing or critical systems using PageRank.",
    "get_blast_radius": "The request asked for multi-hop dependency impact analysis.",
    "get_system_decisions": "The request asked to trace architectural decisions and their source documents.",
    "propose_follow_up_action": "The request asked to propose a human-approved follow-up action.",
}


def dispatch_tool(name: str, arguments: dict[str, Any]) -> Any:
    """Validate and dispatch only registered, bounded tools."""
    function = TOOL_REGISTRY.get(name)
    if function is None:
        raise ValueError(f"Unsupported tool: {name}")
    if not isinstance(arguments, dict):
        raise ValueError("Tool arguments must be an object")
    return function(arguments)


def _json(value: Any) -> str:
    return json.dumps(value, default=str)


def run_ollama_turn(
    user_message: str,
    *,
    model: str = "qwen3:4b",
    max_tool_calls: int = 3,
) -> dict[str, Any]:
    """Run one bounded Ollama tool loop and return the standard turn shape."""
    from ollama import chat

    system_prompt = (
        "You are GraphPilot, a graph-powered engineering and organizational intelligence agent. "
        "Use registered tools for graph facts, shortest paths, PageRank, decisions, and historical memory. "
        "Never invent entity IDs, evidence, or causation. "
        "Use get_people_for_incident only when an exact incident ID is "
        "available from the user's message or previous tool results. "
        "Use find_shortest_path to explain how any two entities connect. "
        "Use rank_critical_systems to identify load-bearing systems. "
        "Use get_system_decisions to trace decisions back to their authors and documents. "
        "Clearly distinguish historical results, facts, hypotheses, unknowns, "
        "and recommendations. Cite IDs and relationship paths returned by tools."
    )
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]
    tool_names: list[str] = []
    tool_results: list[Any] = []

    for _ in range(max_tool_calls):
        response = chat(
            model=model,
            messages=messages,
            tools=TOOL_DEFINITIONS,
            options={"temperature": 0},
        )
        message = response.message
        tool_calls = message.tool_calls or []
        if not tool_calls:
            final_result = tool_results[-1] if tool_results else None
            if isinstance(final_result, dict) and "explanation" not in final_result:
                from app.tools.explanation import explain_investigation

                used_tool = tool_names[-1] if tool_names else None
                final_result["explanation"] = explain_investigation(
                    final_result,
                    tool_name=used_tool,
                    tool_reason=_TOOL_REASONS.get(used_tool or "") if used_tool else None,
                )
            return {
                "message": message.content or "No answer was returned by the model.",
                "tool_used": tool_names[-1] if tool_names else None,
                "tool_result": final_result,
                "status": "success",
            }

        messages.append(
            {
                "role": "assistant",
                "content": message.content or "",
                "tool_calls": [
                    {
                        "function": {
                            "name": call.function.name,
                            "arguments": call.function.arguments,
                        }
                    }
                    for call in tool_calls
                ],
            }
        )
        for call in tool_calls:
            name = call.function.name
            arguments = call.function.arguments
            try:
                result = dispatch_tool(name, arguments)
            except (ValueError, TypeError, RuntimeError, RedisError) as exc:
                result = {"status": "error", "message": str(exc)}
            tool_names.append(name)
            tool_results.append(result)
            messages.append(
                {
                    "role": "tool",
                    "tool_name": name,
                    "content": _json(result),
                }
            )

    return {
        "message": "The tool-calling limit was reached before a final answer was produced.",
        "tool_used": tool_names[-1] if tool_names else None,
        "tool_result": tool_results[-1] if tool_results else None,
        "status": "error",
    }
