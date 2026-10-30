"""The voice assistant's operations, off unless VOICE_ENABLED=1."""

import json
import os
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as TurnTimeout
from datetime import timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from agent import voice
from agent.voice_stub import ScriptedVoiceModel
from backend import clock, db, store
from backend.voice import briefs, normalize

INSTRUCTIONS = Path(__file__).parent.parent / "voice_instructions.md"
FALLBACK = "I could not do that. Try again or type it."
TURNS: dict[str, deque[float]] = defaultdict(deque)
POOL = ThreadPoolExecutor(max_workers=4)
WINDOW_SECONDS = 60
SHORTEST_NAME = 3


def enabled() -> bool:
    """Return whether voice is switched on."""
    return os.getenv("VOICE_ENABLED") == "1"


def require_voice() -> None:
    """Answer 404 for every voice operation while voice is off."""
    if not enabled():
        raise HTTPException(404, "Voice is off.")


config_router = APIRouter(prefix="/api")
router = APIRouter(prefix="/api", dependencies=[Depends(require_voice)])


class Turn(BaseModel):
    """One spoken or typed request from a handler."""

    session_id: str
    handler_id: str
    text: str


class SignOffRequest(BaseModel):
    """The handler who will confirm the sign-off on screen."""

    handler_id: str


@config_router.get("/voice/config", operation_id="get_voice_config")
def get_voice_config() -> dict[str, Any]:
    """Return whether voice is on and which provider it uses."""
    return {"enabled": enabled(), "provider": os.getenv("VOICE_PROVIDER") or "browser"}


@router.get("/voice/instructions", operation_id="get_voice_instructions")
def get_voice_instructions() -> dict[str, str]:
    """Return the voice assistant's instructions."""
    return {"text": INSTRUCTIONS.read_text(encoding="utf-8")}


def check_rate(session_id: str) -> None:
    """Allow VOICE_TURNS_PER_MINUTE turns per session, then answer 429."""
    limit = int(os.getenv("VOICE_TURNS_PER_MINUTE") or "20")
    now = clock.now().timestamp()
    turns = TURNS[session_id]
    while turns and now - turns[0] > WINDOW_SECONDS:
        turns.popleft()
    if len(turns) >= limit:
        raise HTTPException(429, "Too many requests. Wait a minute and try again.")
    turns.append(now)


def answer(body: Turn) -> dict[str, Any]:
    """Run the voice agent, with the scripted model when AGENT_STUB=1."""
    llm = ScriptedVoiceModel() if os.getenv("AGENT_STUB") == "1" else None
    return voice.run_turn(body.session_id, body.handler_id, body.text, llm)


def checked(action: dict[str, Any], handler_id: str) -> dict[str, Any]:
    """Keep a sign-off highlight only if a sign-off request backs it."""
    if action["type"] != "focus_signoff":
        return action
    with db.connect() as conn:
        request = conn.execute(
            "SELECT 1 FROM signoff_requests WHERE claim_id = ? AND handler_id = ?"
            " AND expires_at > ?",
            (action["claim_id"], handler_id, clock.stamp()),
        ).fetchone()
    return action if request else {"type": "none", "claim_id": ""}


@router.post("/voice/turn", operation_id="voice_turn")
def voice_turn(body: Turn) -> dict[str, Any]:
    """Answer one request from a handler with a reply, speech and screen action."""
    check_rate(body.session_id)
    with db.connect() as conn:
        store.handler_row(conn, body.handler_id)
    timeout = float(os.getenv("VOICE_TURN_TIMEOUT_SECONDS") or "30")
    started = time.monotonic()
    try:
        result = POOL.submit(answer, body).result(timeout=timeout)
        status = "succeeded"
        result["ui_action"] = checked(result["ui_action"], body.handler_id)
    except TurnTimeout:
        none = {"type": "none", "claim_id": ""}
        result = {"reply": FALLBACK, "speech": FALLBACK, "ui_action": none, "tools": []}
        status = "failed"
    latency = round((time.monotonic() - started) * 1000)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO voice_turns (session_id, handler_id, transcript, reply,"
            " speech, ui_action, tools, status, latency_ms, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                body.session_id,
                body.handler_id,
                body.text,
                result["reply"],
                result["speech"],
                json.dumps(result["ui_action"]),
                json.dumps(result["tools"]),
                status,
                latency,
                clock.stamp(),
            ),
        )
    return result | {"status": status}


