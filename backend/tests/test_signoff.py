from datetime import timedelta

import pytest

from backend import clock, db
from backend.tests import sessions
from backend.tests.test_decisions import calculate, decide, pay

client = sessions.client()


@pytest.fixture
def waiting():
    calculate("CLM-1011")
    decide("CLM-1011", "approve", 1500.0)


def sign_off(user_id):
    return client.post(
        "/api/claims/CLM-1011/sign-off", headers=sessions.headers(user_id)
    )


def send_back(reason, user_id="USR-01"):
    return client.post(
        "/api/claims/CLM-1011/send-back",
        json={"reason": reason},
        headers=sessions.headers(user_id),
    )


def test_listed_for_sign_off(waiting):
    signoffs = client.get("/api/signoffs").json()
    assert [(s["claim_id"], s["payout"]) for s in signoffs] == [("CLM-1011", 1500.0)]


@pytest.mark.parametrize("user_id", ["USR-04", "USR-05", "USR-ADMIN", "USR-AUDIT"])
def test_people_who_cannot_sign_off(waiting, user_id):
    response = sign_off(user_id)
    assert response.status_code == 403
    assert response.json()["detail"] == "You are not allowed to sign off payouts."
    claim = client.get("/api/claims/CLM-1011").json()
    assert claim["state"] == "waiting_for_signoff"
    assert claim["paid"] == 0


@pytest.mark.parametrize("user_id", ["USR-01", "USR-02", "USR-03"])
def test_sign_off_pays(waiting, user_id):
    assert sign_off(user_id).status_code == 200
    claim = client.get("/api/claims/CLM-1011").json()
    assert claim["state"] == "decided"
    assert claim["paid"] == 1500.0
    assert client.get("/api/signoffs").json() == []
    response = pay("CLM-1011", 1500.0)
    assert response.status_code == 409
    assert response.json()["detail"] == "This claim is already paid."
    with db.connect() as conn:
        signed = conn.execute("SELECT handler_id FROM signoffs").fetchone()
    assert signed["handler_id"] == user_id.replace("USR", "HND")


def test_sign_off_needs_a_waiting_claim():
    assert sign_off("USR-01").status_code == 409
    assert send_back("Check the receipts.").status_code == 409


def test_the_body_cannot_name_another_handler(waiting):
    response = client.post(
        "/api/claims/CLM-1011/sign-off",
        json={"handler_id": "HND-01"},
        headers=sessions.headers("USR-04"),
    )
    assert response.status_code == 403
    assert client.get("/api/claims/CLM-1011").json()["paid"] == 0


def test_send_back_needs_a_handler(waiting):
    assert send_back("Check.", "USR-AUDIT").status_code == 403
    assert send_back("Check.", "USR-04").status_code == 200


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
