"""Reading claims, policies, customers, handlers, the wording and instructions."""

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from backend import auth, db, seed, store

router = APIRouter(prefix="/api")
INSTRUCTIONS = Path(__file__).parent
MEDICAL = ("medical_record", "medical_bill")


def withheld(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Replace the text of medical documents, which must not reach a model."""
    return [
        d | {"content": f"[medical document withheld: {len(d['content'])} characters]"}
        if d["type"] in MEDICAL
        else d
        for d in documents
    ]


def summary(
    conn: sqlite3.Connection, row: sqlite3.Row, who: auth.Principal
) -> dict[str, Any]:
    """Return one claim as it appears in the queue. Agents see a short name only."""
    data = json.loads(row["data"])
    name = store.customer_name(conn, row["customer_id"], row["tenant_id"])
    latest = store.latest_decision(conn, row["claim_id"])
    return {
        "claim_id": row["claim_id"],
        "policy_id": row["policy_id"],
        "customer_id": row["customer_id"],
        "customer": store.short_name(name),
        "customer_name": store.short_name(name) if who.agent else name,
        "claim_type": data["claim_type"],
        "summary": data["summary"],
        "amount_claimed": data["amount_claimed"],
        "state": row["state"],
        "state_since": row["state_since"],
        "failed_attempts": row["failed_attempts"],
        "left_for_handler": row["failed_attempts"] >= store.FAILURES_FOR_HANDLER,
        "decision": latest["decision"] if latest else "",
        "payout": db.dollars(latest["payout_cents"]) if latest else 0.0,
        "paid": db.dollars(store.paid_cents(conn, row["claim_id"])),
    }


@router.get("/claims", operation_id="list_claims")
def list_claims(who: auth.Who) -> list[dict[str, Any]]:
    """List the queue with each claim's state and latest decision."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM claims WHERE tenant_id = ? ORDER BY claim_id",
            (who.tenant_id,),
        ).fetchall()
        return [summary(conn, row, who) for row in rows]


@router.get("/claims/{claim_id}", operation_id="get_claim")
def get_claim(claim_id: str, who: auth.Who) -> dict[str, Any]:
    """Return one claim in full, with its decisions and runs."""
    with db.connect() as conn:
        row = store.claim_row(conn, claim_id, who.tenant_id)
        medical = auth.tenant_config(conn, who.tenant_id).get("external_model_medical")
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
        documents = data["documents"]
        if who.agent and not medical:
            documents = withheld(documents)
        return summary(conn, row, who) | {
            "incident_date": data["incident_date"],
            "incident_location": data["incident_location"],
            "submitted_on": data["submitted_on"],
            "story": data["story"],
            "items": data["items"],
            "documents": documents,
            "decisions": [store.decision_view(d) for d in decisions],
            "runs": [store.run_view(conn, r) for r in runs],
            "sendbacks": [dict(s) for s in sendbacks],
        }


@router.get("/policies/{policy_id}", operation_id="get_policy")
def get_policy(policy_id: str, who: auth.Who) -> dict[str, Any]:
    """Return one policy with its plan's limits and add-ons."""
    with db.connect() as conn:
        return store.policy_view(conn, policy_id, who.tenant_id)


@router.get("/customers/{customer_id}/history", operation_id="get_customer_history")
def get_customer_history(customer_id: str, who: auth.Who) -> dict[str, Any]:
    """Return the customer's name and earlier claims."""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT data FROM customers WHERE customer_id = ? AND tenant_id = ?",
            (customer_id, who.tenant_id),
        ).fetchone()
    if row is None:
        raise HTTPException(404, f"There is no customer {customer_id}.")
    customer = json.loads(row["data"])
    return {
        "customer_id": customer_id,
        "name": store.short_name(customer["name"]) if who.agent else customer["name"],
        "customer_since": customer["customer_since"],
        "previous_claims": customer["previous_claims"],
    }


@router.get("/wording", operation_id="get_policy_wording")
def get_policy_wording(who: auth.Who) -> dict[str, str]:
    """Return the policy wording text and its version."""
    with db.connect() as conn:
        company = db.reference(conn, "company", who.tenant_id)
        version = company["policy_wording_version"]
    text = (seed.data_dir() / "policy_wording.md").read_text(encoding="utf-8")
    return {"version": version, "text": text}


def instructions() -> dict[str, str]:
    """Return the instructions for running the queue and for working a claim."""
    queue = (INSTRUCTIONS / "instructions_queue.md").read_text(encoding="utf-8")
    claim = (INSTRUCTIONS / "instructions_claim.md").read_text(encoding="utf-8")
    digest = hashlib.sha256((queue + claim).encode()).hexdigest()
    return {"queue": queue, "claim": claim, "fingerprint": digest[:12]}


@router.get("/instructions", operation_id="get_instructions")
def get_instructions() -> dict[str, str]:
    """Return the agent's instructions for the queue and for a claim."""
    return instructions()


@router.get("/handlers", operation_id="list_handlers")
def list_handlers(who: auth.Who) -> list[dict[str, Any]]:
    """List the handlers and whether they can sign off."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM handlers WHERE tenant_id = ? ORDER BY handler_id",
            (who.tenant_id,),
        ).fetchall()
    return [
        {
            "handler_id": r["handler_id"],
            "name": r["name"],
            "role": r["role"],
            "can_approve_over_limit": bool(r["can_approve_over_limit"]),
        }
        for r in rows
    ]
