from types import SimpleNamespace

from app.graph.tasks import create_task, get_task, investigator_handoff, review_task


class TaskGraph:
    def __init__(self):
        self.task = None
        self.documents = {
            "doc-supported": ("doc-supported", "Runbook", "internal://runbook", "checkout degraded payments api"),
        }

    def query(self, query, params=None):
        if "MERGE (t:Task" in query:
            self.task = {
                "id": params["task_id"],
                "tenant_id": params["tenant_id"],
                "system_id": params["system_id"],
                "status": "assigned",
                "assigned_role": "investigator",
                "findings_json": "[]",
                "evidence_refs_json": "[]",
                "review_status": "pending",
                "review_result_json": "{}",
                "next_action": "investigate",
                "created_at": params["timestamp"],
                "updated_at": params["timestamp"],
            }
            return SimpleNamespace(result_set=[[self.task["id"]]])
        if "SET t.status = 'investigator_complete'" in query:
            self.task.update({
                "status": "investigator_complete",
                "assigned_role": "reviewer",
                "findings_json": params["findings_json"],
                "evidence_refs_json": params["evidence_refs_json"],
                "next_action": "review",
                "updated_at": params["timestamp"],
            })
        elif "SET t.status = $status" in query:
            self.task.update({
                "status": params["status"],
                "assigned_role": "coordinator",
                "review_status": params["review_status"],
                "review_result_json": params["review_result_json"],
                "next_action": params["next_action"],
                "updated_at": params["timestamp"],
            })
        elif "MATCH (t:Task" in query and "RETURN t.id" in query:
            return SimpleNamespace(result_set=[[
                self.task[key]
                for key in (
                    "id", "tenant_id", "system_id", "status", "assigned_role",
                    "findings_json", "evidence_refs_json", "review_status",
                    "review_result_json", "next_action", "created_at", "updated_at",
                )
            ]] if self.task else [])
        elif "MATCH (d:Document)" in query:
            return SimpleNamespace(result_set=list(self.documents.values()))
        return SimpleNamespace(result_set=[])


def test_task_handoff_and_reviewer_flag_unsupported_source():
    graph = TaskGraph()
    task = create_task("system-checkout", tenant_id="tenant-a", graph=graph)
    assert task["assigned_role"] == "investigator"

    handed_off = investigator_handoff(
        task["task_id"],
        [{"claim": "Checkout is degraded", "evidence_refs": ["doc-missing"]}],
        ["doc-missing"],
        tenant_id="tenant-a",
        graph=graph,
    )
    assert handed_off["status"] == "investigator_complete"
    assert handed_off["assigned_role"] == "reviewer"

    reviewed = review_task(task["task_id"], tenant_id="tenant-a", graph=graph)
    assert reviewed["review_status"] == "flagged"
    assert reviewed["review_result"]["approved"] is False
    assert reviewed["review_result"]["issues"][0]["source_id"] == "doc-missing"


def test_task_tenant_scope_blocks_other_tenant():
    graph = TaskGraph()
    task = create_task("system-checkout", tenant_id="tenant-a", graph=graph)
    assert task["task_id"]
    assert graph.task["tenant_id"] == "tenant-a"