@router.get("/voice/sessions/{session_id}", operation_id="list_voice_turns")
def list_voice_turns(session_id: str) -> list[dict[str, Any]]:
    """Return one session's turns for the captions panel."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM voice_turns WHERE session_id = ? ORDER BY id", (session_id,)
        ).fetchall()
    return [
        dict(r)
        | {"ui_action": json.loads(r["ui_action"]), "tools": json.loads(r["tools"])}
        for r in rows
    ]


@router.get("/claims/search", operation_id="search_claims")
def search_claims(text: str) -> list[dict[str, Any]]:
    """Find claims matching a spoken or typed claim number or a surname."""
    claim_id = normalize.claim_id(text)
    words = {w.strip(".,?!'s").lower() for w in text.split() if len(w) >= SHORTEST_NAME}
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT claims.claim_id, customers.name FROM claims"
            " JOIN customers USING (customer_id) ORDER BY claim_id"
        ).fetchall()
        found = [
            r["claim_id"]
            for r in rows
            if r["claim_id"] == claim_id
            or (not claim_id and words & {n.lower() for n in r["name"].split()})
        ]
        return [briefs.claim_brief(conn, c) for c in found]


@router.get("/claims/{claim_id}/brief", operation_id="get_claim_brief")
def get_claim_brief(claim_id: str) -> dict[str, Any]:
    """Return one claim's facts, with no free text."""
    with db.connect() as conn:
        return briefs.claim_brief(conn, claim_id)


@router.get("/claims/{claim_id}/decision-brief", operation_id="get_decision_brief")
def get_decision_brief(claim_id: str) -> dict[str, Any]:
    """Return the latest decision, payout and reason."""
    with db.connect() as conn:
        return briefs.decision_brief(conn, claim_id)


@router.get("/claims/{claim_id}/run-status", operation_id="get_run_status_brief")
def get_run_status_brief(claim_id: str) -> dict[str, Any]:
    """Return the latest run on a claim and its outcome."""
    with db.connect() as conn:
        return briefs.run_status_brief(conn, claim_id)


@router.get("/analytics/brief", operation_id="get_analytics_brief")
def get_analytics_brief() -> dict[str, Any]:
    """Return the number of claims in each state and the total paid."""
    with db.connect() as conn:
        return briefs.analytics_brief(conn)


@router.post("/claims/{claim_id}/signoff-request", operation_id="request_signoff")
def request_signoff(claim_id: str, body: SignOffRequest) -> dict[str, Any]:
    """Prepare a sign-off for one handler to confirm on screen."""
    with db.connect() as conn:
        claim = store.claim_row(conn, claim_id)
        handler = store.handler_row(conn, body.handler_id)
        if not handler["can_approve_over_limit"]:
            raise HTTPException(403, f"{handler['name']} is not allowed to sign off.")
        if claim["state"] != "waiting_for_signoff":
            raise HTTPException(409, f"{claim_id} is not waiting for sign-off.")
        now = clock.now()
        conn.execute(
            "INSERT INTO signoff_requests"
            " (claim_id, handler_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (
                claim_id,
                body.handler_id,
                now.isoformat(timespec="seconds"),
                (now + timedelta(minutes=10)).isoformat(timespec="seconds"),
            ),
        )
    spoken = briefs.speak_claim_id(claim_id).capitalize()
    return {
        "claim_id": claim_id,
        "state": claim["state"],
        "reply": f"{claim_id} is highlighted on the Sign-off screen. Confirm it there.",
        "speech": f"{spoken} is highlighted on the Sign-off screen. Confirm it there.",
        "ui_action": {"type": "focus_signoff", "claim_id": claim_id},
    }
