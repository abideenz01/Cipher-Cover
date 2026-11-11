import json
from contextlib import nullcontext
from pathlib import Path

import pytest
from langchain_core.callbacks import BaseCallbackHandler

from agent import main, tracing
from agent.stub import ScriptedModel
from backend import db, runs
from backend.tests import sessions

DATA = Path(__file__).parents[2] / "data"
client = sessions.client()


class Recorder(BaseCallbackHandler):
    """Keep everything a tracing handler would be given."""

    def __init__(self):
        self.metadata = []
        self.payloads = []

    def on_chain_start(self, serialized, inputs, *, metadata=None, **kwargs):
        self.metadata.append(metadata or {})
        self.payloads.append(str(inputs))

    def on_chat_model_start(self, serialized, messages, **kwargs):
        self.payloads.append(str(messages))

    def on_tool_end(self, output, **kwargs):
        self.payloads.append(str(output))


@pytest.fixture(autouse=True)
def local_backend(monkeypatch):
    monkeypatch.setattr(main, "backend", lambda: nullcontext(client))


@pytest.fixture
def recorder(monkeypatch):
    recorder = Recorder()
    monkeypatch.setattr(tracing, "callbacks", lambda: [recorder])
    return recorder


def run_claim(claim_id):
    run_id = runs.begin(claim_id, sessions.TENANT)
    with db.connect() as conn:
        token = runs.claim_token(conn, run_id)
    with main.acting(token):
        main.run(claim_id, run_id, ScriptedModel())
    return run_id


def test_without_keys_nothing_is_traced(monkeypatch):
    for key in tracing.KEYS:
        monkeypatch.delenv(key, raising=False)
    assert not tracing.enabled()
    assert tracing.callbacks() == []
    tracing.flush()


def test_with_keys_a_claim_gets_its_own_trace(monkeypatch):
    for key in tracing.KEYS:
        monkeypatch.setenv(key, "https://langfuse.invalid" if "URL" in key else "k")
    contexts = []

    def handler(*, trace_context):
        contexts.append(trace_context)

    monkeypatch.setattr(tracing, "CallbackHandler", handler)
    tracing.client.cache_clear()
    try:
        tracing.callbacks()
        tracing.callbacks()
        assert contexts[0]["trace_id"] != contexts[1]["trace_id"]
    finally:
        tracing.client().shutdown()
        tracing.client.cache_clear()


def test_a_claim_is_one_session_named_after_the_claim_and_thread(recorder):
    run_id = run_claim("CLM-1001")
    sessions_seen = {m.get("langfuse_session_id") for m in recorder.metadata}
    assert sessions_seen == {f"CLM-1001:{run_id}"}


def test_medical_documents_and_contact_details_never_reach_the_trace(recorder):
    claim = next(
        c
        for c in json.loads((DATA / "claims.json").read_text(encoding="utf-8"))
        if c["claim_id"] == "CLM-1003"
    )
    customer = next(
        c
        for c in json.loads((DATA / "customers.json").read_text(encoding="utf-8"))
        if c["customer_id"] == claim["customer_id"]
    )
    medical = [
        d["content"]
        for d in claim["documents"]
        if d["type"] in ("medical_record", "medical_bill")
    ]
    run_claim("CLM-1003")
    sent = "\n".join(recorder.payloads)
    assert "medical document withheld" in sent
    assert medical
    assert all(text[:80] not in sent for text in medical)
    assert customer["email"] not in sent


def test_the_mask_replaces_email_addresses_at_any_depth():
    data = {"a": ["write to x.y+z@example.com"], "b": ("c@d.org",), "n": 3}
    assert tracing.mask(data=data) == {
        "a": ["write to [email]"],
        "b": ["[email]"],
        "n": 3,
    }
