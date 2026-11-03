"""Working out payouts, recording decisions and paying claims."""

import json
import sqlite3
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend import auth, clock, db, payout, sections, store

router = APIRouter(prefix="/api")


class Calculation(BaseModel):
    """The lines to pay and what others have already paid."""

    run_id: str
    lines: list[payout.Line]
    paid_by_others: float


class Decision(BaseModel):
    """The agent's decision on a claim."""

    run_id: str
    decision: Literal["approve", "decline", "refer"]
    payout: float
    reason: str
    sections: list[str]
    model: str


class Payment(BaseModel):
    """An amount to pay on a claim."""

    run_id: str
    amount: float


def limit_cents(conn: sqlite3.Connection, tenant_id: str) -> int:
    """Return the tenant's payout approval limit in cents."""
    company = db.reference(conn, "company", tenant_id)
    return db.cents(company["payout_approval_limit"])


def holds(
    conn: sqlite3.Connection, who: auth.Principal, run_id: str, claim_id: str
) -> None:
    """Refuse unless the run is a live claim run on this claim, under this token."""
    store.claim_row(conn, claim_id, who.tenant_id)
    if store.live_run(conn, run_id, who.tenant_id)["claim_id"] != claim_id:
        raise HTTPException(409, f"Run {run_id} is not working claim {claim_id}.")
    if run_id != who.run_id:
        raise HTTPException(403, f"This token is not for run {run_id}.")


def cited(conn: sqlite3.Connection, run_id: str, ids: list[str]) -> str:
    """Return the cited sections as text, or refuse what the run never read."""
    if not ids:
        raise HTTPException(409, "Cite at least one section you relied on.")
    read = store.read_sections(conn, run_id)
    unread = [s for s in ids if s not in read]
    if unread:
        raise HTTPException(
            409,
            f"Section {', '.join(unread)} was not read on this run."
            " Read it with read_section before you cite it.",
        )
    return "; ".join(sections.title(s) for s in ids)


def pay(
    conn: sqlite3.Connection, tenant_id: str, claim_id: str, amount_cents: int
) -> None:
    """Record a payment. No money leaves the system."""
    conn.execute(
        "INSERT INTO payments (claim_id, amount_cents, created_at, tenant_id)"
        " VALUES (?, ?, ?, ?)",
        (claim_id, amount_cents, clock.stamp(), tenant_id),
    )


@router.post("/claims/{claim_id}/calculate", operation_id="calculate_payout")
def calculate_payout(claim_id: str, body: Calculation, who: auth.Who) -> dict[str, Any]:
    """Work out a payout under section 10 of the policy wording."""
    with db.connect() as conn:
        holds(conn, who, body.run_id, claim_id)
        claim = store.claim_row(conn, claim_id, who.tenant_id)
        policy = store.policy_view(conn, claim["policy_id"], who.tenant_id)
        benefit = json.loads(claim["data"])["claim_type"]
        total, steps = payout.calculate(
            policy, benefit, body.lines, body.paid_by_others
        )
        conn.execute(
            "INSERT INTO calculations (claim_id, payout_cents, steps, created_at,"
            " tenant_id) VALUES (?, ?, ?, ?, ?)",
            (claim_id, total, json.dumps(steps), clock.stamp(), who.tenant_id),
        )
    return {"payout": db.dollars(total), "steps": steps}


@router.post("/claims/{claim_id}/decision", operation_id="record_decision")
def record_decision(claim_id: str, body: Decision, who: auth.Who) -> dict[str, Any]:
    """Store the agent's decision on a claim."""
    with db.connect() as conn:
        holds(conn, who, body.run_id, claim_id)
        if store.claim_row(conn, claim_id, who.tenant_id)["state"] != "in_progress":
            raise HTTPException(409, f"Claim {claim_id} is already decided.")
        if not body.reason.strip():
            raise HTTPException(409, "The reason is missing.")
        section = cited(conn, body.run_id, body.sections)
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
        company = db.reference(conn, "company", who.tenant_id)
        wording = company["policy_wording_version"]
        conn.execute(
            "INSERT INTO decisions (claim_id, decision, payout_cents, reason, section,"
            " steps, model, wording_version, created_at, sections, run_id, tenant_id)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                claim_id,
                body.decision,
                amount,
                body.reason,
                section,
                json.dumps(steps),
                body.model,
                wording,
                clock.stamp(),
                json.dumps(body.sections),
                body.run_id,
                who.tenant_id,
            ),
        )
        over = body.decision == "approve" and amount > limit_cents(conn, who.tenant_id)
        state = "waiting_for_signoff" if over else "decided"
        store.set_state(conn, claim_id, state)
    return {"claim_id": claim_id, "state": state, "decision": body.decision}


@router.post("/claims/{claim_id}/pay", operation_id="pay_claim")
def pay_claim(claim_id: str, body: Payment, who: auth.Who) -> dict[str, Any]:
    """Pay an amount, blocked until a handler signs off when over the limit."""
    with db.connect() as conn:
        holds(conn, who, body.run_id, claim_id)
        latest = store.latest_decision(conn, claim_id)
        amount = db.cents(body.amount)
        if latest is None or latest["decision"] != "approve":
            raise HTTPException(409, "Only an approved claim can be paid.")
        if latest["payout_cents"] != amount:
            raise HTTPException(409, "The amount must match the approved payout.")
        if store.paid_cents(conn, claim_id):
            raise HTTPException(409, "This claim is already paid.")
        if amount > limit_cents(conn, who.tenant_id):
            raise HTTPException(409, "Waiting for a handler's sign-off.")
        pay(conn, who.tenant_id, claim_id, amount)
    return {"claim_id": claim_id, "paid": db.dollars(amount)}
