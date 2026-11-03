import threading

import pytest
from fastapi.testclient import TestClient

from backend import db, queue_runs, runner, runs
from backend.main import app
from backend.tests import sessions
from backend.tests.test_decisions import decide

client = sessions.client()


@pytest.fixture(autouse=True)
def held(monkeypatch):
    """Start no agent: each test drives the run itself, as a stand-in would."""
    monkeypatch.setattr(runs, "spawn", lambda work: None)


def start(cap=0):
    return client.post("/api/runs", json={"cap": cap})


def agent(run_id):
    """Return headers for the queue agent on a queue run."""
    return sessions.queue_agent(run_id)


def begin(run_id, claim_id):
    return client.post(
        f"/api/queue-runs/{run_id}/attempts",
        json={"claim_id": claim_id},
        headers=agent(run_id),
    )


def end(claim_run, error="", failure=""):
    with db.connect() as conn:
        queue_run_id = conn.execute(
            "SELECT queue_run_id FROM runs WHERE run_id = ?", (claim_run,)
        ).fetchone()["queue_run_id"]
    body = {"error": error, "failure": failure}
    return client.post(
        f"/api/runs/{claim_run}/finish", json=body, headers=agent(queue_run_id)
    ).json()


def work(run_id, claim_id, error="", failure=""):
    """Take a claim and end it: a refer, or the failure given."""
    claim_run = begin(run_id, claim_id).json()["run_id"]
    if not error:
        decide(claim_id, "refer", 0)
    return end(claim_run, error, failure)


def finish(run_id, summary="Done."):
    return client.post(
        f"/api/queue-runs/{run_id}/finish",
        json={"summary": summary},
        headers=agent(run_id),
    )


def write_todos(run_id, todos):
    return client.put(
        f"/api/queue-runs/{run_id}/todos", json={"todos": todos}, headers=agent(run_id)
    )


def queue_run(run_id):
    return client.get(f"/api/queue-runs/{run_id}").json()


def claim(claim_id):
    return client.get(f"/api/claims/{claim_id}").json()


def test_one_queue_run_at_a_time():
    first = start(1).json()["run_id"]
    response = start(1)
    assert response.status_code == 409
    assert first in response.json()["detail"]
    client.post(f"/api/queue-runs/{first}/stop")
    assert finish(first).json()["status"] == "stopped"
    assert start(1).status_code == 200


def test_the_cap():
    run_id = start(2).json()["run_id"]
    work(run_id, "CLM-1001", "Boom.", "error")
    work(run_id, "CLM-1002")
    response = begin(run_id, "CLM-1003")
    assert response.status_code == 409
    assert response.json()["detail"] == "The cap is reached."
    assert begin(run_id, "CLM-1001").json()["attempt"] == 2


def test_a_claim_that_fails_twice_is_left_for_a_handler():
    run_id = start().json()["run_id"]
    assert work(run_id, "CLM-1001", "Boom.", "error")["outcome"] == (
        "CLM-1001: failed (error), back in the queue."
    )
    assert claim("CLM-1001")["state"] == "waiting"
    assert claim("CLM-1001")["failed_attempts"] == 1
    second = work(run_id, "CLM-1001", "Boom again.", "error")
    assert second["outcome"].startswith("CLM-1001: failed twice, left for a handler.")
    response = begin(run_id, "CLM-1001")
    assert response.status_code == 409
    assert "left for a handler" in response.json()["detail"]
    summary = next(
        c for c in client.get("/api/claims").json() if c["claim_id"] == "CLM-1001"
    )
    assert summary["left_for_handler"] is True
    assert summary["state"] == "waiting"


def test_the_outcome_lines():
    run_id = start().json()["run_id"]
    assert work(run_id, "CLM-1002")["outcome"] == "CLM-1002: refer, $0.00."
    claim_run = begin(run_id, "CLM-1003").json()["run_id"]
    assert end(claim_run)["outcome"].startswith("CLM-1003: failed (error)")


