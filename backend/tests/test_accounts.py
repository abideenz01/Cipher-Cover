"""Tenant admins manage sign-ins and settings; tenants keep their own settings."""

from contextlib import nullcontext

import pytest
from fastapi.testclient import TestClient

from agent import main
from backend import db, runs
from backend.main import app
from backend.tests import sessions, tenants

admin = sessions.client(sessions.ADMIN)
acme_admin = sessions.client(tenants.ADMIN)
NEW = {
    "email": "Nia.Reyes@undercover.example",
    "name": "Nia Reyes",
    "handler_id": "",
    "roles": ["auditor"],
    "password": "a-long-enough-password",
}


def create(**changes):
    return admin.post("/api/users", json=NEW | changes)


def sign_in(email, password):
    return TestClient(app).post(
        "/api/auth/login", json={"email": email, "password": password}
    )


def test_an_admin_lists_only_their_own_tenants_sign_ins():
    users = admin.get("/api/users").json()
    assert len(users) == 7
    assert all(u["email"].endswith("@undercover.example") for u in users)
    assert "password_hash" not in users[0]
    acme = acme_admin.get("/api/users").json()
    assert {u["user_id"] for u in acme} == {"USR-A1", "USR-A2", "USR-A3", tenants.ADMIN}


def test_an_admin_adds_a_sign_in_that_works(monkeypatch):
    monkeypatch.setenv("COOKIE_SECURE", "0")
    created = create()
    assert created.status_code == 200
    user = created.json()
    assert user["email"] == "nia.reyes@undercover.example"
    assert user["roles"] == ["auditor"]
    assert user["status"] == "active"
    signed_in = sign_in("nia.reyes@undercover.example", NEW["password"])
    assert signed_in.status_code == 200
    assert signed_in.json()["roles"] == ["auditor"]
    with db.connect() as conn:
        event = conn.execute(
            "SELECT actor, target FROM security_events WHERE kind = 'user_created'"
        ).fetchone()
    assert tuple(event) == (sessions.ADMIN, user["user_id"])


@pytest.mark.parametrize(
    ("changes", "status"),
    [
        ({"email": "dana.whitfield@undercover.example"}, 409),
        ({"password": "short"}, 422),
        ({"roles": ["root"]}, 422),
        ({"roles": []}, 422),
        ({"email": "no-at-sign"}, 422),
        ({"handler_id": "HND-A1"}, 404),
    ],
)
def test_a_bad_sign_in_is_refused(changes, status):
    assert create(**changes).status_code == status


def test_an_admin_changes_roles_and_it_takes_effect():
    trainee = sessions.client(sessions.TRAINEE)
    assert trainee.get("/api/auth/me").json()["can_sign_off"] is False
    body = {"roles": ["claims_handler", "senior_handler"]}
    changed = admin.put(f"/api/users/{sessions.TRAINEE}/roles", json=body)
    assert changed.json()["roles"] == ["claims_handler", "senior_handler"]
    assert trainee.get("/api/auth/me").json()["can_sign_off"] is True


def test_an_admin_cannot_lock_themselves_out():
    own = f"/api/users/{sessions.ADMIN}"
    assert admin.put(f"{own}/roles", json={"roles": ["auditor"]}).status_code == 409
    assert admin.post(f"{own}/disable").status_code == 409


def test_disabling_ends_the_sessions_and_enabling_restores_sign_in():
    handler = sessions.client("USR-02")
    assert handler.get("/api/claims").status_code == 200
    assert admin.post("/api/users/USR-02/disable").json()["status"] == "disabled"
    assert handler.get("/api/claims").status_code == 401
    assert admin.post("/api/users/USR-02/enable").json()["status"] == "active"
    assert (
        sign_in("marcus.oyelaran@undercover.example", sessions.PASSWORD).status_code
        == 200
    )


def test_admins_reach_no_other_tenants_sign_ins():
    assert acme_admin.post("/api/users/USR-01/disable").status_code == 404
    body = {"roles": ["tenant_admin"]}
    assert acme_admin.put("/api/users/USR-01/roles", json=body).status_code == 404
    assert sessions.client().get("/api/claims").status_code == 200


@pytest.mark.parametrize("user_id", [sessions.SENIOR, sessions.AUDITOR, sessions.SIU])
def test_only_admins_manage(user_id):
    person = sessions.client(user_id)
    assert person.post("/api/users", json=NEW).status_code == 403
    assert person.post("/api/users/USR-02/disable").status_code == 403
    body = {"external_model_medical": True}
    assert person.put("/api/tenant/settings", json=body).status_code == 403


def test_auditors_can_read_the_sign_ins_and_settings():
    auditor = sessions.client(sessions.AUDITOR)
    assert auditor.get("/api/users").status_code == 200
    assert auditor.get("/api/tenant/settings").status_code == 200


def test_the_medical_setting_is_the_admins_to_change():
    settings = admin.get("/api/tenant/settings").json()
    assert settings == {
        "name": "UnderCover Travel Insurance",
        "timezone": "UTC",
        "external_model_medical": False,
        "payout_approval_limit": 1000.0,
        "sign_off_sla_hours": 24,
    }
    run_id = runs.begin("CLM-1003", sessions.TENANT)
    agent = sessions.claim_agent(run_id)
    seen = admin.get("/api/claims/CLM-1003", headers=agent).json()
    assert "withheld" in next(
        d["content"] for d in seen["documents"] if d["type"] == "medical_record"
    )
    body = {"external_model_medical": True}
    assert admin.put("/api/tenant/settings", json=body).json()["external_model_medical"]
    seen = admin.get("/api/claims/CLM-1003", headers=agent).json()
    assert "withheld" not in str(seen["documents"])
    assert (
        acme_admin.get("/api/tenant/settings").json()["external_model_medical"] is False
    )


def test_each_tenant_has_its_own_sign_off_limit(monkeypatch):
    monkeypatch.setenv("AGENT_STUB", "1")
    monkeypatch.setattr(main, "backend", lambda: nullcontext(sessions.anyone()))
    monkeypatch.setattr(runs, "spawn", lambda work: work())
    acme = sessions.client(tenants.USER)
    assert (
        acme_admin.get("/api/tenant/settings").json()["payout_approval_limit"] == 750.0
    )
    acme.post("/api/claims/CLM-5004/runs")
    claim = acme.get("/api/claims/CLM-5004").json()
    assert claim["payout"] == 820.0
    assert claim["state"] == "waiting_for_signoff"
    assert [s["claim_id"] for s in acme.get("/api/signoffs").json()] == ["CLM-5004"]
    acme.post("/api/claims/CLM-5002/runs")
    paid = acme.get("/api/claims/CLM-5002").json()
    assert (paid["state"], paid["paid"]) == ("decided", 630.0)


def test_the_sign_in_throttle_survives_a_restart(monkeypatch):
    monkeypatch.setenv("COOKIE_SECURE", "0")
    for _ in range(5):
        assert sign_in("dana.whitfield@undercover.example", "nope").status_code == 401
    with TestClient(app):
        pass
    assert (
        sign_in("dana.whitfield@undercover.example", sessions.PASSWORD).status_code
        == 429
    )
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM login_failures").fetchone()[0] == 10


def test_the_database_runs_in_wal_mode():
    with db.connect() as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
