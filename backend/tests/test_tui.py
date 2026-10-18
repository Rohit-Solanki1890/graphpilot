from app.tui import ApprovalDecision, format_turn


def test_format_turn_separates_facts_hypotheses_and_evidence():
    lines = format_turn(
        {
            "message": "Checkout is degraded.",
            "status": "success",
            "tool_result": {
                "system": {
                    "id": "system-checkout",
                    "name": "Checkout",
                    "description": "Payments",
                    "status": "degraded",
                },
                "findings": [
                    {
                        "kind": "fact",
                        "statement": "System status is 'degraded'.",
                        "entity_ids": ["system-checkout"],
                    },
                    {
                        "kind": "hypothesis",
                        "statement": "A dependency may be involved.",
                        "entity_ids": ["system-checkout", "system-api"],
                    },
                ],
                "related_incidents": [{"id": "incident-1", "title": "Timeouts", "severity": "SEV-2", "status": "open"}],
                "dependencies": [{"id": "system-api", "name": "Payments API", "status": "healthy"}],
                "experts": [{"id": "person-ava", "name": "Ava Patel", "role": "Engineer"}],
                "recommended_responders": [
                    {
                        "id": "person-ava",
                        "name": "Ava Patel",
                        "role": "Engineer",
                        "reason": "Worked on Checkout Reliability.",
                    }
                ],
                "evidence": [{"id": "doc-1", "title": "Runbook", "source": "internal://runbook"}],
                "memory_context": {
                    "prior_investigations": [
                        {
                            "investigation_id": "investigation-old",
                            "created_at": "2026-10-15T12:00:00+00:00",
                            "summary": "Earlier review",
                        }
                    ]
                },
                "memory_conflicts": [
                    {
                        "prior_investigation_id": "investigation-old",
                        "message": "Historical and current findings differ; review both sources.",
                    }
                ],
                "procedure": {
                    "completed_steps": ["Verify the target system and current status."],
                    "remaining_steps": ["Review source documents and explicit graph paths."],
                },
                "unknowns": [],
            },
        }
    )

    facts = lines.index("Facts")
    hypotheses = lines.index("Hypotheses")
    assert facts < hypotheses
    assert "  - System status is 'degraded'. (entities: system-checkout)" in lines
    assert "  - A dependency may be involved. (entities: system-checkout, system-api)" in lines
    assert "Incidents" in lines
    assert "  - Timeouts — SEV-2 — open — incident-1" in lines
    assert "Dependencies" in lines
    assert "Experts" in lines
    assert "Potential Responders" in lines
    assert "Evidence" in lines
    assert "Prior investigations" in lines
    assert any("investigation-old" in line and "historical" in line for line in lines)
    assert "Memory conflicts" in lines
    assert "Procedure" in lines


def test_format_turn_handles_missing_and_unsupported_results():
    assert format_turn(
        {
            "message": "I could not find the system.",
            "status": "not_found",
            "tool_result": None,
        }
    ) == [
        "GraphPilot: I could not find the system.",
        "Status: NOT_FOUND",
    ]


def test_format_turn_shows_explanation_and_action_gate():
    lines = format_turn({
        "message": "Proposed action action-1; approval is required before execution.",
        "status": "success",
        "tool_result": {
            "action": {
                "action_id": "action-1",
                "status": "proposed",
                "type": "create_follow_up_task",
                "approval_required": True,
                "rationale": "Evidence-backed follow-up.",
            }
        },
    })
    assert "Action" in lines
    assert any("action-1 [proposed]" in line for line in lines)
    assert "  Approval required: True" in lines


def test_format_turn_renders_list_shaped_recent_investigations():
    lines = format_turn(
        {
            "message": "I found previous investigations.",
            "status": "success",
            "tool_used": "get_recent_investigations",
            "tool_result": [
                {
                    "investigation_id": "investigation-1",
                    "status": "completed",
                    "summary": "Checkout was degraded.",
                    "created_at": "2026-10-15T12:00:00+00:00",
                    "system_id": "system-checkout",
                    "evidence_ids": ["doc-checkout-runbook"],
                    "paths": [
                        {
                            "kind": "incident_dependency",
                            "nodes": [
                                {"label": "Incident", "id": "incident-timeouts"},
                                {"label": "System", "id": "system-checkout"},
                            ],
                        }
                    ],
                    "findings": [
                        {
                            "description": "Historical hypothesis",
                            "fact_status": "hypothesis",
                        }
                    ],
                }
            ],
        }
    )

    assert "Historical investigations" in lines
    assert any("investigation-1" in line and "Checkout was degraded." in line for line in lines)
    assert "    Evidence: doc-checkout-runbook" in lines
    assert "    Paths:" in lines
    assert any("incident_dependency" in line for line in lines)
    assert "      - [hypothesis] Historical hypothesis" in lines


def test_format_turn_handles_non_mapping_tool_result_without_crashing():
    lines = format_turn(
        {
            "message": "The tool returned a scalar.",
            "status": "success",
            "tool_result": "unexpected",
        }
    )

    assert "Tool result: unexpected" in lines


def test_approval_decision_message_carries_correct_fields():
    """ApprovalDecision is a Textual Message — verify it stores the action ID
    and decision string so the app handler can dispatch the right command."""
    msg = ApprovalDecision("action-abc", "approve")
    assert msg.action_id == "action-abc"
    assert msg.decision == "approve"

    msg_reject = ApprovalDecision("action-xyz", "reject")
    assert msg_reject.decision == "reject"


def test_approval_decision_is_distinct_per_instance():
    """Two separate decisions must not share state."""
    a = ApprovalDecision("action-1", "approve")
    b = ApprovalDecision("action-2", "reject")
    assert a.action_id != b.action_id
    assert a.decision != b.decision
