"""Reading claims, policies, customers, handlers, the wording and instructions."""

import json
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from backend import db, seed, store

router = APIRouter(prefix="/api")
INSTRUCTIONS = Path(__file__).parent / "instructions.md"


def summary(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    """Return one claim as it appears in the queue."""
    data = json.loads(row["data"])
    name = store.customer_name(conn, row["customer_id"])
    latest = store.latest_decision(conn, row["claim_id"])
    return {
        "claim_id": row["claim_id"],
        "policy_id": row["policy_id"],
        "customer_id": row["customer_id"],
        "customer": store.short_name(name),
        "customer_name": name,
        "claim_type": data["claim_type"],
        "summary": data["summary"],
        "amount_claimed": data["amount_claimed"],
        "state": row["state"],
        "state_since": row["state_since"],
        "decision": latest["decision"] if latest else "",
        "payout": db.dollars(latest["payout_cents"]) if latest else 0.0,
        "paid": db.dollars(store.paid_cents(conn, row["claim_id"])),
    }


@router.get("/claims", operation_id="list_claims")
def list_claims() -> list[dict[str, Any]]:
    """List the queue with each claim's state and latest decision."""
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM claims ORDER BY claim_id").fetchall()
        return [summary(conn, row) for row in rows]


@router.get("/claims/{claim_id}", operation_id="get_claim")
def get_claim(claim_id: str) -> dict[str, Any]:
    """Return one claim in full, with its decisions and runs."""
    with db.connect() as conn:
        row = store.claim_row(conn, claim_id)
        data = json.loads(row["data"])
        decisions = conn.execute(
            "SELECT * FROM decisions WHERE claim_id = ? ORDER BY id", (claim_id,)
        ).fetchall()
        runs = conn.execute(
            "SELECT * FROM runs WHERE claim_id = ? ORDER BY started_at", (claim_id,)
        ).fetchall()
        sendbacks = conn.execute(
            "SELECT handler_id, reason, created_at FROM sendbacks WHERE claim_id = ?",
            (claim_id,),
        ).fetchall()
        return summary(conn, row) | {
            "incident_date": data["incident_date"],
            "incident_location": data["incident_location"],
            "submitted_on": data["submitted_on"],
            "story": data["story"],
            "items": data["items"],
            "documents": data["documents"],
            "decisions": [store.decision_view(d) for d in decisions],
            "runs": [dict(r) for r in runs],
            "sendbacks": [dict(s) for s in sendbacks],
        }


@router.get("/policies/{policy_id}", operation_id="get_policy")
def get_policy(policy_id: str) -> dict[str, Any]:
    """Return one policy with its plan's limits and add-ons."""
    with db.connect() as conn:
        return store.policy_view(conn, policy_id)


@router.get("/customers/{customer_id}/history", operation_id="get_customer_history")
def get_customer_history(customer_id: str) -> dict[str, Any]:
    """Return the customer's name and earlier claims."""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT data FROM customers WHERE customer_id = ?", (customer_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(404, f"There is no customer {customer_id}.")
    customer = json.loads(row["data"])
    return {
        "customer_id": customer_id,
        "name": customer["name"],
        "customer_since": customer["customer_since"],
        "previous_claims": customer["previous_claims"],
    }


@router.get("/wording", operation_id="get_policy_wording")
def get_policy_wording() -> dict[str, str]:
    """Return the policy wording text and its version."""
    with db.connect() as conn:
        version = db.reference(conn, "company")["policy_wording_version"]
    text = (seed.data_dir() / "policy_wording.md").read_text(encoding="utf-8")
    return {"version": version, "text": text}


@router.get("/instructions", operation_id="get_instructions")
def get_instructions() -> dict[str, str]:
    """Return the agent's instructions."""
    return {"text": INSTRUCTIONS.read_text(encoding="utf-8")}


@router.get("/handlers", operation_id="list_handlers")
def list_handlers() -> list[dict[str, Any]]:
    """List the handlers and whether they can sign off."""
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM handlers ORDER BY handler_id").fetchall()
    return [
        {
            "handler_id": r["handler_id"],
            "name": r["name"],
            "role": r["role"],
            "can_approve_over_limit": bool(r["can_approve_over_limit"]),
        }
        for r in rows
    ]
