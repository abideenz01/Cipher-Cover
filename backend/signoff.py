"""Handlers sign off payouts over the limit, or send claims back."""

import sqlite3
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from backend import auth, clock, db, decisions, security_events, store
from backend.voice.briefs import speak_claim_id, speak_money

router = APIRouter(prefix="/api")


class SendBack(BaseModel):
    """Why the signed-in handler is sending a claim back."""

    reason: str = Field(min_length=1)


def acting_handler(conn: sqlite3.Connection, who: auth.Principal) -> sqlite3.Row:
    """Return the handler record of the signed-in person, or refuse."""
    if not who.handler_id:
        raise HTTPException(403, "Only a claims handler can do that.")
    return store.handler_row(conn, who.handler_id, who.tenant_id)


@router.get("/signoffs", operation_id="list_signoffs")
def list_signoffs(who: auth.Who) -> list[dict[str, Any]]:
    """List approved payouts waiting for a handler's sign-off."""
    with db.connect() as conn:
        sla = db.reference(conn, "company", who.tenant_id)["sign_off_sla_hours"]
        rows = conn.execute(
            "SELECT * FROM claims WHERE state = 'waiting_for_signoff'"
            " AND tenant_id = ? ORDER BY state_since",
            (who.tenant_id,),
        ).fetchall()
        waiting = []
        for row in rows:
            latest = store.decided(conn, row["claim_id"])
            since = datetime.fromisoformat(row["state_since"])
            hours = (clock.now() - since).total_seconds() / 3600
            waiting.append(
                {
                    "claim_id": row["claim_id"],
                    "customer": store.short_name(
                        store.customer_name(conn, row["customer_id"], who.tenant_id)
                    ),
                    "payout": db.dollars(latest["payout_cents"]),
                    "reason": latest["reason"],
                    "section": latest["section"],
                    "waiting_since": row["state_since"],
                    "hours_waiting": round(hours, 1),
                    "overdue": hours > sla,
                    "speech": f"{speak_claim_id(row['claim_id']).capitalize()} for"
                    f" {speak_money(db.dollars(latest['payout_cents']))}",
                }
            )
    return waiting


@router.post("/claims/{claim_id}/sign-off", operation_id="sign_off_claim")
def sign_off_claim(claim_id: str, who: auth.Who, request: Request) -> dict[str, Any]:
    """The signed-in handler signs off a payout, which pays it."""
    with db.connect() as conn:
        claim = store.claim_row(conn, claim_id, who.tenant_id)
        handler = acting_handler(conn, who)
        if not handler["can_approve_over_limit"]:
            raise HTTPException(403, f"{handler['name']} cannot sign off payouts.")
        if claim["state"] != "waiting_for_signoff":
            raise HTTPException(409, "This claim is not waiting for sign-off.")
        latest = store.decided(conn, claim_id)
        amount = latest["payout_cents"]
        conn.execute(
            "INSERT INTO signoffs (claim_id, handler_id, amount_cents, created_at,"
            " tenant_id) VALUES (?, ?, ?, ?, ?)",
            (claim_id, who.handler_id, amount, clock.stamp(), who.tenant_id),
        )
        decisions.pay(conn, who.tenant_id, claim_id, amount)
        security_events.record(
            conn,
            who.tenant_id,
            who.actor,
            "sign_off",
            claim_id,
            "ok",
            auth.ip(request),
            {"amount_cents": amount},
        )
        store.set_state(conn, claim_id, "decided")
    return {"claim_id": claim_id, "state": "decided", "paid": db.dollars(amount)}


@router.post("/claims/{claim_id}/send-back", operation_id="send_back_claim")
def send_back_claim(
    claim_id: str, body: SendBack, who: auth.Who, request: Request
) -> dict[str, Any]:
    """The signed-in handler returns a claim to the queue with a reason."""
    with db.connect() as conn:
        claim = store.claim_row(conn, claim_id, who.tenant_id)
        acting_handler(conn, who)
        if claim["state"] != "waiting_for_signoff":
            raise HTTPException(409, "This claim is not waiting for sign-off.")
        conn.execute(
            "INSERT INTO sendbacks (claim_id, handler_id, reason, created_at,"
            " tenant_id) VALUES (?, ?, ?, ?, ?)",
            (claim_id, who.handler_id, body.reason, clock.stamp(), who.tenant_id),
        )
        security_events.record(
            conn,
            who.tenant_id,
            who.actor,
            "send_back",
            claim_id,
            "ok",
            auth.ip(request),
        )
        store.set_state(conn, claim_id, "waiting")
    return {"claim_id": claim_id, "state": "waiting"}
