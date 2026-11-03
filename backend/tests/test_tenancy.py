"""Tenant isolation, sign-in on every operation, and agent token binding.

Isolation here is enforced by the application on SQLite. It is the interim
measure for development and pilots, not the production guarantee: see
docs/ADR_POSTGRES.md.
"""

import re
from contextlib import nullcontext
from datetime import timedelta

import pytest

from agent import main
from backend import auth, clock, db, permissions, runs
from backend.main import app
from backend.tests import sessions, tenants
from backend.tests.test_decisions import calculate, decide

client = sessions.client()
acme = sessions.client(tenants.USER)
OPERATIONS = [
    (operation["operationId"], method.upper(), path)
    for path, methods in app.openapi()["paths"].items()
    for method, operation in methods.items()
]


@pytest.fixture(autouse=True)
def voice_on(monkeypatch):
    monkeypatch.setenv("VOICE_ENABLED", "1")


def filled(path):
    """Fill a path's parameters in."""
    return re.sub(r"\{[^}]+\}", "X", path.replace("{number}", "1"))


@pytest.mark.parametrize(("operation", "method", "path"), OPERATIONS)
def test_every_operation_but_three_needs_sign_in(operation, method, path):
    response = sessions.anyone().request(method, filled(path), json={})
    if operation in permissions.PUBLIC:
        assert response.status_code not in (401, 403), operation
    else:
        assert response.status_code == 401, operation
        assert response.json()["detail"] == "Sign in first."


def test_only_health_login_and_public_config_are_open():
    open_ops = {o for o, _, _ in OPERATIONS} & permissions.PUBLIC
    assert open_ops == {"health", "login", "get_public_config"}
    assert any(d.dependency is auth.guard for d in app.router.dependencies)


def test_every_operation_has_someone_who_may_call_it():
    callers = set(permissions.PUBLIC) | permissions.CLAIM_AGENT
    callers |= permissions.QUEUE_AGENT | permissions.VOICE_AGENT
    for allowed in permissions.ROLES.values():
        callers |= allowed
    operations = {o for o, _, _ in OPERATIONS}
    assert len(operations) == len(OPERATIONS)
    assert operations == callers


def test_public_config_holds_no_tenant_data_or_secrets():
    config = sessions.anyone().get("/api/public-config").json()
    assert config == {"product": "Cipher Cover", "sign_in": "password"}
    text = str(config).lower()
    for word in ("tenant", "undercover", "acme", "key", "secret", "token", "model"):
        assert word not in text


def test_voice_needs_sign_in_too():
    assert sessions.anyone().get("/api/voice/config").status_code == 401
    assert client.get("/api/voice/config").json()["enabled"] is True


def undercover_runs(monkeypatch):
    """Return a claim run, and a queue run, of T-UNDERCOVER."""
    monkeypatch.setattr(runs, "spawn", lambda work: None)
    claim_run = runs.begin("CLM-1002", sessions.TENANT)
    queue_run = client.post("/api/runs", json={"cap": 1}).json()["run_id"]
    return claim_run, queue_run


def test_another_tenants_records_are_not_there(monkeypatch):
    calculate("CLM-1011")
    decide("CLM-1011", "approve", 1500.0)
    claim_run, queue_run = undercover_runs(monkeypatch)
    missing = [
        ("GET", "/api/claims/CLM-1001"),
        ("GET", "/api/policies/POL-2001"),
        ("GET", "/api/customers/CUS-3001/history"),
        ("GET", f"/api/runs/{claim_run}"),
        ("GET", f"/api/runs/{claim_run}/events"),
        ("GET", f"/api/queue-runs/{queue_run}"),
        ("GET", f"/api/queue-runs/{queue_run}/events"),
        ("POST", f"/api/queue-runs/{queue_run}/stop"),
        ("POST", "/api/claims/CLM-1001/runs"),
        ("GET", "/api/claims/CLM-1001/brief"),
        ("GET", "/api/claims/CLM-1011/decision-brief"),
        ("GET", "/api/claims/CLM-1001/run-status"),
        ("POST", "/api/claims/CLM-1011/sign-off"),
        ("POST", "/api/claims/CLM-1011/signoff-request"),
    ]
    for method, path in missing:
        response = acme.request(method, path)
        assert response.status_code == 404, (method, path)
    response = acme.post("/api/claims/CLM-1011/send-back", json={"reason": "No."})
    assert response.status_code == 404
    assert client.get("/api/claims/CLM-1011").json()["state"] == "waiting_for_signoff"
    assert client.get(f"/api/queue-runs/{queue_run}").json()["status"] == "running"


