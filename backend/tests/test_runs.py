import pytest
from fastapi.testclient import TestClient

from agent import main
from backend import runner, runs
from backend.main import app
from backend.tests.test_decisions import decide

client = TestClient(app)


@pytest.fixture(autouse=True)
def inline(monkeypatch):
    monkeypatch.setenv("AGENT_STUB", "1")
    monkeypatch.setattr(main, "backend", lambda: TestClient(app))
    monkeypatch.setattr(runs, "spawn", lambda work: work())


def start(claim_id):
    return client.post(f"/api/claims/{claim_id}/runs")


def finished(claim_id):
    run_id = start(claim_id).json()["run_id"]
    return client.get(f"/api/runs/{run_id}").json(), client.get(
        f"/api/runs/{run_id}/events"
    ).json()


def test_run_decides_the_claim():
    run, events = finished("CLM-1001")
    assert run["status"] == "succeeded"
    assert client.get("/api/claims/CLM-1001").json()["state"] == "decided"
    assert len(events) >= 6
    assert [e["created_at"] for e in events] == sorted(e["created_at"] for e in events)
    calculation = next(e for e in events if e["name"] == "calculate_payout")
    assert calculation["detail"]["claim_id"] == "CLM-1001"


def test_run_over_the_limit_waits():
    run, events = finished("CLM-1011")
    assert run["status"] == "succeeded"
    assert client.get("/api/claims/CLM-1011").json()["state"] == "waiting_for_signoff"
    paid = [
        e for e in events if e["kind"] == "tool_result" and e["name"] == "pay_claim"
    ]
    assert "sign-off" in paid[0]["detail"]["result"]


def test_one_run_at_a_time(monkeypatch):
    monkeypatch.setattr(runs, "spawn", lambda work: None)
    assert start("CLM-1001").status_code == 200
    assert start("CLM-1001").status_code == 409


def test_a_failed_run_frees_the_claim(monkeypatch):
    def broken(claim_id, run_id, on_step):
        raise RuntimeError("The model is unavailable.")

    monkeypatch.setattr(runner, "execute", broken)
    run, _ = finished("CLM-1001")
    assert run["status"] == "failed"
    assert run["error"] == "The model is unavailable."
    assert client.get("/api/claims/CLM-1001").json()["state"] == "waiting"


def test_a_run_without_a_decision_fails(monkeypatch):
    monkeypatch.setattr(runner, "execute", lambda claim_id, run_id, on_step: None)
    run, _ = finished("CLM-1001")
    assert run["status"] == "failed"
    assert client.get("/api/claims/CLM-1001").json()["state"] == "waiting"


def test_queue_run_takes_one_claim_at_a_time(monkeypatch):
    claims = [c["claim_id"] for c in client.get("/api/claims").json()]
    for claim_id in claims[3:]:
        decide(claim_id, "refer", 0)
    busiest = []

    def counting(claim_id, run_id, on_step):
        states = [c["state"] for c in client.get("/api/claims").json()]
        busiest.append(states.count("in_progress"))
        decide(claim_id, "refer", 0)

    monkeypatch.setattr(runner, "execute", counting)
    assert client.post("/api/runs").json()["claim_ids"] == claims[:3]
    assert busiest == [1, 1, 1]
    assert {c["state"] for c in client.get("/api/claims").json()} == {"decided"}


def test_missing_run():
    assert client.get("/api/runs/nope").status_code == 404
