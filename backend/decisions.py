"""Working out payouts, recording decisions and paying claims."""

import json
import sqlite3
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend import clock, db, payout, store

router = APIRouter(prefix="/api")


class Calculation(BaseModel):
    """The lines to pay and what others have already paid."""

    lines: list[payout.Line]
    paid_by_others: float


class Decision(BaseModel):
    """The agent's decision on a claim."""

    decision: Literal["approve", "decline", "refer"]
    payout: float
    reason: str
    section: str
    model: str


class Payment(BaseModel):
    """An amount to pay on a claim."""

    amount: float


def limit_cents(conn: sqlite3.Connection) -> int:
    """Return the payout approval limit in cents."""
    return db.cents(db.reference(conn, "company")["payout_approval_limit"])


def pay(conn: sqlite3.Connection, claim_id: str, amount_cents: int) -> None:
    """Record a payment. No money leaves the system."""
    conn.execute(
        "INSERT INTO payments (claim_id, amount_cents, created_at) VALUES (?, ?, ?)",
        (claim_id, amount_cents, clock.stamp()),
    )


@router.post("/claims/{claim_id}/calculate", operation_id="calculate_payout")
def calculate_payout(claim_id: str, body: Calculation) -> dict[str, Any]:
    """Work out a payout under section 10 of the policy wording."""
    with db.connect() as conn:
        claim = store.claim_row(conn, claim_id)
        policy = store.policy_view(conn, claim["policy_id"])
        benefit = json.loads(claim["data"])["claim_type"]
        total, steps = payout.calculate(
            policy, benefit, body.lines, body.paid_by_others
        )
        conn.execute(
            "INSERT INTO calculations (claim_id, payout_cents, steps, created_at)"
            " VALUES (?, ?, ?, ?)",
            (claim_id, total, json.dumps(steps), clock.stamp()),
        )
    return {"payout": db.dollars(total), "steps": steps}


@router.post("/claims/{claim_id}/decision", operation_id="record_decision")
def record_decision(claim_id: str, body: Decision) -> dict[str, Any]:
    """Store the agent's decision on a claim."""
    with db.connect() as conn:
        store.claim_row(conn, claim_id)
        if store.paid_cents(conn, claim_id):
            raise HTTPException(409, "This claim is already paid.")
        amount = db.cents(body.payout)
        steps: list[dict[str, Any]] = []
        if body.decision == "approve":
            calc = conn.execute(
                "SELECT * FROM calculations WHERE claim_id = ? ORDER BY id DESC",
                (claim_id,),
            ).fetchone()
            if calc is None or calc["payout_cents"] != amount:
                raise HTTPException(
                    409, "The payout must match the latest calculate_payout result."
                )
            steps = json.loads(calc["steps"])
        elif amount:
            raise HTTPException(409, "A decline or referral pays $0.00.")
        wording = db.reference(conn, "company")["policy_wording_version"]
        conn.execute(
            "INSERT INTO decisions (claim_id, decision, payout_cents, reason, section,"
            " steps, model, wording_version, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                claim_id,
                body.decision,
                amount,
                body.reason,
                body.section,
                json.dumps(steps),
                body.model,
                wording,
                clock.stamp(),
            ),
        )
        over = body.decision == "approve" and amount > limit_cents(conn)
        state = "waiting_for_signoff" if over else "decided"
        store.set_state(conn, claim_id, state)
    return {"claim_id": claim_id, "state": state, "decision": body.decision}


@router.post("/claims/{claim_id}/pay", operation_id="pay_claim")
def pay_claim(claim_id: str, body: Payment) -> dict[str, Any]:
    """Pay an amount, blocked until a handler signs off when over the limit."""
    with db.connect() as conn:
        store.claim_row(conn, claim_id)
        latest = store.latest_decision(conn, claim_id)
        amount = db.cents(body.amount)
        if latest is None or latest["decision"] != "approve":
            raise HTTPException(409, "Only an approved claim can be paid.")
        if latest["payout_cents"] != amount:
            raise HTTPException(409, "The amount must match the approved payout.")
        if store.paid_cents(conn, claim_id):
            raise HTTPException(409, "This claim is already paid.")
        if amount > limit_cents(conn):
            raise HTTPException(409, "Waiting for a handler's sign-off.")
        pay(conn, claim_id, amount)
    return {"claim_id": claim_id, "paid": db.dollars(amount)}
