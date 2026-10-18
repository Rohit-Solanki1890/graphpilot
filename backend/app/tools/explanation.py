"""Normalize and explain graph-grounded investigation claims."""

from __future__ import annotations

from typing import Any


def standardize_findings(
    findings: list[dict[str, Any]],
    *,
    system_id: str,
    evidence: list[dict[str, Any]],
    unknowns: list[str],
) -> list[dict[str, Any]]:
    evidence_ids = [item.get("id") for item in evidence if item.get("id")]
    normalized = []
    for finding in findings:
        kind = finding.get("kind", "fact")
        path = finding.get("path")
        path_ids = [
            node.get("id")
            for node in (path or {}).get("nodes", [])
            if isinstance(node, dict) and node.get("id")
        ]
        relationships = finding.get("relationships") or []
        status = finding.get("fact_status") or (
            "hypothesis" if kind == "hypothesis" else "verified"
        )
        rationale = (
            "Observed directly in the graph and linked to the cited entity IDs."
            if status == "verified"
            else "Inference from connected graph relationships; causation is not established."
        )
        normalized.append(
            {
                **finding,
                "kind": kind,
                "fact_status": status,
                "evidence_ids": finding.get("evidence_ids") or evidence_ids,
                "path_ids": finding.get("path_ids") or path_ids,
                "relationships": relationships,
                "confidence_rationale": finding.get("confidence_rationale") or rationale,
                "unknowns": finding.get("unknowns") or (
                    ["Causation is not established by graph connectivity."]
                    if kind == "hypothesis"
                    else []
                ),
                "provenance": {
                    **(finding.get("provenance") or {}),
                    "system_id": system_id,
                    "evidence_ids": finding.get("evidence_ids") or evidence_ids,
                    "path_ids": finding.get("path_ids") or path_ids,
                },
            }
        )
    return normalized


def explain_investigation(
    result: dict[str, Any],
    *,
    tool_name: str | None = None,
    tool_reason: str | None = None,
) -> dict[str, Any]:
    """Return a concise audit explanation without inventing evidence.

    ``tool_name`` and ``tool_reason`` allow the caller to record the actual
    registered tool that was selected (e.g. ``get_system_overview`` when Ollama
    chose a different tool than ``investigate_system``).  Both parameters
    default to the investigation-tool values so that all existing call sites
    remain backward-compatible without any change.
    """
    findings = result.get("findings") or []
    sources = result.get("evidence") or []
    explanation = {
        "selected_tool": tool_name or "investigate_system",
        "selection_reason": tool_reason or (
            "The request targeted a system and required connected graph evidence."
        ),
        "claims": [
            {
                "statement": finding.get("statement"),
                "status": finding.get("fact_status") or finding.get("kind"),
                "evidence_ids": finding.get("evidence_ids") or [],
                "path_ids": finding.get("path_ids") or [],
                "confidence_rationale": finding.get("confidence_rationale"),
                "unknowns": finding.get("unknowns") or [],
            }
            for finding in findings
        ],
        "sources_consulted": [
            {"id": source.get("id"), "title": source.get("title"), "source": source.get("source")}
            for source in sources
        ],
        "uncertainties": result.get("unknowns") or [],
        "next_step": (
            "Review flagged conflicts before taking action."
            if result.get("memory_conflicts")
            else "Confirm ownership and availability before assigning follow-up work."
        ),
    }
    return explanation
