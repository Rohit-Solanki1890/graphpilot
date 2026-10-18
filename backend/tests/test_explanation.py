from app.tools.explanation import explain_investigation, standardize_findings


def test_standardized_claim_contains_audit_fields():
    findings = standardize_findings(
        [{
            "kind": "hypothesis",
            "statement": "Payments API may be involved.",
            "entity_ids": ["system-checkout", "system-payments-api"],
            "path": {
                "nodes": [{"id": "system-checkout"}, {"id": "system-payments-api"}],
            },
        }],
        system_id="system-checkout",
        evidence=[{"id": "doc-runbook"}],
        unknowns=["Deployment timing is unknown."],
    )

    claim = findings[0]
    assert claim["fact_status"] == "hypothesis"
    assert claim["evidence_ids"] == ["doc-runbook"]
    assert claim["path_ids"] == ["system-checkout", "system-payments-api"]
    assert claim["confidence_rationale"]
    assert claim["unknowns"]


def test_explanation_preserves_sources_and_uncertainty():
    explanation = explain_investigation({
        "findings": [{
            "statement": "System is degraded.",
            "fact_status": "verified",
            "evidence_ids": ["doc-1"],
            "path_ids": ["system-checkout"],
            "confidence_rationale": "Observed directly in the graph.",
            "unknowns": [],
        }],
        "evidence": [{"id": "doc-1", "title": "Runbook", "source": "internal://runbook"}],
        "unknowns": ["Root cause is unknown."],
    })

    # Default tool name is "investigate_system" for backward compatibility.
    assert explanation["selected_tool"] == "investigate_system"
    assert explanation["claims"][0]["evidence_ids"] == ["doc-1"]
    assert explanation["sources_consulted"][0]["id"] == "doc-1"
    assert explanation["uncertainties"] == ["Root cause is unknown."]


def test_explanation_records_actual_tool_when_supplied():
    """When Ollama calls a non-investigation tool the explanation must reflect
    the real tool name and reason, not the investigate_system defaults."""
    explanation = explain_investigation(
        {
            "findings": [],
            "evidence": [],
            "unknowns": [],
        },
        tool_name="get_system_overview",
        tool_reason="The request needed a high-level connected view of the system.",
    )

    assert explanation["selected_tool"] == "get_system_overview"
    assert "high-level" in explanation["selection_reason"]
    # Claims and sources are empty because the tool result has none — the
    # function must not fabricate entries.
    assert explanation["claims"] == []
    assert explanation["sources_consulted"] == []


def test_explanation_defaults_are_backward_compatible():
    """Callers that pass no tool_name must still get the investigate_system
    default, so no existing call site needs updating."""
    explanation = explain_investigation({"findings": [], "evidence": [], "unknowns": []})
    assert explanation["selected_tool"] == "investigate_system"
    assert explanation["selection_reason"]
