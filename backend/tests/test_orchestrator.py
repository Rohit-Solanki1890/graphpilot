from app.agent import orchestrator


def test_run_turn_investigates_system_by_name(monkeypatch):
    monkeypatch.setattr(
        orchestrator,
        "get_system",
        lambda target: None,
    )
    monkeypatch.setattr(
        orchestrator,
        "get_system_by_name",
        lambda target: {"id": "system-checkout", "name": "Checkout"},
    )
    investigation = {
        "system": {"id": "system-checkout", "name": "Checkout", "status": "degraded"},
        "summary": "Checkout is degraded.",
        "findings": [{"kind": "fact", "statement": "System status is 'degraded'."}],
        "related_incidents": [],
        "dependencies": [],
        "experts": [],
        "evidence": [],
        "recommended_responders": [{"name": "Ava Patel"}],
        "unknowns": [],
    }
    monkeypatch.setattr(orchestrator, "investigate_system", lambda system_id: investigation)
    monkeypatch.setattr(
        orchestrator,
        "save_investigation",
        lambda system_id, result: {"investigation_id": "investigation-test"},
    )

    result = orchestrator.run_turn("Investigate Checkout")

    assert result["status"] == "success"
    assert result["tool_used"] == "investigate_system"
    assert result["tool_result"] is investigation
    assert "Checkout is degraded." in result["message"]
    assert "hypotheses are labeled explicitly" in result["message"]
    assert result["tool_result"]["investigation_id"] == "investigation-test"
    assert "Potential responder: Ava Patel." in result["message"]


def test_run_turn_reports_missing_system(monkeypatch):
    monkeypatch.setattr(orchestrator, "get_system", lambda target: None)
    monkeypatch.setattr(orchestrator, "get_system_by_name", lambda target: None)

    result = orchestrator.run_turn("investigate Unknown Service")

    assert result == {
        "message": "I could not find a system named or identified as 'Unknown Service'.",
        "tool_used": None,
        "tool_result": None,
        "status": "not_found",
    }


def test_run_turn_reports_unsupported_request():
    result = orchestrator.run_turn("List all incidents")

    assert result["status"] == "unsupported"
    assert result["tool_used"] is None
    assert result["tool_result"] is None


def test_run_turn_recalls_historical_investigation(monkeypatch):
    memory = {
        "investigation_id": "investigation-1",
        "system_id": "system-checkout",
        "summary": "Checkout was degraded.",
        "findings": [{"kind": "hypothesis", "description": "Historical lead"}],
        "is_historical": True,
    }
    monkeypatch.setattr(orchestrator, "get_investigation", lambda investigation_id: memory)

    result = orchestrator.run_turn("recall investigation investigation-1")

    assert result["status"] == "success"
    assert result["tool_used"] == "get_investigation"
    assert result["tool_result"]["is_historical"] is True
    assert "not newly verified" in result["message"]


def test_run_turn_lists_recent_investigations(monkeypatch):
    monkeypatch.setattr(orchestrator, "get_system", lambda target: {"id": "system-checkout", "name": "Checkout"})
    monkeypatch.setattr(orchestrator, "get_recent_investigations", lambda system_id: [{"investigation_id": "investigation-1"}])

    result = orchestrator.run_turn("list investigations for Checkout")

    assert result["status"] == "success"
    assert result["tool_used"] == "get_recent_investigations"
    assert result["tool_result"]["investigations"][0]["investigation_id"] == "investigation-1"


def test_run_turn_proposes_and_approves_action(monkeypatch):
    monkeypatch.setattr(
        orchestrator,
        "get_system",
        lambda target: {"id": "system-checkout", "name": "Checkout"},
    )
    monkeypatch.setattr(
        orchestrator,
        "get_system_documents",
        lambda system_id: [{"id": "doc-checkout-runbook"}],
    )
    monkeypatch.setattr(
        orchestrator,
        "propose_action",
        lambda action_type, payload, **kwargs: {
            "action_id": "action-123",
            "status": "proposed",
            "type": action_type,
            "approval_required": True,
            "rationale": kwargs.get("rationale"),
        },
    )
    monkeypatch.setattr(
        orchestrator,
        "execute_action",
        lambda action_id, approve=False: {
            "action_id": action_id,
            "status": "executed" if approve else "rejected",
            "type": "create_follow_up_task",
            "approval_required": True,
        },
    )

    prop = orchestrator.run_turn("propose follow-up task for Checkout")
    assert prop["status"] == "success"
    assert prop["tool_used"] == "propose_action"
    assert prop["tool_result"]["action"]["status"] == "proposed"

    exec_res = orchestrator.run_turn("approve action action-123")
    assert exec_res["status"] == "success"
    assert exec_res["tool_used"] == "execute_action"
    assert exec_res["tool_result"]["action"]["status"] == "executed"


def test_run_turn_coordinates_multi_agent_handoff(monkeypatch):
    monkeypatch.setattr(
        orchestrator,
        "get_system",
        lambda target: {"id": "system-checkout", "name": "Checkout"},
    )
    monkeypatch.setattr(
        orchestrator,
        "create_task",
        lambda system_id: {"task_id": "task-1", "system_id": system_id, "status": "assigned"},
    )
    monkeypatch.setattr(
        orchestrator,
        "investigate_system",
        lambda system_id: {
            "findings": [{"kind": "fact", "statement": "Checkout latency check"}],
            "evidence": [{"id": "doc-checkout-runbook"}],
        },
    )
    monkeypatch.setattr(
        orchestrator,
        "investigator_handoff",
        lambda task_id, claims, refs: {"task_id": task_id, "status": "investigator_complete"},
    )
    monkeypatch.setattr(
        orchestrator,
        "review_task",
        lambda task_id: {
            "task_id": task_id,
            "tenant_id": "default",
            "status": "reviewed",
            "review_status": "approved",
            "next_action": "close",
            "evidence_refs": ["doc-checkout-runbook"],
            "review_result": {"approved": True, "checked_findings": 1, "issues": []},
        },
    )

    res = orchestrator.run_turn("coordinate Checkout")
    assert res["status"] == "success"
    assert res["tool_used"] == "coordinate_task"
    assert res["tool_result"]["coordination_task"]["review_status"] == "approved"


def test_run_turn_executes_shortest_path_and_pagerank(monkeypatch):
    monkeypatch.setattr(
        orchestrator,
        "find_shortest_path",
        lambda src, dst: {
            "outcome": "answered_with_path",
            "algorithm": "algo.SPpaths",
            "hops": 2,
            "via": ["Person:Ava Patel", "Project:Checkout Reliability", "System:Checkout"],
        },
    )
    monkeypatch.setattr(
        orchestrator,
        "rank_critical_systems",
        lambda: {
            "algorithm": "algo.pageRank",
            "systems": [{"id": "system-event-stream", "name": "Event Stream", "status": "healthy", "score": 0.45}],
        },
    )

    path_turn = orchestrator.run_turn("path from Ava Patel to Checkout")
    assert path_turn["status"] == "success"
    assert path_turn["tool_used"] == "find_shortest_path"
    assert "algo.SPpaths" in path_turn["message"]

    rank_turn = orchestrator.run_turn("rank critical systems")
    assert rank_turn["status"] == "success"
    assert rank_turn["tool_used"] == "rank_critical_systems"
    assert "Event Stream" in rank_turn["message"]
