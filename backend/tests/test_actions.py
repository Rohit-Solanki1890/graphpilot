import json
from types import SimpleNamespace

import pytest

from app.graph.actions import execute_action, get_action, propose_action


class ActionGraph:
    def __init__(self):
        self.action = None
        self.executed_task = False

    def query(self, query, params=None):
        if "MERGE (a:Action" in query:
            self.action = {
                "id": params["action_id"],
                "tenant_id": params["tenant_id"],
                "type": params["type"],
                "status": "proposed",
                "approval_required": True,
                "payload_json": params["payload_json"],
                "evidence_ids_json": params["evidence_ids_json"],
                "rationale": params["rationale"],
                "target_system_id": params["target_system_id"],
                "created_at": params["timestamp"],
                "updated_at": params["timestamp"],
                "approved_at": None,
                "executed_at": None,
                "execution_result_json": "{}",
            }
            return SimpleNamespace(result_set=[[self.action["id"]]])
        if "SET a.status = 'rejected'" in query:
            self.action["status"] = "rejected"
            self.action["execution_result_json"] = params["result_json"]
        elif "SET a.status = 'approved'" in query:
            self.action["status"] = "approved"
        elif "SET a.status = 'executed'" in query:
            self.action["status"] = "executed"
            self.action["execution_result_json"] = params["result_json"]
            self.executed_task = "CREATED_TASK" in query
        elif "MATCH (a:Action" in query and "RETURN a.id" in query:
            return SimpleNamespace(result_set=[[
                self.action[key]
                for key in (
                    "id", "tenant_id", "type", "status", "approval_required",
                    "payload_json", "evidence_ids_json", "rationale",
                    "target_system_id", "created_at", "updated_at",
                    "approved_at", "executed_at", "execution_result_json",
                )
            ]] if self.action else [])
        return SimpleNamespace(result_set=[])


def test_action_requires_approval_and_records_execution():
    graph = ActionGraph()
    action = propose_action(
        "create_follow_up_task",
        {"title": "Review checkout dependency"},
        target_system_id="system-checkout",
        evidence_ids=["doc-runbook"],
        rationale="Dependency path and incident evidence require follow-up.",
        tenant_id="tenant-a",
        graph=graph,
    )
    assert action["status"] == "proposed"

    rejected = execute_action(action["action_id"], tenant_id="tenant-a", graph=graph)
    assert rejected["status"] == "rejected"
    assert graph.executed_task is False

    action = propose_action(
        "create_follow_up_task",
        {"title": "Review checkout dependency"},
        target_system_id="system-checkout",
        tenant_id="tenant-a",
        graph=graph,
    )
    executed = execute_action(
        action["action_id"], approve=True, tenant_id="tenant-a", graph=graph
    )
    assert executed["status"] == "executed"
    assert graph.executed_task is True


def test_action_payload_validation_rejects_unknown_or_incomplete_actions():
    with pytest.raises(ValueError):
        propose_action(
            "delete_system",
            {},
            target_system_id="system-checkout",
            graph=ActionGraph(),
        )
    with pytest.raises(ValueError):
        propose_action(
            "create_follow_up_task",
            {},
            target_system_id="system-checkout",
            graph=ActionGraph(),
        )