def test_lists_show_only_the_tenants_own(monkeypatch):
    calculate("CLM-1011")
    decide("CLM-1011", "approve", 1500.0)
    undercover_runs(monkeypatch)
    listed = [c["claim_id"] for c in acme.get("/api/claims").json()]
    assert len(listed) == tenants.CLAIMS
    assert all(c.startswith("CLM-50") for c in listed)
    handlers = [h["handler_id"] for h in acme.get("/api/handlers").json()]
    assert handlers == ["HND-A1", "HND-A2", "HND-A3"]
    assert acme.get("/api/signoffs").json() == []
    assert acme.get("/api/queue-runs").json() == []
    assert acme.get("/api/claims/search?text=Becker").json() == []
    assert acme.get("/api/claims/search?text=1001").json() == []
    brief = acme.get("/api/analytics/brief").json()
    assert brief["counts"]["waiting"] == tenants.CLAIMS
    assert brief["counts"]["waiting_for_signoff"] == 0
    assert tenants.CLAIM not in {
        c["claim_id"] for c in client.get("/api/claims").json()
    }
    assert client.get(f"/api/claims/{tenants.CLAIM}").status_code == 404


def test_a_tenants_work_stays_in_that_tenant(monkeypatch):
    monkeypatch.setenv("AGENT_STUB", "1")
    monkeypatch.setattr(main, "backend", lambda: nullcontext(sessions.anyone()))
    monkeypatch.setattr(runs, "spawn", lambda work: work())
    run_id = acme.post(f"/api/claims/{tenants.CLAIM}/runs").json()["run_id"]
    assert acme.get(f"/api/runs/{run_id}").json()["status"] == "succeeded"
    claim = acme.get(f"/api/claims/{tenants.CLAIM}").json()
    assert claim["state"] == "decided"
    assert claim["paid"] == 280.0
    with db.connect() as conn:
        for table in ("calculations", "decisions", "payments", "runs"):
            found = conn.execute(
                f"SELECT DISTINCT tenant_id FROM {table}"  # noqa: S608 - fixed names
                " WHERE claim_id = ?",
                (tenants.CLAIM,),
            ).fetchall()
            assert [r["tenant_id"] for r in found] == [tenants.ACME], table
        for table in ("section_reads", "run_events", "service_tokens"):
            found = conn.execute(
                f"SELECT DISTINCT tenant_id FROM {table}"  # noqa: S608 - fixed names
                " WHERE run_id = ?",
                (run_id,),
            ).fetchall()
            assert [r["tenant_id"] for r in found] == [tenants.ACME], table
        assert not conn.execute(
            "SELECT 1 FROM payments WHERE tenant_id != ?", (tenants.ACME,)
        ).fetchone()


def claim_agent(claim_id="CLM-1001"):
    """Return a claim run on a claim and headers for its agent."""
    run_id = runs.begin(claim_id, sessions.TENANT)
    return run_id, sessions.claim_agent(run_id)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/claims/CLM-1002"),
        ("GET", "/api/policies/POL-2002"),
        ("GET", "/api/customers/CUS-3002/history"),
        ("GET", f"/api/claims/{tenants.CLAIM}"),
        ("GET", "/api/claims"),
        ("GET", "/api/signoffs"),
        ("POST", "/api/claims/CLM-1001/sign-off"),
        ("POST", "/api/claims/CLM-1001/runs"),
        ("POST", "/api/runs"),
    ],
)
def test_a_claim_agent_reaches_only_its_own_claim(method, path):
    _, agent = claim_agent()
    response = client.request(method, path, json={"cap": 1}, headers=agent)
    assert response.status_code == 403, path


def test_a_claim_agent_reads_its_own_claim_policy_and_customer():
    run_id, agent = claim_agent()
    for path in (
        "/api/claims/CLM-1001",
        "/api/policies/POL-2001",
        "/api/customers/CUS-3001/history",
        "/api/instructions",
    ):
        assert client.get(path, headers=agent).status_code == 200, path
    other = runs.begin("CLM-1002", sessions.TENANT)
    response = client.get(
        "/api/documents/wording/sections/5", params={"run_id": other}, headers=agent
    )
    assert response.status_code == 403
    with db.connect() as conn:
        denied = conn.execute(
            "SELECT actor, outcome FROM security_events WHERE kind = 'authorization'"
        ).fetchall()
    assert (f"claim:{run_id}", "denied") in [tuple(d) for d in denied]


def test_a_claim_agents_token_ends_with_its_run():
    run_id, agent = claim_agent()
    runs.finish(run_id, "CLM-1001", "Stopped.")
    assert client.get("/api/claims/CLM-1001", headers=agent).status_code == 401


