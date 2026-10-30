from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from backend import clock
from backend.main import app
from backend.tests.test_decisions import calculate, decide, pay

client = TestClient(app)


@pytest.fixture
def waiting():
    calculate("CLM-1011")
    decide("CLM-1011", "approve", 1500.0)


def sign_off(handler_id):
    return client.post("/api/claims/CLM-1011/sign-off", json={"handler_id": handler_id})


def send_back(reason):
    return client.post(
        "/api/claims/CLM-1011/send-back",
        json={"handler_id": "HND-01", "reason": reason},
    )


def test_listed_for_sign_off(waiting):
    signoffs = client.get("/api/signoffs").json()
    assert [(s["claim_id"], s["payout"]) for s in signoffs] == [("CLM-1011", 1500.0)]


@pytest.mark.parametrize("handler_id", ["HND-04", "HND-05"])
def test_handlers_who_cannot_sign_off(waiting, handler_id):
    assert sign_off(handler_id).status_code == 403
    claim = client.get("/api/claims/CLM-1011").json()
    assert claim["state"] == "waiting_for_signoff"
    assert claim["paid"] == 0


@pytest.mark.parametrize("handler_id", ["HND-01", "HND-02", "HND-03"])
def test_sign_off_pays(waiting, handler_id):
    assert sign_off(handler_id).status_code == 200
    claim = client.get("/api/claims/CLM-1011").json()
    assert claim["state"] == "decided"
    assert claim["paid"] == 1500.0
    assert client.get("/api/signoffs").json() == []
    response = pay("CLM-1011", 1500.0)
    assert response.status_code == 409
    assert response.json()["detail"] == "This claim is already paid."


def test_sign_off_needs_a_waiting_claim():
    assert sign_off("HND-01").status_code == 409
    assert send_back("Check the receipts.").status_code == 409


def test_unknown_handler(waiting):
    assert sign_off("HND-99").status_code == 404


def test_send_back(waiting):
    assert send_back("").status_code == 422
    assert send_back("Check the receipts.").status_code == 200
    claim = client.get("/api/claims/CLM-1011").json()
    assert claim["state"] == "waiting"
    assert claim["decisions"][-1]["decision"] == "approve"
    assert claim["sendbacks"][0]["reason"] == "Check the receipts."
    assert client.get("/api/signoffs").json() == []


def test_overdue(waiting, monkeypatch):
    start = clock.now()
    monkeypatch.setattr(clock, "now", lambda: start + timedelta(hours=23))
    assert client.get("/api/signoffs").json()[0]["overdue"] is False
    monkeypatch.setattr(clock, "now", lambda: start + timedelta(hours=25))
    assert client.get("/api/signoffs").json()[0]["overdue"] is True