def test_one_lease_per_claim():
    run_id = start().json()["run_id"]
    assert begin(run_id, "CLM-1001").status_code == 200
    assert begin(run_id, "CLM-1001").status_code == 409
    codes = []
    threads = [
        threading.Thread(
            target=lambda: codes.append(begin(run_id, "CLM-1002").status_code)
        )
        for _ in range(4)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(codes) == [200, 409, 409, 409]


def test_the_token_budget(monkeypatch):
    monkeypatch.setenv("RUN_TOKEN_LIMIT", "1000")
    run_id = start().json()["run_id"]
    runs.record(run_id, {"kind": "usage", "name": "stub", "detail": {"tokens": 700}})
    work(run_id, "CLM-1001")
    claim_run = queue_run(run_id)["attempts"][0]["run_id"]
    with db.connect() as conn:
        conn.execute("UPDATE runs SET tokens = 500 WHERE run_id = ?", (claim_run,))
    assert queue_run(run_id)["tokens"] == 1200
    response = begin(run_id, "CLM-1002")
    assert response.status_code == 409
    assert response.json()["detail"] == "The token budget is spent."
    finished = finish(run_id).json()
    assert finished["status"] == "succeeded"
    assert finished["stop_reason"] == "token_limit"


def test_provider_failures_in_a_row_pause_the_run():
    run_id = start().json()["run_id"]
    work(run_id, "CLM-1001", "Bad gateway.", "provider")
    work(run_id, "CLM-1002", "Bad gateway.", "provider")
    work(run_id, "CLM-1003")
    work(run_id, "CLM-1004", "Bad gateway.", "provider")
    work(run_id, "CLM-1005", "Bad gateway.", "provider")
    assert queue_run(run_id)["status"] == "running"
    last = work(run_id, "CLM-1006", "Bad gateway.", "provider")
    assert last["outcome"].endswith("The run is paused after provider errors.")
    assert queue_run(run_id)["status"] == "paused"
    assert begin(run_id, "CLM-1007").json()["detail"] == (
        "The run is paused after provider errors."
    )
    finished = finish(run_id).json()
    assert finished["status"] == "paused"
    assert finished["stop_reason"] == "provider_errors"


def test_finishing_checks_for_missed_claims():
    run_id = start(1).json()["run_id"]
    response = finish(run_id)
    assert response.status_code == 409
    assert "CLM-1001" in response.json()["detail"]
    work(run_id, "CLM-1001", "Boom.", "error")
    response = finish(run_id)
    assert response.status_code == 409
    assert response.json()["detail"].endswith(": CLM-1001.")
    work(run_id, "CLM-1001")
    finished = finish(run_id, "One claim referred.").json()
    assert finished["status"] == "succeeded"
    assert finished["stop_reason"] == "cap"
    assert finished["summary"] == "One claim referred."
    assert finish(run_id).status_code == 409


def test_stop_finishes_the_claim_in_hand():
    run_id = start().json()["run_id"]
    todos = [
        {"claim_id": "CLM-1001", "status": "in_progress", "note": ""},
        {"claim_id": "CLM-1002", "status": "to_do", "note": ""},
        {"claim_id": "CLM-1003", "status": "done", "note": "refer"},
    ]
    write_todos(run_id, todos)
    claim_run = begin(run_id, "CLM-1001").json()["run_id"]
    assert client.post(f"/api/queue-runs/{run_id}/stop").json()["status"] == "stopping"
    decide("CLM-1001", "refer", 0)
    assert end(claim_run)["status"] == "succeeded"
    assert begin(run_id, "CLM-1002").json()["detail"] == "The run is stopping."
    finished = finish(run_id).json()
    assert finished["status"] == "stopped"
    assert [t["status"] for t in finished["todos"]] == [
        "not_started",
        "not_started",
        "done",
    ]
    assert claim("CLM-1002")["state"] == "waiting"
    assert client.post(f"/api/queue-runs/{run_id}/stop").status_code == 409
    assert write_todos(run_id, []).status_code == 409


def test_an_agent_that_raises_frees_its_claims(monkeypatch):
    def broken(run_id, on_step, token):
        begin(run_id, "CLM-1001")
        raise RuntimeError("The queue agent broke.")

    monkeypatch.setattr(runner, "execute_queue", broken)
    monkeypatch.setattr(runs, "spawn", lambda work: work())
    run = start().json()
    assert run["status"] == "failed"
    assert run["error"] == "The queue agent broke."
    assert claim("CLM-1001")["state"] == "waiting"
    assert claim("CLM-1001")["failed_attempts"] == 1


def test_an_agent_that_ends_without_a_summary_fails(monkeypatch):
    monkeypatch.setattr(runner, "execute_queue", lambda run_id, on_step, t: None)
    monkeypatch.setattr(runs, "spawn", lambda work: work())
    run = start().json()
    assert run["status"] == "failed"
    assert run["error"] == "The agent ended without a summary."


def test_a_stand_in_works_the_queue(monkeypatch):
    def stand_in(run_id, on_step, token):
        on_step(run_id, {"kind": "usage", "name": "stub", "detail": {"tokens": 50}})
        on_step(
            run_id, {"kind": "tool_call", "name": "list_waiting_claims", "detail": {}}
        )
        for claim_id in ("CLM-1001", "CLM-1002"):
            work(run_id, claim_id)
        finish(run_id, "Two claims referred.")

    monkeypatch.setattr(runner, "execute_queue", stand_in)
    monkeypatch.setattr(runs, "spawn", lambda work: work())
    run = start(2).json()
    assert run["status"] == "succeeded"
    assert run["claims_worked"] == 2
    assert run["agent_tokens"] == 50
    events = client.get(f"/api/queue-runs/{run['run_id']}/events").json()
    assert [e["name"] for e in events] == ["list_waiting_claims"]


def test_recovery_on_startup():
    run_id = start().json()["run_id"]
    claim_run = begin(run_id, "CLM-1001").json()["run_id"]
    with TestClient(app):
        pass
    assert begin(run_id, "CLM-1002").status_code == 409
    assert claim("CLM-1001")["state"] == "waiting"
    assert claim("CLM-1001")["failed_attempts"] == 1
    run = client.get(f"/api/runs/{claim_run}").json()
    assert run["status"] == "failed"
    assert run["error"] == "The backend restarted."
    assert queue_run(run_id)["status"] == "failed"


def test_a_queue_run_records_what_it_was_allowed(monkeypatch):
    monkeypatch.delenv("MODEL_NAME", raising=False)
    monkeypatch.delenv("AGENT_STUB", raising=False)
    run = start(5).json()
    assert run["cap"] == 5
    assert run["limits"] == {
        "claim_step_limit": 30,
        "claim_seconds": 120,
        "token_limit": 1_000_000,
        "provider_failures_to_pause": 3,
    }
    assert run["model"] == "deepseek/deepseek-v4.1-flash"
    assert run["reasoning_effort"] == "low"
    assert run["fingerprint"] == client.get("/api/instructions").json()["fingerprint"]
    assert run["todos"] == []
    assert run["summary"] == ""
    monkeypatch.setenv("AGENT_STUB", "1")
    assert queue_runs.model() == ("scripted", "")


def test_the_run_history():
    run_id = ""
    for _ in range(queue_runs.HISTORY + 1):
        run_id = start().json()["run_id"]
        client.post(f"/api/queue-runs/{run_id}/stop")
        finish(run_id)
    history = client.get("/api/queue-runs").json()
    assert len(history) == queue_runs.HISTORY
    assert history[0]["run_id"] == run_id
    assert client.get("/api/queue-runs/nope").status_code == 404
    assert client.get("/api/queue-runs/nope/events").status_code == 404
