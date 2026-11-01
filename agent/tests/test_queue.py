from contextlib import nullcontext

import httpx2
import openai
import pytest
from fastapi.testclient import TestClient

from agent import main, queue
from agent.stub import FaultyModel, QueueScript, ScriptedModel
from backend import runner, runs
from backend.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def inline(monkeypatch):
    monkeypatch.setattr(main, "backend", lambda: nullcontext(client))
    monkeypatch.setattr(main, "RETRY_DELAY", 0)
    monkeypatch.setattr(runs, "spawn", lambda work: work())


def run_with(monkeypatch, cap, llm, claim_llm):
    monkeypatch.setattr(
        runner,
        "execute_queue",
        lambda run_id, on_step: queue.run_queue(run_id, llm, claim_llm, on_step),
    )
    run_id = client.post("/api/runs", json={"cap": cap}).json()["run_id"]
    return client.get(f"/api/queue-runs/{run_id}").json()


def states():
    return {c["claim_id"]: c["state"] for c in client.get("/api/claims").json()}


def test_a_capped_run_works_three_claims(monkeypatch):
    monkeypatch.setenv("AGENT_STUB", "1")
    run_id = client.post("/api/runs", json={"cap": 3}).json()["run_id"]
    run = client.get(f"/api/queue-runs/{run_id}").json()
    assert run["status"] == "succeeded"
    assert run["summary"] == "Decided 3 claims."
    assert run["stop_reason"] == "cap"
    assert [t["status"] for t in run["todos"]] == ["done"] * 3
    assert [t["claim_id"] for t in run["todos"]] == ["CLM-1001", "CLM-1002", "CLM-1003"]
    assert run["todos"][0]["note"] == "CLM-1001: approve, $420.00, paid."
    assert run["model"] == "scripted"
    assert run["agent_tokens"] > 0
    assert run["tokens"] > run["agent_tokens"]
    values = list(states().values())
    assert values.count("waiting") == 32
    assert "in_progress" not in values
    names = [e["name"] for e in client.get(f"/api/queue-runs/{run_id}/events").json()]
    assert names[:3] == ["get_run_status", "get_run_status", "list_waiting_claims"]
    assert "finish_run" in names


def test_each_claim_gets_a_fresh_claim_agent(monkeypatch):
    claim_llm = ScriptedModel()
    run = run_with(monkeypatch, 2, QueueScript(), claim_llm)
    firsts = [prompt[1].text for prompt in claim_llm.prompts if len(prompt) == 2]
    assert firsts == ["Claim CLM-1001", "Claim CLM-1002"]
    for prompt in claim_llm.prompts:
        assert len(set(re_claims(prompt))) == 1
    for attempt in run["attempts"]:
        events = client.get(f"/api/runs/{attempt['run_id']}/events").json()
        calls = [
            e for e in events if e["name"] == "get_claim" and e["kind"] == "tool_call"
        ]
        assert calls[0]["detail"]["claim_id"] == attempt["claim_id"]


def re_claims(prompt):
    return [m.text.split()[-1] for m in prompt[1:2]]


def test_the_queue_agent_cannot_decide_or_pay():
    names = {t.name for t in queue.tools("x", None, lambda *_: None, 120)}
    assert names == {
        "get_run_status",
        "list_waiting_claims",
        "write_todos",
        "work_claim",
        "finish_run",
    }
    assert not names & {"record_decision", "pay_claim", "calculate_payout"}
    run_id = client.post("/api/runs", json={"cap": 1}).json()["run_id"]
    body = {
        "run_id": run_id,
        "decision": "refer",
        "payout": 0,
        "reason": "Reason.",
        "sections": ["wording-5"],
        "model": "stub",
    }
    assert client.post("/api/claims/CLM-1001/decision", json=body).status_code == 409


def test_a_claim_that_breaks_does_not_stop_the_run(monkeypatch):
    run = run_with(monkeypatch, 3, QueueScript(), FaultyModel(fail_on="CLM-1002"))
    assert run["status"] == "succeeded"
    todos = {t["claim_id"]: t for t in run["todos"]}
    assert todos["CLM-1001"]["status"] == "done"
    assert todos["CLM-1003"]["status"] == "done"
    assert todos["CLM-1002"]["status"] == "left_for_handler"
    tries = [a for a in run["attempts"] if a["claim_id"] == "CLM-1002"]
    assert [a["attempt"] for a in tries] == [1, 2]
    claim = client.get("/api/claims/CLM-1002").json()
    assert claim["state"] == "waiting"
    assert claim["left_for_handler"] is True
    assert states()["CLM-1003"] in {"decided", "waiting_for_signoff"}


def test_finishing_early_is_refused(monkeypatch):
    run = run_with(monkeypatch, 2, QueueScript(finish_early=True), ScriptedModel())
    assert run["status"] == "succeeded"
    assert [t["status"] for t in run["todos"]] == ["done", "done"]
    events = client.get(f"/api/queue-runs/{run['run_id']}/events").json()
    refused = [
        e for e in events if e["name"] == "finish_run" and e["kind"] == "tool_result"
    ]
    assert "not decided yet" in refused[0]["detail"]["result"]


def test_a_provider_that_stays_down_pauses_the_run(monkeypatch):
    request = httpx2.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    down = openai.InternalServerError(
        "Bad gateway.", response=httpx2.Response(502, request=request), body=None
    )
    run = run_with(monkeypatch, 2, FaultyModel(always=down), ScriptedModel())
    assert run["status"] == "paused"
    assert run["stop_reason"] == "provider_errors"
    assert "in_progress" not in states().values()


def test_claim_agents_that_hit_the_provider_pause_the_run(monkeypatch):
    request = httpx2.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    down = openai.APITimeoutError(request=request)
    run = run_with(monkeypatch, 5, QueueScript(), FaultyModel(always=down))
    assert run["status"] == "paused"
    assert len(run["attempts"]) == 3
    assert {a["failure"] for a in run["attempts"]} == {"provider"}
    assert "in_progress" not in states().values()


def test_a_named_claim_run_still_works(monkeypatch):
    monkeypatch.setenv("AGENT_STUB", "1")
    run_id = client.post("/api/claims/CLM-1001/runs").json()["run_id"]
    assert client.get(f"/api/runs/{run_id}").json()["status"] == "succeeded"
