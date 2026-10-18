from types import SimpleNamespace

from app.agent import ollama_agent


def test_dispatch_tool_uses_explicit_registry(monkeypatch):
    monkeypatch.setattr(
        ollama_agent,
        "get_system",
        lambda value: {"id": "system-checkout", "name": "Checkout"},
    )
    monkeypatch.setattr(
        ollama_agent,
        "investigate_system",
        lambda system_id: {
            "system": {"id": system_id},
            "summary": "Checkout is degraded.",
            "findings": [],
        },
    )
    monkeypatch.setattr(
        "app.graph.save_investigation",
        lambda system_id, result: {"investigation_id": "investigation-test"},
    )

    result = ollama_agent.dispatch_tool(
        "investigate_system",
        {"system_id_or_name": "Checkout"},
    )

    assert result["investigation_id"] == "investigation-test"


def test_dispatch_tool_rejects_unknown_or_invalid_tools():
    try:
        ollama_agent.dispatch_tool("run_cypher", {})
    except ValueError as exc:
        assert "Unsupported tool" in str(exc)
    else:
        raise AssertionError("unknown tools must be rejected")

    try:
        ollama_agent.dispatch_tool("get_investigation", {"investigation_id": ""})
    except ValueError as exc:
        assert "non-empty" in str(exc)
    else:
        raise AssertionError("invalid arguments must be rejected")


def test_run_ollama_turn_executes_tool_then_returns_model_answer(monkeypatch):
    calls = []

    def fake_chat(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return SimpleNamespace(
                message=SimpleNamespace(
                    content="",
                    tool_calls=[
                        SimpleNamespace(
                            function=SimpleNamespace(
                                name="get_investigation",
                                arguments={"investigation_id": "investigation-1"},
                            )
                        )
                    ],
                )
            )
        return SimpleNamespace(
            message=SimpleNamespace(
                content="Historical result: the previous investigation found a degraded system.",
                tool_calls=[],
            )
        )

    monkeypatch.setattr("ollama.chat", fake_chat)
    monkeypatch.setattr(
        ollama_agent,
        "get_investigation",
        lambda investigation_id: {
            "investigation_id": investigation_id,
            "is_historical": True,
            "findings": [],
        },
    )

    result = ollama_agent.run_ollama_turn("Recall investigation investigation-1")

    assert result["status"] == "success"
    assert result["tool_used"] == "get_investigation"
    assert result["tool_result"]["is_historical"] is True
    assert len(calls) == 2
    assert any(message["role"] == "tool" for message in calls[1]["messages"])


def test_orchestrator_ollama_mode_falls_back_on_failure(monkeypatch):
    monkeypatch.setenv("GRAPHPILOT_AGENT_MODE", "ollama")
    monkeypatch.setattr(
        "app.agent.ollama_agent.run_ollama_turn",
        lambda message, model: (_ for _ in ()).throw(RuntimeError("Ollama unavailable")),
    )
    monkeypatch.setattr(
        "app.agent.orchestrator.get_system",
        lambda target: {"id": "system-checkout", "name": "Checkout"},
    )
    monkeypatch.setattr(
        "app.agent.orchestrator.investigate_system",
        lambda system_id: {"summary": "fallback", "system": {"id": system_id}, "findings": []},
    )
    monkeypatch.setattr(
        "app.agent.orchestrator.save_investigation",
        lambda system_id, result: {"investigation_id": "investigation-fallback"},
    )

    result = __import__("app.agent.orchestrator", fromlist=["run_turn"]).run_turn("Investigate Checkout")

    assert result["status"] == "success"
    assert result["llm_fallback"] == "Ollama unavailable"
