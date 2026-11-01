from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.tests.test_decisions import calculate, decide
from backend.tests.test_read import PERSONAL, keys
from backend.voice import routes
from backend.voice.briefs import speak_claim_id, speak_money
from backend.voice.normalize import claim_id

client = TestClient(app)


@pytest.fixture(autouse=True)
def voice_on(monkeypatch):
    monkeypatch.setenv("VOICE_ENABLED", "1")
    routes.TURNS.clear()


@pytest.fixture
def waiting():
    calculate("CLM-1011")
    decide("CLM-1011", "approve", 1500.0)


def test_config(monkeypatch):
    assert client.get("/api/voice/config").json() == {
        "enabled": True,
        "provider": "browser",
    }
    monkeypatch.delenv("VOICE_ENABLED")
    assert client.get("/api/voice/config").json()["enabled"] is False
    for path in [
        "/api/voice/instructions",
        "/api/claims/search?text=1011",
        "/api/claims/CLM-1002/brief",
        "/api/analytics/brief",
    ]:
        assert client.get(path).status_code == 404, path


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("ten eleven", "CLM-1011"),
        ("claim ten oh two", "CLM-1002"),
        ("C L M one zero one three", "CLM-1013"),
        ("fourteen oh five", "CLM-1405"),
        ("open claim ten twenty four", "CLM-1024"),
        ("sign off CLM-1011", "CLM-1011"),
        ("the Becker claim", ""),
    ],
)
def test_normalize(text, expected):
    assert claim_id(text) == expected


@pytest.mark.parametrize(
    ("amount", "spoken"),
    [
        (1500.0, "one thousand five hundred dollars"),
        (420.0, "four hundred twenty dollars"),
        (61.0, "sixty-one dollars"),
        (1380.5, "one thousand three hundred eighty dollars and fifty cents"),
        (1.01, "one dollar and one cent"),
        (2_000_000.0, "two million dollars"),
    ],
)
def test_speak_money(amount, spoken):
    assert speak_money(amount) == spoken


def test_speak_claim_id():
    assert speak_claim_id("CLM-1011") == "claim one zero one one"


def test_claim_brief_has_no_free_text():
    brief = client.get("/api/claims/CLM-1002/brief").json()
    assert (
        brief["reply"] == "CLM-1002 is waiting. Tom B. claimed $1,150.00 for baggage."
    )
    assert "one thousand one hundred fifty dollars" in brief["speech"]
    assert not keys(brief) & (PERSONAL | {"story", "documents"})
    missing = client.get("/api/claims/CLM-9999/brief")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "There is no claim CLM-9999."


def test_search():
    assert [
        c["claim_id"] for c in client.get("/api/claims/search?text=Becker").json()
    ] == ["CLM-1002"]
    assert [
        c["claim_id"] for c in client.get("/api/claims/search?text=1011").json()
    ] == ["CLM-1011"]
    assert client.get("/api/claims/search?text=nobody").json() == []


def test_decision_and_run_briefs(waiting):
    brief = client.get("/api/claims/CLM-1011/decision-brief").json()
    assert brief["reply"] == (
        "CLM-1011 was approved for $1,500.00 under"
        " Section 5. Baggage and Personal Effects."
    )
    none = client.get("/api/claims/CLM-1001/decision-brief").json()
    assert none["reply"] == "CLM-1001 has no decision yet."
    run = client.get("/api/claims/CLM-1001/run-status").json()
    assert run["reply"] == "CLM-1001 has not been run yet."
    decide("CLM-1001", "refer", 0)
    referred = client.get("/api/claims/CLM-1001/decision-brief").json()
    assert referred["reply"] == (
        "CLM-1001 was referred under Section 5. Baggage and Personal Effects."
    )


def test_analytics_brief(waiting):
    brief = client.get("/api/analytics/brief").json()
    assert brief["counts"]["waiting_for_signoff"] == 1
    assert brief["counts"]["waiting"] == 34
    assert brief["paid"] == 0


def request(handler_id):
    return client.post(
        "/api/claims/CLM-1011/signoff-request", json={"handler_id": handler_id}
    )


def test_request_signoff_changes_nothing(waiting):
    response = request("HND-01")
    assert response.status_code == 200
    assert response.json()["ui_action"] == {
        "type": "focus_signoff",
        "claim_id": "CLM-1011",
    }
    claim = client.get("/api/claims/CLM-1011").json()
    assert claim["state"] == "waiting_for_signoff"
    assert claim["paid"] == 0
    assert request("HND-04").status_code == 403


def test_request_signoff_needs_a_waiting_claim():
    assert request("HND-01").status_code == 409


def test_signoffs_are_spoken(waiting):
    item = client.get("/api/signoffs").json()[0]
    assert (
        item["speech"] == "Claim one zero one one for one thousand five hundred dollars"
    )


def test_rate_limit(monkeypatch):
    monkeypatch.setattr(
        routes,
        "answer",
        lambda body: {
            "reply": "Hi.",
            "speech": "Hi.",
            "ui_action": {"type": "none", "claim_id": ""},
            "tools": [],
        },
    )
    body = {"session_id": "s1", "handler_id": "HND-01", "text": "hello"}
    for _ in range(20):
        assert client.post("/api/voice/turn", json=body).status_code == 200
    assert client.post("/api/voice/turn", json=body).status_code == 429
    assert len(client.get("/api/voice/sessions/s1").json()) == 20


def test_unbacked_highlight_is_dropped(monkeypatch):
    monkeypatch.setattr(
        routes,
        "answer",
        lambda body: {
            "reply": "Done.",
            "speech": "Done.",
            "ui_action": {"type": "focus_signoff", "claim_id": "CLM-1011"},
            "tools": [],
        },
    )
    body = {"session_id": "s2", "handler_id": "HND-01", "text": "sign off ten eleven"}
    result = client.post("/api/voice/turn", json=body).json()
    assert result["ui_action"] == {"type": "none", "claim_id": ""}


def test_timeout(monkeypatch):
    monkeypatch.setenv("VOICE_TURN_TIMEOUT_SECONDS", "0.1")
    monkeypatch.setattr(routes, "answer", lambda body: __import__("time").sleep(1))
    body = {"session_id": "s3", "handler_id": "HND-01", "text": "hello"}
    result = client.post("/api/voice/turn", json=body).json()
    assert result["status"] == "failed"
    assert result["reply"] == routes.FALLBACK
    assert client.get("/api/voice/sessions/s3").json()[0]["status"] == "failed"


def test_voice_never_reads_the_answer_key():
    for path in [
        Path("agent/voice.py"),
        Path("agent/voice_stub.py"),
        *Path("backend/voice").glob("*.py"),
    ]:
        assert "evals" not in path.read_text(encoding="utf-8"), path
