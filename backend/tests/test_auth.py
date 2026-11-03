"""Sign-in, sessions, CSRF, roles and the security event log."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from backend import auth, clock, db, runs
from backend.main import app
from backend.tests import sessions

DANA = "dana.whitfield@undercover.example"
WRONG = "not-the-password"  # noqa: S105 - a wrong password, on purpose


@pytest.fixture(autouse=True)
def plain_http(monkeypatch):
    """Let the test client, which speaks http, keep the session cookie."""
    monkeypatch.setenv("COOKIE_SECURE", "0")
    monkeypatch.setattr(runs, "spawn", lambda work: None)


def login(email=DANA, password=sessions.PASSWORD, browser=None):
    browser = browser or TestClient(app)
    response = browser.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    return browser, response


def events(kind):
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT tenant_id, actor, target, outcome FROM security_events"
            " WHERE kind = ? ORDER BY id",
            (kind,),
        ).fetchall()
    return [tuple(r) for r in rows]


def test_sign_in_starts_a_cookie_session():
    browser, response = login()
    assert response.status_code == 200
    me = response.json()
    assert me["user_id"] == "USR-01"
    assert me["handler_id"] == "HND-01"
    assert me["tenant_id"] == "T-UNDERCOVER"
    assert me["tenant_name"] == "UnderCover Travel Insurance"
    assert me["roles"] == ["claims_handler", "senior_handler"]
    assert me["can_sign_off"] is True
    cookies = response.headers.get_list("set-cookie")
    session = next(c for c in cookies if c.startswith("cc_session="))
    assert "HttpOnly" in session
    assert "SameSite=strict" in session
    assert browser.cookies["cc_csrf"] == me["csrf_token"]
    assert browser.get("/api/auth/me").json()["name"] == "Dana Whitfield"
    assert len(browser.get("/api/claims").json()) == 35
    assert events("login") == [("T-UNDERCOVER", "USR-01", DANA, "ok")]


def test_cookies_are_secure_by_default(monkeypatch):
    monkeypatch.delenv("COOKIE_SECURE")
    _, response = login()
    for cookie in response.headers.get_list("set-cookie"):
        assert "Secure" in cookie


def test_email_case_does_not_matter():
    _, response = login(DANA.upper())
    assert response.status_code == 200


def test_sessions_are_stored_only_as_hashes():
    browser, response = login()
    token = browser.cookies["cc_session"]
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM sessions WHERE user_id = 'USR-01'"
            " AND created_at < '2100' ORDER BY created_at DESC"
        ).fetchone()
        user = conn.execute(
            "SELECT password_hash FROM users WHERE user_id = 'USR-01'"
        ).fetchone()
    assert row["token_hash"] == auth.digest(token)
    assert token not in str(dict(row))
    assert response.json()["csrf_token"] not in str(dict(row))
    assert user["password_hash"].startswith("scrypt$")
    assert sessions.PASSWORD not in user["password_hash"]


def test_a_cookie_write_needs_the_csrf_token():
    browser, response = login()
    csrf = response.json()["csrf_token"]
    refused = browser.post("/api/claims/CLM-1001/runs")
    assert refused.status_code == 403
    assert refused.json()["detail"] == "The request is missing its CSRF token."
    wrong = browser.post("/api/claims/CLM-1001/runs", headers={"X-CSRF-Token": "x"})
    assert wrong.status_code == 403
    ok = browser.post("/api/claims/CLM-1001/runs", headers={"X-CSRF-Token": csrf})
    assert ok.status_code == 200
    assert [e[3] for e in events("csrf")] == ["denied", "denied"]


@pytest.mark.parametrize(
    ("email", "password"),
    [(DANA, WRONG), ("nobody@undercover.example", sessions.PASSWORD)],
)
def test_a_wrong_sign_in_says_only_that_it_is_wrong(email, password):
    _, response = login(email, password)
    assert response.status_code == 401
    assert response.json()["detail"] == "The email or password is wrong."
    assert "set-cookie" not in response.headers
    assert events("login")[-1][3] == "denied"


def test_repeated_failures_are_throttled():
    for _ in range(auth.LOGIN_FAILURES):
        assert login(password=WRONG)[1].status_code == 401
    response = login()[1]
    assert response.status_code == 429


def test_a_disabled_user_cannot_sign_in_or_keep_a_session():
    with db.connect() as conn:
        conn.execute("UPDATE users SET status = 'disabled' WHERE user_id = 'USR-01'")
    assert login()[1].status_code == 401
    assert sessions.client().get("/api/claims").status_code == 401


def test_sign_out_ends_the_session():
    browser, response = login()
    csrf = {"X-CSRF-Token": response.json()["csrf_token"]}
    assert browser.post("/api/auth/logout", headers=csrf).status_code == 200
    browser.cookies.set("cc_session", "")
    _, again = login()
    stolen = again.headers.get_list("set-cookie")[0].split(";")[0].split("=", 1)[1]
    other = TestClient(app, headers=sessions.bearer(stolen))
    assert other.post("/api/auth/logout").status_code == 200
    assert other.get("/api/claims").status_code == 401
    assert [e[3] for e in events("logout")] == ["ok", "ok"]


def test_an_idle_session_ends(monkeypatch):
    monkeypatch.setenv("SESSION_IDLE_MINUTES", "30")
    browser, _ = login()
    start = clock.now()
    monkeypatch.setattr(clock, "now", lambda: start + timedelta(minutes=29))
    assert browser.get("/api/auth/me").status_code == 200
    monkeypatch.setattr(clock, "now", lambda: start + timedelta(minutes=58))
    assert browser.get("/api/auth/me").status_code == 200
    monkeypatch.setattr(clock, "now", lambda: start + timedelta(minutes=89))
    assert browser.get("/api/auth/me").status_code == 401


def test_a_session_ends_after_its_hours_however_busy(monkeypatch):
    browser, _ = login()
    start = clock.now()
    monkeypatch.setattr(clock, "now", lambda: start + timedelta(hours=11))
    assert browser.get("/api/auth/me").status_code == 200
    monkeypatch.setattr(clock, "now", lambda: start + timedelta(hours=13))
    assert browser.get("/api/auth/me").status_code == 401


def test_a_made_up_token_is_refused_and_logged():
    stranger = TestClient(app, headers=sessions.bearer("cs_made_up"))
    assert stranger.get("/api/claims").status_code == 401
    forged = TestClient(app, headers=sessions.bearer("ct_made_up"))
    assert forged.get("/api/claims").status_code == 401
    assert events("authentication") == [
        ("", "", "list_claims", "denied"),
        ("", "", "list_claims", "denied"),
    ]


@pytest.mark.parametrize(
    ("user_id", "can"),
    [
        ("USR-01", {"start_run", "sign_off_claim"}),
        ("USR-04", {"start_run"}),
        ("USR-05", set()),
        ("USR-ADMIN", {"list_security_events"}),
        ("USR-AUDIT", {"list_security_events"}),
    ],
)
def test_what_each_role_may_do(user_id, can):
    person = sessions.client(user_id)
    assert person.get("/api/claims").status_code == 200
    assert person.get("/api/runs/x/events").status_code == 404
    started = person.post("/api/claims/CLM-1001/runs").status_code
    assert (started == 200) == ("start_run" in can)
    log = person.get("/api/security-events").status_code
    assert (log == 200) == ("list_security_events" in can)
    me = person.get("/api/auth/me").json()
    assert me["can_sign_off"] == ("sign_off_claim" in can)


def test_admins_and_auditors_cannot_sign_off_pay_or_run():
    for user_id in (sessions.ADMIN, sessions.AUDITOR):
        person = sessions.client(user_id)
        assert person.post("/api/claims/CLM-1001/sign-off").status_code == 403
        assert person.post("/api/runs", json={"cap": 1}).status_code == 403
        body = {"run_id": "x", "amount": 1}
        assert person.post("/api/claims/CLM-1001/pay", json=body).status_code == 403


def test_people_cannot_act_as_the_agent():
    run_id = runs.begin("CLM-1001", sessions.TENANT)
    client = sessions.client()
    body = {"run_id": run_id, "amount": 1}
    assert client.post("/api/claims/CLM-1001/pay", json=body).status_code == 403
    assert client.post(f"/api/runs/{run_id}/finish", json={}).status_code == 403


def test_the_security_log_is_per_tenant_and_newest_first():
    sessions.client(sessions.TRAINEE).post("/api/claims/CLM-1001/sign-off")
    log = sessions.client(sessions.AUDITOR).get("/api/security-events").json()
    assert log[0]["kind"] == "authorization"
    assert log[0]["actor"] == "USR-04"
    assert log[0]["target"] == "sign_off_claim /api/claims/CLM-1001/sign-off"
    assert log[0]["outcome"] == "denied"
    assert all(e["tenant_id"] == "T-UNDERCOVER" for e in log)
    for event in log:
        assert sessions.PASSWORD not in str(event)


def test_passwords_round_trip_and_bad_hashes_fail():
    stored = auth.hash_password("pass phrase")
    assert auth.verify_password("pass phrase", stored)
    assert not auth.verify_password("other", stored)
    assert not auth.verify_password("pass phrase", "")
    assert not auth.verify_password("pass phrase", "md5$1$2$3$4$5")


def test_without_a_demo_password_each_user_gets_a_random_one(
    tmp_path, monkeypatch, capsys
):
    from backend import seed  # noqa: PLC0415 - used only here

    monkeypatch.delenv("DEMO_PASSWORD")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "random.db"))
    seed.seed()
    printed = [
        line.split()[-1]
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("Demo sign-in")
    ]
    assert len(printed) == 11
    assert len(set(printed)) == 11
    _, response = login(password=printed[0])
    assert response.status_code == 200
