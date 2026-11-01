from pathlib import Path

import httpx2
import openai
import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from agent import main
from agent.stub import FaultyModel, ScriptedModel
from backend import runner, runs
from backend.main import app

client = TestClient(app)
REQUEST = httpx2.Request("POST", "https://openrouter.ai/api/v1/chat/completions")


class StubModel(GenericFakeChatModel):
    """A chat model that gives scripted replies in place of a real model."""

    def bind_tools(self, tools, **kwargs):
        return self


def tool_call(name, **args):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": name}])


def rate_limited():
    response = httpx2.Response(429, request=REQUEST)
    return openai.RateLimitError("Rate limited.", response=response, body=None)


def server_error():
    response = httpx2.Response(502, request=REQUEST)
    return openai.InternalServerError("Bad gateway.", response=response, body=None)


@pytest.fixture(autouse=True)
def local_backend(monkeypatch):
    monkeypatch.setattr(main, "backend", lambda: TestClient(app))
    monkeypatch.setattr(main, "RETRY_DELAY", 0)
    monkeypatch.setattr(runs, "spawn", lambda work: work())


def run_with(monkeypatch, claim_id, llm, seconds=120):
    """Start a named-claim run through the backend with the given model."""
    monkeypatch.setattr(
        runner,
        "execute",
        lambda claim_id, run_id, on_step: main.run(
            claim_id, run_id, llm, on_step, seconds
        ),
    )
    run_id = client.post(f"/api/claims/{claim_id}/runs").json()["run_id"]
    return client.get(f"/api/runs/{run_id}").json()


def test_run_approves_and_pays():
    steps = []
    reply = main.run("CLM-1001", runs.begin("CLM-1001"), ScriptedModel(), steps.append)
    assert reply == "Approved CLM-1001."
    calls = [s["name"] for s in steps if s["kind"] == "tool_call"]
    assert calls == [
        "get_claim",
        "get_policy",
        "get_customer_history",
        "read_section",
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


def test_a_run_records_what_it_read_and_used(monkeypatch):
    run = run_with(monkeypatch, "CLM-1001", ScriptedModel())
    assert run["status"] == "succeeded"
    assert run["sections_read"] == [
        {"id": "wording-10", "title": "Section 10. How we work out your payment"}
    ]
    assert run["model_calls"] == 8
    assert run["tokens"] == 800
    assert run["model"] == "scripted"
    decision = client.get("/api/claims/CLM-1001").json()["decisions"][-1]
    assert [s["id"] for s in decision["sections"]] == ["wording-10"]
    assert decision["run_id"] == run["run_id"]
    events = client.get(f"/api/runs/{run['run_id']}/events").json()
    assert "usage" not in {e["kind"] for e in events}


def test_agent_cannot_pay_over_the_limit():
    steps = []
    main.run("CLM-1011", runs.begin("CLM-1011"), ScriptedModel(), steps.append)
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
        "list_sections",
        "read_section",
        "calculate_payout",
        "record_decision",
        "pay_claim",
    ]
    schema = main.record_decision.args
    assert "run_id" not in schema
    assert "run_id" not in main.pay_claim.args


def test_system_prompt_is_the_claim_instructions_only():
    model = ScriptedModel()
    main.run("CLM-1001", runs.begin("CLM-1001"), model)
    system = model.prompts[0][0].text
    instructions = client.get("/api/instructions").json()["claim"]
    assert instructions in system
    assert len(system) < len(instructions) + 500
    assert "## 3. Trip Delay" not in system


def test_refusals_reach_the_agent():
    result = main.call("POST", "/api/claims/CLM-1001/pay", {"run_id": "", "amount": 5})
    assert result == {"error": "There is no live claim run ."}


def test_plain_reply():
    model = StubModel(
        messages=iter([tool_call("get_claim", claim_id="CLM-1002"), AIMessage("Done.")])
    )
    assert main.run("CLM-1002", runs.begin("CLM-1002"), model) == "Done."


def test_provider_errors_are_retried(monkeypatch):
    model = FaultyModel(errors=[rate_limited(), rate_limited()])
    run = run_with(monkeypatch, "CLM-1001", model)
    assert run["status"] == "succeeded"
    assert len(model.prompts) == 8
    assert client.get("/api/claims/CLM-1001").json()["failed_attempts"] == 0


def test_provider_errors_that_last_fail_the_claim(monkeypatch):
    run = run_with(monkeypatch, "CLM-1001", FaultyModel(always=server_error()))
    assert run["status"] == "failed"
    assert run["failure"] == "provider"
    claim = client.get("/api/claims/CLM-1001").json()
    assert claim["state"] == "waiting"
    assert claim["failed_attempts"] == 1


def test_the_step_limit(monkeypatch):
    monkeypatch.setenv("CLAIM_STEP_LIMIT", "5")
    run = run_with(monkeypatch, "CLM-1001", FaultyModel(loop=True))
    assert run["status"] == "failed"
    assert run["failure"] == "step_limit"
    assert run["model_calls"] == 5


def test_the_time_limit(monkeypatch):
    run = run_with(monkeypatch, "CLM-1001", ScriptedModel(), seconds=0)
    assert run["status"] == "failed"
    assert run["failure"] == "time_limit"
    assert client.get("/api/claims/CLM-1001").json()["state"] == "waiting"


def test_a_decision_citing_an_unread_section_is_corrected(monkeypatch):
    steps = []
    model = FaultyModel(cite_unread=True)
    run_id = runs.begin("CLM-1001")
    main.run("CLM-1001", run_id, model, steps.append)
    results = [
        s["detail"]["result"]
        for s in steps
        if s["kind"] == "tool_result" and s["name"] == "record_decision"
    ]
    assert "manual-9 was not read" in results[0]
    assert '"state": "decided"' in results[1]
    decision = client.get("/api/claims/CLM-1001").json()["decisions"][-1]
    assert [s["id"] for s in decision["sections"]] == ["wording-10", "manual-9"]


def test_failure_kinds():
    assert main.failure(rate_limited()) == "provider"
    assert main.failure(main.ClaimTimeout()) == "time_limit"
    assert main.failure(ValueError("x")) == "error"
    assert main.describe(ValueError()) == "ValueError"


def test_agent_never_reads_the_answer_key():
    for path in Path("agent").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "evals" not in text
        assert "claims_manual" not in text


def test_model_name(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("MODEL_NAME", raising=False)
    built = main.model()
    assert built.model_name == "deepseek/deepseek-v4.1-flash"
    assert built.reasoning_effort == "low"
    assert built.max_retries == 0
    assert main.model_name() == "deepseek/deepseek-v4.1-flash"
    monkeypatch.setenv("MODEL_NAME", "openrouter/free")
    assert main.model().model_name == "openrouter/free"
    assert main.model_name() == "openrouter/free"
