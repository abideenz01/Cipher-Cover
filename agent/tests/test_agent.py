from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from agent import main
from agent.stub import ScriptedModel
from backend.main import app

client = TestClient(app)


class StubModel(GenericFakeChatModel):
    """A chat model that gives scripted replies in place of a real model."""

    def bind_tools(self, tools, **kwargs):
        return self


def tool_call(name, **args):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": name}])


@pytest.fixture(autouse=True)
def local_backend(monkeypatch):
    monkeypatch.setattr(main, "backend", lambda: TestClient(app))


def test_run_approves_and_pays():
    steps = []
    reply = main.run("CLM-1001", "t1", ScriptedModel(), steps.append)
    assert reply == "Approved CLM-1001."
    calls = [s["name"] for s in steps if s["kind"] == "tool_call"]
    assert calls == [
        "get_claim",
        "get_policy",
        "get_customer_history",
        "calculate_payout",
        "record_decision",
        "pay_claim",
    ]
    claim = client.get("/api/claims/CLM-1001").json()
    assert claim["state"] == "decided"
    assert claim["decisions"][-1]["decision"] == "approve"
    assert claim["decisions"][-1]["model"] == "scripted"
    assert claim["payout"] == 420.0
    assert claim["paid"] == 420.0


def test_agent_cannot_pay_over_the_limit():
    steps = []
    main.run("CLM-1011", "t1", ScriptedModel(), steps.append)
    paid = [s for s in steps if s["kind"] == "tool_result" and s["name"] == "pay_claim"]
    assert "Waiting for a handler's sign-off." in paid[0]["detail"]["result"]
    claim = client.get("/api/claims/CLM-1011").json()
    assert claim["state"] == "waiting_for_signoff"
    assert claim["paid"] == 0


def test_tools():
    assert [t.name for t in main.TOOLS] == [
        "get_claim",
        "get_policy",
        "get_customer_history",
        "calculate_payout",
        "record_decision",
        "pay_claim",
    ]


def test_system_prompt_comes_from_the_api():
    model = ScriptedModel()
    main.run("CLM-1001", "t1", model)
    system = model.prompts[0][0].text
    assert client.get("/api/instructions").json()["text"] in system
    assert client.get("/api/wording").json()["text"] in system


def test_refusals_reach_the_agent():
    result = main.pay_claim.invoke({"claim_id": "CLM-1001", "amount": 5.0})
    assert result == {"error": "Only an approved claim can be paid."}


def test_plain_reply():
    model = StubModel(
        messages=iter([tool_call("get_claim", claim_id="CLM-1002"), AIMessage("Done.")])
    )
    assert main.run("CLM-1002", "t1", model) == "Done."


def test_agent_never_reads_the_answer_key():
    for path in Path("agent").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "evals" not in text
        assert "claims_manual" not in text


def test_model_name(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("MODEL_NAME", raising=False)
    assert main.model().model_name == "openai/gpt-6-luna"
    assert main.model_name() == "openai/gpt-6-luna"
    monkeypatch.setenv("MODEL_NAME", "openrouter/free")
    assert main.model().model_name == "openrouter/free"
