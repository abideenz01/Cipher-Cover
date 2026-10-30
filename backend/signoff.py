"""Handlers sign off payouts over the limit, or send claims back."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend import clock, db, decisions, store
from backend.voice.briefs import speak_claim_id, speak_money

router = APIRouter(prefix="/api")


class SignOff(BaseModel):
    """The handler signing off."""

    handler_id: str


class SendBack(BaseModel):
    """The handler sending a claim back and why."""

    handler_id: str
    reason: str = Field(min_length=1)


@router.get("/signoffs", operation_id="list_signoffs")
def list_signoffs() -> list[dict[str, Any]]:
    """List approved payouts waiting for a handler's sign-off."""
    with db.connect() as conn:
        sla = db.reference(conn, "company")["sign_off_sla_hours"]
        rows = conn.execute(
            "SELECT * FROM claims WHERE state = 'waiting_for_signoff'"
            " ORDER BY state_since"
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
                        store.customer_name(conn, row["customer_id"])
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
def sign_off_claim(claim_id: str, body: SignOff) -> dict[str, Any]:
    """A handler signs off a payout, which pays it."""
    with db.connect() as conn:
        claim = store.claim_row(conn, claim_id)
        handler = store.handler_row(conn, body.handler_id)
        if not handler["can_approve_over_limit"]:
            raise HTTPException(403, f"{handler['name']} cannot sign off payouts.")
        if claim["state"] != "waiting_for_signoff":
            raise HTTPException(409, "This claim is not waiting for sign-off.")
        latest = store.decided(conn, claim_id)
        amount = latest["payout_cents"]
        conn.execute(
            "INSERT INTO signoffs (claim_id, handler_id, amount_cents, created_at)"
            " VALUES (?, ?, ?, ?)",
            (claim_id, body.handler_id, amount, clock.stamp()),
        )
        decisions.pay(conn, claim_id, amount)
        store.set_state(conn, claim_id, "decided")
    return {"claim_id": claim_id, "state": "decided", "paid": db.dollars(amount)}


@router.post("/claims/{claim_id}/send-back", operation_id="send_back_claim")
def send_back_claim(claim_id: str, body: SendBack) -> dict[str, Any]:
    """A handler returns a claim to the queue with a reason."""
    with db.connect() as conn:
        claim = store.claim_row(conn, claim_id)
        store.handler_row(conn, body.handler_id)
        if claim["state"] != "waiting_for_signoff":
            raise HTTPException(409, "This claim is not waiting for sign-off.")
        conn.execute(
            "INSERT INTO sendbacks (claim_id, handler_id, reason, created_at)"
            " VALUES (?, ?, ?, ?)",
            (claim_id, body.handler_id, body.reason, clock.stamp()),
        )
        store.set_state(conn, claim_id, "waiting")
    return {"claim_id": claim_id, "state": "waiting"}
