"""Queries shared by the routes."""

import json
from datetime import datetime
from typing import Any

from fastapi import HTTPException

from backend import clock, db, sections

FAILURES_FOR_HANDLER = 2


def short_name(name: str) -> str:
    """Return a first name and last initial, such as Tom B."""
    first, *rest = name.split()
    return f"{first} {rest[-1][0]}." if rest else first


def claim_row(conn: db.Connection, claim_id: str, tenant_id: str) -> db.Row:
    """Return one of the tenant's claims, or raise 404, as for one that is not there."""
    row = conn.execute(
        "SELECT * FROM claims WHERE claim_id = ? AND tenant_id = ?",
        (claim_id, tenant_id),
    ).fetchone()
    if row is None:
        raise HTTPException(404, f"There is no claim {claim_id}.")
    return row


def policy_data(conn: db.Connection, policy_id: str, tenant_id: str) -> dict[str, Any]:
    """Return one of the tenant's policies, or raise 404."""
    row = conn.execute(
        "SELECT data FROM policies WHERE policy_id = ? AND tenant_id = ?",
        (policy_id, tenant_id),
    ).fetchone()
    if row is None:
        raise HTTPException(404, f"There is no policy {policy_id}.")
    return json.loads(row["data"])


def handler_row(conn: db.Connection, handler_id: str, tenant_id: str) -> db.Row:
    """Return one of the tenant's handlers, or raise 404."""
    row = conn.execute(
        "SELECT * FROM handlers WHERE handler_id = ? AND tenant_id = ?",
        (handler_id, tenant_id),
    ).fetchone()
    if row is None:
        raise HTTPException(404, f"There is no handler {handler_id}.")
    return row


def customer_name(conn: db.Connection, customer_id: str, tenant_id: str) -> str:
    """Return one of the tenant's customers' full name."""
    return conn.execute(
        "SELECT name FROM customers WHERE customer_id = ? AND tenant_id = ?",
        (customer_id, tenant_id),
    ).fetchone()["name"]


def set_state(conn: db.Connection, claim_id: str, state: str) -> None:
    """Move a claim to a new state."""
    conn.execute(
        "UPDATE claims SET state = ?, state_since = ? WHERE claim_id = ?",
        (state, clock.stamp(), claim_id),
    )


def decision_view(row: db.Row) -> dict[str, Any]:
    """Return a decision row for the API."""
    return {
        "decision": row["decision"],
        "payout": db.dollars(row["payout_cents"]),
        "reason": row["reason"],
        "section": row["section"],
        "sections": [
            {"id": s, "title": sections.title(s)} for s in json.loads(row["sections"])
        ],
        "run_id": row["run_id"],
        "steps": json.loads(row["steps"]),
        "model": row["model"],
        "wording_version": row["wording_version"],
        "created_at": row["created_at"],
    }


def latest_decision(conn: db.Connection, claim_id: str) -> db.Row | None:
    """Return a claim's latest decision row, if any."""
    return conn.execute(
        "SELECT * FROM decisions WHERE claim_id = ? ORDER BY id DESC LIMIT 1",
        (claim_id,),
    ).fetchone()


def paid_cents(conn: db.Connection, claim_id: str) -> int:
    """Return the total paid on a claim, in cents."""
    return conn.execute(
        "SELECT COALESCE(SUM(amount_cents), 0) FROM payments WHERE claim_id = ?",
        (claim_id,),
    ).fetchone()[0]


def policy_view(conn: db.Connection, policy_id: str, tenant_id: str) -> dict[str, Any]:
    """Return a policy with its plan's limits and add-ons."""
    policy = policy_data(conn, policy_id, tenant_id)
    plans = db.reference(conn, "plans", tenant_id)
    plan = next(p for p in plans["plans"] if p["plan"] == policy["plan"])
    add_ons = [a for a in plans["add_ons"] if a["add_on"] in policy["add_ons"]]
    return policy | {
        "limits": plan,
        "add_on_details": add_ons,
        "deductible_applies_to": plans["deductible_applies_to"],
    }


def decided(conn: db.Connection, claim_id: str) -> db.Row:
    """Return a claim's latest decision, or raise 409 if it has none."""
    row = latest_decision(conn, claim_id)
    if row is None:
        raise HTTPException(409, f"Claim {claim_id} has no decision.")
    return row


def live_run(conn: db.Connection, run_id: str, tenant_id: str) -> db.Row:
    """Return one of the tenant's claim runs that is still running, or raise 409."""
    row = conn.execute(
        "SELECT * FROM runs WHERE run_id = ? AND tenant_id = ?", (run_id, tenant_id)
    ).fetchone()
    if row is None or row["status"] != "running":
        raise HTTPException(409, f"There is no live claim run {run_id}.")
    return row


def read_sections(conn: db.Connection, run_id: str) -> list[str]:
    """Return the sections a run has read, in order, without repeats."""
    rows = conn.execute(
        "SELECT section_id FROM section_reads WHERE run_id = ? ORDER BY id", (run_id,)
    ).fetchall()
    return list(dict.fromkeys(r["section_id"] for r in rows))


def run_view(
    conn: db.Connection, row: db.Row, read: list[str] | None = None
) -> dict[str, Any]:
    """Return a claim run with the sections it read and how long it took.

    `read` is the run's sections when the caller has already looked them up.
    """
    ended = row["ended_at"] or clock.stamp()
    seconds = (
        datetime.fromisoformat(ended) - datetime.fromisoformat(row["started_at"])
    ).total_seconds()
    if read is None:
        read = read_sections(conn, row["run_id"])
    return dict(row) | {
        "seconds": round(seconds),
        "sections_read": [{"id": s, "title": sections.title(s)} for s in read],
    }


def sections_by_run(conn: db.Connection, claim_id: str) -> dict[str, list[str]]:
    """Return the sections each of a claim's runs read, in order, without repeats."""
    rows = conn.execute(
        "SELECT r.run_id, s.section_id FROM section_reads s"
        " JOIN runs r ON r.run_id = s.run_id WHERE r.claim_id = ? ORDER BY s.id",
        (claim_id,),
    ).fetchall()
    found: dict[str, dict[str, None]] = {}
    for r in rows:
        found.setdefault(r["run_id"], {})[r["section_id"]] = None
    return {run_id: list(ids) for run_id, ids in found.items()}
