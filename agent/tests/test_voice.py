from contextlib import nullcontext

import pytest
from fastapi.testclient import TestClient

from agent import main, voice
from agent.voice_stub import ScriptedVoiceModel
from backend.main import app
from backend.tests.test_decisions import calculate, decide
from backend.voice import routes

client = TestClient(app)


@pytest.fixture(autouse=True)
def local_backend(monkeypatch):
    monkeypatch.setenv("VOICE_ENABLED", "1")
    monkeypatch.setattr(main, "backend", lambda: nullcontext(client))
    routes.TURNS.clear()


def over_the_limit():
    calculate("CLM-1011")
    decide("CLM-1011", "approve", 1500.0)


def test_tools():
    assert [t.name for t in voice.tools("HND-01")] == [
        "find_claims",
        "get_claim_brief",
        "get_decision_brief",
        "list_signoff_queue",
        "get_latest_run_status",
        "get_analytics_brief",
        "start_claim_run",
        "open_claim",
        "request_signoff",
    ]


def test_turn_reads_the_totals():
    model = ScriptedVoiceModel()
    result = voice.run_turn("s1", "HND-01", "how are we doing", model)
    assert result["tools"] == ["get_analytics_brief"]
    assert result["reply"].startswith("35 waiting")
    assert "dollars" in result["speech"]
    assert result["ui_action"] == {"type": "none", "claim_id": ""}
    system = model.prompts[0][0].text
    assert system == client.get("/api/voice/instructions").json()["text"]


def test_turn_opens_a_claim_without_reading_its_story():
    model = ScriptedVoiceModel()
    result = voice.run_turn("s2", "HND-01", "open claim ten twenty four", model)
    assert result["tools"] == ["find_claims", "open_claim"]
    assert result["ui_action"] == {"type": "open_claim", "claim_id": "CLM-1024"}
    story = client.get("/api/claims/CLM-1024").json()["story"]
    assert all(story not in m.text for prompt in model.prompts for m in prompt)


def test_sign_off_by_voice_is_only_a_request():
    over_the_limit()
    result = voice.run_turn("s3", "HND-01", "sign off ten eleven", ScriptedVoiceModel())
    assert result["tools"] == ["find_claims", "request_signoff"]
    assert result["ui_action"] == {"type": "focus_signoff", "claim_id": "CLM-1011"}
    assert client.get("/api/claims/CLM-1011").json()["state"] == "waiting_for_signoff"
    refused = voice.run_turn(
        "s4", "HND-04", "sign off ten eleven", ScriptedVoiceModel()
    )
    assert "not allowed" in refused["reply"]
    assert refused["ui_action"]["type"] == "none"


def test_sign_off_queue():
    over_the_limit()
    result = voice.run_turn(
        "s5", "HND-01", "what is waiting for my sign off", ScriptedVoiceModel()
    )
    assert result["reply"] == "Waiting for sign-off: CLM-1011."


def test_session_keeps_its_history():
    model = ScriptedVoiceModel()
    voice.run_turn("s6", "HND-01", "how are we doing", model)
    second = voice.run_turn("s6", "HND-01", "open claim ten oh two", model)
    assert second["tools"] == ["find_claims", "open_claim"]
    assert len(model.prompts[-1]) > len(model.prompts[0])


def test_turn_through_the_api(monkeypatch):
    monkeypatch.setenv("AGENT_STUB", "1")
    body = {"session_id": "s7", "handler_id": "HND-01", "text": "open ten oh two"}
    result = client.post("/api/voice/turn", json=body).json()
    assert result["status"] == "succeeded"
    assert result["ui_action"]["claim_id"] == "CLM-1002"
    turns = client.get("/api/voice/sessions/s7").json()
    assert turns[0]["tools"] == ["find_claims", "open_claim"]


def test_other_tools():
    tools = {t.name: t for t in voice.tools("HND-01")}
    assert (
        tools["get_claim_brief"].invoke({"claim_id": "CLM-1002"})["state"] == "waiting"
    )
    assert (
        tools["get_decision_brief"].invoke({"claim_id": "CLM-1002"})["decision"] == ""
    )
    assert (
        tools["get_latest_run_status"].invoke({"claim_id": "CLM-1002"})["status"] == ""
    )
    started = tools["start_claim_run"].invoke({"claim_id": "CLM-9999"})
    assert started == {"error": "There is no claim CLM-9999."}


def test_voice_model(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("MODEL_NAME", raising=False)
    monkeypatch.delenv("VOICE_MODEL_NAME", raising=False)
    assert voice.model().model_name == "deepseek/deepseek-v4.1-flash"
    monkeypatch.setenv("VOICE_MODEL_NAME", "openrouter/free")
    assert voice.model().model_name == "openrouter/free"


def test_unknown_claim_and_empty_queue():
    missing = voice.run_turn("s8", "HND-01", "open claim nobody", ScriptedVoiceModel())
    assert missing["reply"] == "I could not find that claim."
    empty = voice.run_turn(
        "s9", "HND-01", "what is waiting for my sign off", ScriptedVoiceModel()
    )
    assert empty["reply"] == "Waiting for sign-off: nothing."