def test_a_claim_agents_token_expires(monkeypatch):
    _, agent = claim_agent()
    later = clock.now() + timedelta(seconds=200)
    monkeypatch.setattr(clock, "now", lambda: later)
    assert client.get("/api/claims/CLM-1001", headers=agent).status_code == 401


def test_a_restart_revokes_every_agent_token():
    _, agent = claim_agent()
    with sessions.client():
        pass
    assert client.get("/api/claims/CLM-1001", headers=agent).status_code == 401


def test_a_queue_agent_reaches_only_its_own_queue_run(monkeypatch):
    monkeypatch.setattr(runs, "spawn", lambda work: None)
    first = client.post("/api/runs", json={"cap": 1}).json()["run_id"]
    client.post(f"/api/queue-runs/{first}/stop")
    client.post(
        f"/api/queue-runs/{first}/finish",
        json={"summary": "Stopped."},
        headers=sessions.queue_agent(first),
    )
    second = client.post("/api/runs", json={"cap": 1}).json()["run_id"]
    agent = sessions.queue_agent(second)
    assert client.get(f"/api/queue-runs/{first}", headers=agent).status_code == 403
    assert client.get(f"/api/queue-runs/{second}", headers=agent).status_code == 200
    loose = runs.begin("CLM-1005", sessions.TENANT)
    body = {"error": "", "failure": ""}
    response = client.post(f"/api/runs/{loose}/finish", json=body, headers=agent)
    assert response.status_code == 403
    assert client.get("/api/claims/CLM-1001", headers=agent).status_code == 403


def test_a_voice_agent_has_only_what_its_person_has():
    calculate("CLM-1011")
    decide("CLM-1011", "approve", 1500.0)
    trainee = sessions.bearer(sessions.voice_agent(sessions.TRAINEE))
    response = client.post("/api/claims/CLM-1011/signoff-request", headers=trainee)
    assert response.status_code == 403
    assert "not allowed to sign off" in response.json()["detail"]
    senior = sessions.bearer(sessions.voice_agent())
    response = client.post("/api/claims/CLM-1011/signoff-request", headers=senior)
    assert response.status_code == 200
    turn = {"session_id": "s1", "text": "hello"}
    assert client.post("/api/voice/turn", json=turn, headers=senior).status_code == 403
    assert client.get("/api/claims/CLM-1011", headers=senior).status_code == 403
    ada = sessions.bearer(sessions.voice_agent(tenants.USER))
    assert client.get("/api/claims/CLM-1001/brief", headers=ada).status_code == 404


def test_voice_sessions_are_private_to_their_handler(monkeypatch):
    from backend.voice import routes  # noqa: PLC0415 - used only here

    reply = {
        "reply": "Hi.",
        "speech": "Hi.",
        "ui_action": {"type": "none", "claim_id": ""},
        "tools": [],
    }
    monkeypatch.setattr(routes, "answer", lambda *_: dict(reply))
    client.post("/api/voice/turn", json={"session_id": "mine", "text": "hello"})
    assert len(client.get("/api/voice/sessions/mine").json()) == 1
    other = sessions.client("USR-02")
    assert other.get("/api/voice/sessions/mine").json() == []
    assert acme.get("/api/voice/sessions/mine").json() == []


def test_medical_documents_never_reach_an_agent_unless_the_tenant_allows_it():
    human = client.get("/api/claims/CLM-1003").json()
    medical = next(d for d in human["documents"] if d["type"] == "medical_record")
    assert not medical["content"].startswith("[medical document withheld")
    _, agent = claim_agent("CLM-1003")
    seen = client.get("/api/claims/CLM-1003", headers=agent).json()
    withheld = next(d for d in seen["documents"] if d["type"] == "medical_record")
    assert withheld["content"] == (
        f"[medical document withheld: {len(medical['content'])} characters]"
    )
    others = [d for d in seen["documents"] if d["type"] != "medical_record"]
    assert others == [d for d in human["documents"] if d["type"] != "medical_record"]
    with db.connect() as conn:
        conn.execute(
            "UPDATE tenants SET config = '{\"external_model_medical\": true}'"
            " WHERE tenant_id = ?",
            (sessions.TENANT,),
        )
    allowed = client.get("/api/claims/CLM-1003", headers=agent).json()
    assert allowed["documents"] == human["documents"]


def test_agents_see_short_customer_names():
    _, agent = claim_agent()
    assert client.get("/api/claims/CLM-1001").json()["customer_name"] == "Maya Patel"
    assert (
        client.get("/api/claims/CLM-1001", headers=agent).json()["customer_name"]
        == "Maya P."
    )
    history = client.get("/api/customers/CUS-3001/history", headers=agent).json()
    assert history["name"] == "Maya P."
