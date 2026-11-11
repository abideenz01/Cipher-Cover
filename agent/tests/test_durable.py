"""The claim agent carries on where it stopped, and nothing happens twice."""

from contextlib import nullcontext

import pytest

from agent import checkpoints, main
from agent.stub import ScriptedModel
from backend import db, queue_runs, runs
from backend.tests import sessions

client = sessions.client()


class Stopped(BaseException):
    """A stop from outside, such as Ctrl-C or a killed process."""


class StopsAt(ScriptedModel):
    """The scripted model, stopped at one of its calls."""

    at: int = 3

    def _generate(self, messages, *args, **kwargs):
        if len(self.prompts) + 1 == self.at:
            self.prompts.append(messages)
            raise Stopped
        return super()._generate(messages, *args, **kwargs)


@pytest.fixture(autouse=True)
def local_backend(monkeypatch):
    monkeypatch.setattr(main, "backend", lambda: nullcontext(client))
    monkeypatch.setattr(runs, "spawn", lambda work: work())
    monkeypatch.setenv("AGENT_STUB", "1")


def start_stopped(claim_id, llm):
    """Start a claim run that is stopped partway, as a killed process would be."""
    run_id = runs.begin(claim_id, sessions.TENANT)
    with db.connect() as conn:
        token = runs.claim_token(conn, run_id)
    with pytest.raises(Stopped), main.acting(token):
        main.run(claim_id, run_id, llm, lambda step: runs.record(run_id, step))
    return run_id


def restart(monkeypatch):
    """Restart the backend with durable progress."""
    monkeypatch.setattr(checkpoints, "durable", lambda: True)
    queue_runs.recover()


def run_row(run_id):
    return client.get(f"/api/runs/{run_id}").json()


def calls(run_id):
    events = client.get(f"/api/runs/{run_id}/events").json()
    return [e["name"] for e in events if e["kind"] == "tool_call"]


def counts(claim_id):
    with db.connect() as conn:
        return [
            conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE claim_id = ?",  # noqa: S608 - fixed names
                (claim_id,),
            ).fetchone()[0]
            for table in ("decisions", "payments")
        ]


def test_a_stopped_claim_carries_on_from_its_last_step(monkeypatch):
    run_id = start_stopped("CLM-1001", StopsAt(at=4))
    assert calls(run_id) == ["get_claim", "get_policy", "get_customer_history"]
    restart(monkeypatch)
    assert run_row(run_id)["status"] == "interrupted"
    claim = client.get("/api/claims/CLM-1001").json()
    assert claim["state"] == "in_progress"
    assert claim["failed_attempts"] == 0

    assert runs.resume_interrupted(sessions.TENANT) == [run_id]
    run = run_row(run_id)
    assert run["status"] == "succeeded"
    assert run["attempt"] == 1
    assert calls(run_id) == [
        "get_claim",
        "get_policy",
        "get_customer_history",
        "read_section",
        "calculate_payout",
        "record_decision",
    ]
    claim = client.get("/api/claims/CLM-1001").json()
    assert claim["state"] == "decided"
    assert claim["failed_attempts"] == 0
    assert claim["paid"] == 420.0
    assert counts("CLM-1001") == [1, 1]


def test_a_claim_stopped_before_its_first_step_starts_on_the_same_thread(
    monkeypatch,
):
    run_id = start_stopped("CLM-1001", StopsAt(at=1))
    restart(monkeypatch)
    runs.resume_interrupted(sessions.TENANT)
    assert run_row(run_id)["status"] == "succeeded"
    assert counts("CLM-1001") == [1, 1]


def test_a_stop_while_paying_pays_once(monkeypatch):
    real = main.pay
    stops = [Stopped()]

    def pay_then_stop(claim_id, amount):
        paid = real(claim_id, amount)
        if stops:
            raise stops.pop()
        return paid

    monkeypatch.setattr(main, "pay", pay_then_stop)
    run_id = start_stopped("CLM-1001", ScriptedModel())
    assert counts("CLM-1001") == [1, 1]
    restart(monkeypatch)
    runs.resume_interrupted(sessions.TENANT)
    assert run_row(run_id)["status"] == "succeeded"
    assert counts("CLM-1001") == [1, 1]


def test_a_stop_after_the_decision_records_it_once(monkeypatch):
    real = main.call
    stops = [Stopped()]

    def decide_then_stop(method, path, body=None, params=None):
        result = real(method, path, body, params)
        if path.endswith("/decision") and stops:
            raise stops.pop()
        return result

    monkeypatch.setattr(main, "call", decide_then_stop)
    run_id = start_stopped("CLM-1001", ScriptedModel())
    assert counts("CLM-1001") == [1, 0]
    restart(monkeypatch)
    runs.resume_interrupted(sessions.TENANT)
    assert run_row(run_id)["status"] == "succeeded"
    assert counts("CLM-1001") == [1, 1]


def test_a_claim_that_fails_with_an_error_starts_afresh(monkeypatch):
    execute = runs.runner.execute

    def broken(claim_id, run_id, on_step, token):
        raise RuntimeError("The claim agent broke.")

    monkeypatch.setattr(runs.runner, "execute", broken)
    first = client.post("/api/claims/CLM-1001/runs").json()["run_id"]
    assert run_row(first)["status"] == "failed"
    claim = client.get("/api/claims/CLM-1001").json()
    assert claim["state"] == "waiting"
    assert claim["failed_attempts"] == 1
    monkeypatch.setattr(runs.runner, "execute", execute)
    second = client.post("/api/claims/CLM-1001/runs").json()["run_id"]
    assert second != first
    assert run_row(second)["attempt"] == 2
    assert calls(second)[0] == "get_claim"
    assert counts("CLM-1001") == [1, 1]


def test_without_durable_progress_a_restart_frees_the_claim():
    run_id = start_stopped("CLM-1001", StopsAt(at=3))
    queue_runs.recover()
    assert run_row(run_id)["status"] == "failed"
    claim = client.get("/api/claims/CLM-1001").json()
    assert claim["state"] == "waiting"
    assert claim["failed_attempts"] == 1


def test_the_next_queue_run_finishes_what_a_stopped_one_left(monkeypatch):
    monkeypatch.setattr(runs, "spawn", lambda work: None)
    stopped = client.post("/api/runs", json={"cap": 1}).json()["run_id"]
    monkeypatch.setattr(runs, "spawn", lambda work: work())
    run_id = start_stopped("CLM-1002", StopsAt(at=3))
    restart(monkeypatch)
    old = client.get(f"/api/queue-runs/{stopped}").json()
    assert (old["status"], old["stop_reason"]) == ("stopped", "restart")
    nxt = client.post("/api/runs", json={"cap": 1}).json()["run_id"]
    assert run_row(run_id)["status"] == "succeeded"
    assert client.get("/api/claims/CLM-1002").json()["state"] == "decided"
    assert client.get(f"/api/queue-runs/{nxt}").json()["status"] == "succeeded"


def test_resuming_twice_does_nothing_the_second_time(monkeypatch):
    run_id = start_stopped("CLM-1001", StopsAt(at=3))
    restart(monkeypatch)
    runs.resume(run_id, None)
    runs.resume(run_id, None)
    assert counts("CLM-1001") == [1, 1]
