"""A sign-off picks the claim back up, through the backend or the agent's service."""

import time
from contextlib import nullcontext

import pytest
from fastapi.testclient import TestClient

from agent import main, service
from agent.stub import ScriptedModel
from backend import db, runs, signoff
from backend.tests import sessions

KEY = "a-test-agent-service-key"
client = sessions.client()


@pytest.fixture(autouse=True)
def local(monkeypatch):
    monkeypatch.setattr(main, "backend", lambda: nullcontext(client))
    monkeypatch.setattr(runs, "spawn", lambda work: work())
    monkeypatch.setattr(signoff, "wake_agent", lambda: None)
    monkeypatch.setenv("AGENT_STUB", "1")
    monkeypatch.setenv("AGENT_SERVICE_KEY", KEY)


def held():
    """Run the scripted agent on CLM-1011, which waits for a sign-off, and sign off."""
    run_id = client.post("/api/claims/CLM-1011/runs").json()["run_id"]
    assert client.get(f"/api/runs/{run_id}").json()["status"] == "paused"
    signed = client.post("/api/claims/CLM-1011/sign-off").json()
    assert signed["state"] == "in_progress"
    return run_id, signed


def paid_once(run_id, signed):
    run = client.get(f"/api/runs/{run_id}").json()
    claim = client.get("/api/claims/CLM-1011").json()
    assert (run["status"], run["attempt"]) == ("succeeded", 1)
    assert (claim["state"], claim["paid"]) == ("decided", 1500.0)
    [payment] = claim["payments"]
    assert payment["signed_off_by"] == signed["signed_off_by"] == "HND-01"
    assert payment["signed_off_at"] == signed["signed_off_at"]
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM payments").fetchone()[0] == 1


def test_the_backend_carries_a_signed_off_claim_on_and_pays_it_once():
    run_id, signed = held()
    assert runs.carry_on(sessions.TENANT) == [run_id]
    assert runs.carry_on(sessions.TENANT) == []
    paid_once(run_id, signed)


def test_the_agents_service_carries_it_on_and_reports_each_step():
    run_id, signed = held()
    assert service.carry_on_all() == [run_id]
    assert service.carry_on_all() == []
    paid_once(run_id, signed)
    events = client.get(f"/api/runs/{run_id}/events").json()
    assert events[-1]["name"] == "pay_claim"
    assert events[-1]["kind"] == "tool_result"


def test_a_claim_signed_off_while_the_service_was_away_is_paid_when_it_starts():
    run_id, signed = held()
    with TestClient(service.app):
        for _ in range(100):
            if client.get(f"/api/runs/{run_id}").json()["status"] == "succeeded":
                break
            time.sleep(0.05)
    paid_once(run_id, signed)


def test_a_payment_that_fails_after_sign_off_stays_due(monkeypatch):
    run_id, signed = held()
    real = main.pay
    failures = [RuntimeError("The bank was down.")]

    def flaky(claim_id, amount):
        if failures:
            raise failures.pop()
        return real(claim_id, amount)

    monkeypatch.setattr(main, "pay", flaky)
    service.carry_on_all()
    run = client.get(f"/api/runs/{run_id}").json()
    claim = client.get("/api/claims/CLM-1011").json()
    assert (run["status"], run["error"]) == ("paused", "The bank was down.")
    assert (claim["state"], claim["failed_attempts"], claim["paid"]) == (
        "in_progress",
        0,
        0,
    )
    service.carry_on_all()
    paid_once(run_id, signed)


def test_the_service_answers_only_the_backend(monkeypatch):
    woken = []
    monkeypatch.setattr(service.WORKER, "wake", lambda: woken.append(1))
    agent = TestClient(service.app)
    assert agent.get("/health").json() == {"status": "ok"}
    wrong = agent.post("/resume", headers={"Authorization": "Bearer nope"})
    assert wrong.status_code == 401
    right = agent.post("/resume", headers={"Authorization": f"Bearer {KEY}"})
    assert right.status_code == 202
    assert woken == [1]


def test_only_the_service_key_takes_due_runs():
    held()
    assert client.post("/api/agent/resumable").status_code == 403
    nobody = sessions.anyone()
    stranger = nobody.post(
        "/api/agent/resumable", headers={"Authorization": "Bearer nope"}
    )
    assert stranger.status_code == 401
    taken = nobody.post(
        "/api/agent/resumable", headers={"Authorization": f"Bearer {KEY}"}
    ).json()
    assert [r["claim_id"] for r in taken] == ["CLM-1011"]
    assert taken[0]["signoff"]["handler_id"] == "HND-01"
    assert taken[0]["token"].startswith("ct_")


def test_a_claim_token_cannot_take_due_runs_or_end_another_run():
    run_id, _ = held()
    other = runs.begin("CLM-1001", sessions.TENANT)
    with db.connect() as conn:
        token = runs.claim_token(conn, other)
    headers = {"Authorization": f"Bearer {token}"}
    nobody = sessions.anyone()
    assert nobody.post("/api/agent/resumable", headers=headers).status_code == 403
    ended = nobody.post(
        f"/api/runs/{run_id}/end", json={"error": "", "failure": ""}, headers=headers
    )
    assert ended.status_code == 403


def test_send_back_ends_the_run_that_waited():
    run_id = client.post("/api/claims/CLM-1011/runs").json()["run_id"]
    sent = client.post(
        "/api/claims/CLM-1011/send-back", json={"reason": "Check the receipts."}
    )
    assert sent.status_code == 200
    assert client.get(f"/api/runs/{run_id}").json()["status"] == "succeeded"


def test_the_scripted_model_is_used_by_the_service_only_with_agent_stub(
    monkeypatch,
):
    monkeypatch.setattr(main, "resume", lambda *args: models.append(args[3]))
    monkeypatch.setattr(main, "call", lambda *args: {})
    models = []
    run = {"run_id": "r", "claim_id": "c", "token": "t", "signoff": None, "seconds": 1}
    service.carry_on(run)
    monkeypatch.delenv("AGENT_STUB")
    service.carry_on(run)
    assert isinstance(models[0], ScriptedModel)
    assert models[1] is None
