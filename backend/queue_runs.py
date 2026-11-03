"""Queue runs: one run of the queue agent over many claims.

The backend enforces the run's rules, so the agent learns them from a 409 it can
read: the cap, the token budget, one lease per claim, Stop, the pause after
provider errors and the check for missed claims.
"""

import json
import os
import sqlite3
import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agent import main
from backend import auth, claims, clock, db, runner, runs, store

router = APIRouter(prefix="/api")
LIVE = ("running", "stopping", "paused")
HISTORY = 20
QUEUE_TOKEN_SECONDS = 24 * 3600

TodoStatus = Literal["to_do", "in_progress", "done", "left_for_handler", "not_started"]


class QueueRunStart(BaseModel):
    """The most claims a run may take, or 0 for every waiting claim."""

    cap: int


class Attempt(BaseModel):
    """A claim for the run to take."""

    claim_id: str


class AttemptEnd(BaseModel):
    """How a claim run ended: an error message and its kind, or two empty strings."""

    error: str
    failure: Literal["", "provider", "step_limit", "time_limit", "error"]


class Todo(BaseModel):
    """One item on the run's to-do list."""

    claim_id: str
    status: TodoStatus
    note: str


class Todos(BaseModel):
    """The whole to-do list."""

    todos: list[Todo]


class Summary(BaseModel):
    """The run's summary for the handlers."""

    summary: str


def limits(conn: sqlite3.Connection, tenant_id: str) -> dict[str, int]:
    """Return the limits for a new run, from the environment and company settings."""
    company = db.reference(conn, "company", tenant_id)
    return {
        "claim_step_limit": main.setting("CLAIM_STEP_LIMIT", 30),
        "claim_seconds": company["agent_run_timeout_seconds"],
        "token_limit": main.setting("RUN_TOKEN_LIMIT", 1_000_000),
        "provider_failures_to_pause": main.setting("PROVIDER_FAILURES_TO_PAUSE", 3),
    }


def queue_row(conn: sqlite3.Connection, run_id: str, tenant_id: str) -> sqlite3.Row:
    """Return one of the tenant's queue runs, or raise 404."""
    row = conn.execute(
        "SELECT * FROM queue_runs WHERE run_id = ? AND tenant_id = ?",
        (run_id, tenant_id),
    ).fetchone()
    if row is None:
        raise HTTPException(404, f"There is no queue run {run_id}.")
    return row


def tokens(conn: sqlite3.Connection, row: sqlite3.Row) -> int:
    """Return the tokens a queue run has used, its own and its claim runs'."""
    claims_used = conn.execute(
        "SELECT COALESCE(SUM(tokens), 0) FROM runs WHERE queue_run_id = ?",
        (row["run_id"],),
    ).fetchone()[0]
    return row["tokens"] + claims_used


def taken(conn: sqlite3.Connection, run_id: str) -> list[str]:
    """Return the distinct claims a queue run has taken, in order."""
    rows = conn.execute(
        "SELECT claim_id FROM runs WHERE queue_run_id = ? ORDER BY started_at, rowid",
        (run_id,),
    ).fetchall()
    return list(dict.fromkeys(r["claim_id"] for r in rows))


def eligible(conn: sqlite3.Connection, tenant_id: str) -> list[str]:
    """Return the tenant's waiting claims a queue run may take, in id order."""
    rows = conn.execute(
        "SELECT claim_id FROM claims WHERE state = 'waiting' AND failed_attempts < ?"
        " AND tenant_id = ? ORDER BY claim_id",
        (store.FAILURES_FOR_HANDLER, tenant_id),
    ).fetchall()
    return [r["claim_id"] for r in rows]


def budget_spent(conn: sqlite3.Connection, row: sqlite3.Row) -> bool:
    """Return whether the run has used its token budget."""
    return tokens(conn, row) >= json.loads(row["limits"])["token_limit"]


def missed(conn: sqlite3.Connection, row: sqlite3.Row) -> list[str]:
    """Return the waiting claims still within the cap that the run has not decided."""
    worked = taken(conn, row["run_id"])
    room = row["cap"] == 0 or len(worked) < row["cap"]
    return [c for c in eligible(conn, row["tenant_id"]) if room or c in worked]


def view(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    """Return a queue run for the API."""
    ended = row["ended_at"] or clock.stamp()
    seconds = datetime.fromisoformat(ended) - datetime.fromisoformat(row["started_at"])
    attempts = conn.execute(
        "SELECT run_id, claim_id, attempt, status, failure, tokens FROM runs"
        " WHERE queue_run_id = ? ORDER BY started_at, rowid",
        (row["run_id"],),
    ).fetchall()
    return dict(row) | {
        "limits": json.loads(row["limits"]),
        "todos": json.loads(row["todos"]),
        "tokens": tokens(conn, row),
        "agent_tokens": row["tokens"],
        "seconds": round(seconds.total_seconds()),
        "claims_worked": len({a["claim_id"] for a in attempts}),
        "attempts": [dict(a) for a in attempts],
    }


def finished_todos(row: sqlite3.Row) -> str:
    """Return the to-do list with every unfinished item marked not started."""
    todos = json.loads(row["todos"])
    for todo in todos:
        if todo["status"] in ("to_do", "in_progress"):
            todo["status"] = "not_started"
    return json.dumps(todos)


def end(
    conn: sqlite3.Connection, row: sqlite3.Row, status: str, reason: str, error: str
) -> None:
    """End a queue run."""
    conn.execute(
        "UPDATE queue_runs SET status = ?, stop_reason = ?, error = ?, todos = ?,"
        " ended_at = ? WHERE run_id = ?",
        (status, reason, error, finished_todos(row), clock.stamp(), row["run_id"]),
    )


def close(run_id: str, error: str, failure: str) -> None:
    """Close a run whose agent has returned or raised, freeing any claim it held."""
    with db.connect() as conn:
        auth.revoke(conn, run_id)
        tenant_id = runs.tenant_of(conn, run_id)
        held = conn.execute(
            "SELECT run_id, claim_id FROM runs"
            " WHERE queue_run_id = ? AND status = 'running'",
            (run_id,),
        ).fetchall()
    for claim_run in held:
        runs.finish(
            claim_run["run_id"], claim_run["claim_id"], "The queue run ended.", "error"
        )
    with db.connect() as conn:
        row = queue_row(conn, run_id, tenant_id)
        if row["status"] not in LIVE:
            return
        if failure == "provider" or row["status"] == "paused":
            end(conn, row, "paused", "provider_errors", error)
        else:
            end(
                conn,
                row,
                "failed",
                "error",
                error or "The agent ended without a summary.",
            )


def work(run_id: str) -> None:
    """Run the queue agent and close the run however it ends."""
    with db.connect() as conn:
        tenant_id = runs.tenant_of(conn, run_id)
        token = auth.issue(conn, tenant_id, "queue", QUEUE_TOKEN_SECONDS, run_id=run_id)
    try:
        runner.execute_queue(run_id, runs.record, token)
    except Exception as error:  # noqa: BLE001 - a failed run must free its claims
        close(run_id, main.describe(error), main.failure(error))
        return
    close(run_id, "", "")


def recover() -> None:
    """On startup, free what a stopped backend left: no run can still be live."""
    message = "The backend restarted."
    with db.connect() as conn:
        conn.execute(
            "UPDATE claims SET state = 'waiting', state_since = ?,"
            " failed_attempts = failed_attempts + 1 WHERE state = 'in_progress'",
            (clock.stamp(),),
        )
        conn.execute(
            "UPDATE runs SET status = 'failed', failure = 'error', error = ?,"
            " ended_at = ? WHERE status = 'running'",
            (message, clock.stamp()),
        )
        for row in conn.execute(
            "SELECT * FROM queue_runs WHERE status IN ('running', 'stopping', 'paused')"
        ).fetchall():
            end(conn, row, "failed", "error", message)
        conn.execute(
            "UPDATE service_tokens SET revoked_at = ? WHERE revoked_at = ''"
            " AND kind IN ('claim', 'queue')",
            (clock.stamp(),),
        )


def model() -> tuple[str, str]:
    """Return the model a new run will use and its reasoning effort."""
    if os.getenv("AGENT_STUB") == "1":
        return "scripted", ""
    return main.model_name(), "" if os.getenv("MODEL_NAME") else "low"


@router.post("/runs", operation_id="start_queue_run")
def start_queue_run(body: QueueRunStart, who: auth.Who) -> dict[str, Any]:
    """Start the queue agent on the waiting claims, up to the cap (0 for all)."""
    run_id = uuid.uuid4().hex
    name, effort = model()
    with db.connect() as conn:
        live = conn.execute(
            "SELECT run_id FROM queue_runs WHERE status IN ('running', 'stopping')"
            " AND tenant_id = ?",
            (who.tenant_id,),
        ).fetchone()
        if live:
            raise HTTPException(409, f"Queue run {live['run_id']} is still running.")
        conn.execute(
            "INSERT INTO queue_runs (run_id, status, cap, limits, model,"
            " reasoning_effort, fingerprint, todos, summary, stop_reason, error,"
            " tokens, model_calls, provider_failures, started_at, ended_at,"
            " tenant_id) VALUES"
            " (?, 'running', ?, ?, ?, ?, ?, '[]', '', '', '', 0, 0, 0, ?, '', ?)",
            (
                run_id,
                body.cap,
                json.dumps(limits(conn, who.tenant_id)),
                name,
                effort,
                claims.instructions()["fingerprint"],
                clock.stamp(),
                who.tenant_id,
            ),
        )
    runs.spawn(lambda: work(run_id))
    with db.connect() as conn:
        return view(conn, queue_row(conn, run_id, who.tenant_id))


@router.get("/queue-runs", operation_id="list_queue_runs")
def list_queue_runs(who: auth.Who) -> list[dict[str, Any]]:
    """List the latest queue runs, newest first."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM queue_runs WHERE tenant_id = ?"
            " ORDER BY started_at DESC, rowid DESC LIMIT ?",
            (who.tenant_id, HISTORY),
        ).fetchall()
        return [view(conn, r) for r in rows]


@router.get("/queue-runs/{run_id}", operation_id="get_queue_run")
def get_queue_run(run_id: str, who: auth.Who) -> dict[str, Any]:
    """Return a queue run's status, limits, to-do list, usage and summary."""
    with db.connect() as conn:
        return view(conn, queue_row(conn, run_id, who.tenant_id))


@router.get("/queue-runs/{run_id}/events", operation_id="list_queue_run_events")
def list_queue_run_events(run_id: str, who: auth.Who) -> list[dict[str, Any]]:
    """Return the queue agent's own steps."""
    with db.connect() as conn:
        queue_row(conn, run_id, who.tenant_id)
    return runs.events(run_id)


@router.put("/queue-runs/{run_id}/todos", operation_id="write_todos")
def write_todos(run_id: str, body: Todos, who: auth.Who) -> dict[str, Any]:
    """Replace the run's to-do list."""
    with db.connect() as conn:
        if queue_row(conn, run_id, who.tenant_id)["status"] not in LIVE:
            raise HTTPException(409, "The run has finished.")
        todos = [t.model_dump() for t in body.todos]
        conn.execute(
            "UPDATE queue_runs SET todos = ? WHERE run_id = ?",
            (json.dumps(todos), run_id),
        )
    return {"todos": todos}


NOT_RUNNING = {
    "stopping": "The run is stopping.",
    "paused": "The run is paused after provider errors.",
}


def refusal(conn: sqlite3.Connection, row: sqlite3.Row, claim_id: str) -> str:
    """Return why the run may not take this claim, or '' if it may."""
    if row["status"] != "running":
        return NOT_RUNNING.get(row["status"], "The run has finished.")
    if budget_spent(conn, row):
        return "The token budget is spent."
    claim = store.claim_row(conn, claim_id, row["tenant_id"])
    worked = taken(conn, row["run_id"])
    if claim["failed_attempts"] >= store.FAILURES_FOR_HANDLER:
        reason = f"Claim {claim_id} failed twice and is left for a handler."
    elif row["cap"] and claim_id not in worked and len(worked) >= row["cap"]:
        reason = "The cap is reached."
    else:
        reason = ""
    return reason


@router.post("/queue-runs/{run_id}/attempts", operation_id="begin_attempt")
def begin_attempt(run_id: str, body: Attempt, who: auth.Who) -> dict[str, Any]:
    """Lease a claim for a new claim run, with the token to work it, or refuse."""
    with db.connect() as conn:
        reason = refusal(conn, queue_row(conn, run_id, who.tenant_id), body.claim_id)
        if reason:
            raise HTTPException(409, reason)
        claim_run = runs.lease(conn, body.claim_id, run_id, who.tenant_id)
        token = runs.claim_token(conn, claim_run)
        return store.run_view(
            conn,
            conn.execute(
                "SELECT * FROM runs WHERE run_id = ?", (claim_run,)
            ).fetchone(),
        ) | {"token": token}


def outcome(conn: sqlite3.Connection, claim_run: sqlite3.Row) -> str:
    """Describe in one line how a claim run ended."""
    claim_id = claim_run["claim_id"]
    claim = store.claim_row(conn, claim_id, claim_run["tenant_id"])
    if claim_run["status"] == "failed" and claim["state"] == "waiting":
        if claim["failed_attempts"] >= store.FAILURES_FOR_HANDLER:
            return f"{claim_id}: failed twice, left for a handler. {claim_run['error']}"
        return f"{claim_id}: failed ({claim_run['failure']}), back in the queue."
    latest = store.latest_decision(conn, claim_id)
    if latest is None:
        return f"{claim_id}: {claim['state'].replace('_', ' ')}."
    amount = f"${db.dollars(latest['payout_cents']):,.2f}"
    if claim["state"] == "waiting_for_signoff":
        return f"{claim_id}: approve, {amount}, waiting for sign-off."
    paid = ", paid" if store.paid_cents(conn, claim_id) else ""
    return f"{claim_id}: {latest['decision']}, {amount}{paid}."


@router.post("/runs/{run_id}/finish", operation_id="finish_attempt")
def finish_attempt(run_id: str, body: AttemptEnd, who: auth.Who) -> dict[str, Any]:
    """End a claim run on a queue run and return its outcome in one line."""
    with db.connect() as conn:
        claim_run = store.live_run(conn, run_id, who.tenant_id)
    runs.finish(run_id, claim_run["claim_id"], body.error, body.failure or "error")
    with db.connect() as conn:
        claim_run = conn.execute(
            "SELECT * FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        row = queue_row(conn, claim_run["queue_run_id"], who.tenant_id)
        failures = (
            row["provider_failures"] + 1 if claim_run["failure"] == "provider" else 0
        )
        pause = failures >= json.loads(row["limits"])["provider_failures_to_pause"]
        conn.execute(
            "UPDATE queue_runs SET provider_failures = ?,"
            " status = CASE WHEN ? AND status = 'running' THEN 'paused' ELSE status END"
            " WHERE run_id = ?",
            (failures, pause, row["run_id"]),
        )
        line = outcome(conn, claim_run)
        if pause:
            line += " The run is paused after provider errors."
        return {"outcome": line, "status": claim_run["status"]}


@router.post("/queue-runs/{run_id}/finish", operation_id="finish_queue_run")
def finish_queue_run(run_id: str, body: Summary, who: auth.Who) -> dict[str, Any]:
    """Record the summary, or refuse while waiting claims within the cap remain."""
    with db.connect() as conn:
        row = queue_row(conn, run_id, who.tenant_id)
        if row["status"] not in LIVE:
            raise HTTPException(409, "The run has finished.")
        spent = budget_spent(conn, row)
        left = missed(conn, row)
        if row["status"] == "running" and not spent and left:
            raise HTTPException(
                409,
                "These waiting claims are within the cap and not decided yet: "
                + ", ".join(left[:20])
                + ".",
            )
        conn.execute(
            "UPDATE queue_runs SET summary = ? WHERE run_id = ?", (body.summary, run_id)
        )
        if row["status"] == "stopping":
            end(conn, row, "stopped", "stopped", "")
        elif row["status"] == "paused":
            end(conn, row, "paused", "provider_errors", "")
        else:
            reason = (
                "token_limit"
                if spent
                else "cap"
                if eligible(conn, who.tenant_id)
                else "queue_empty"
            )
            end(conn, row, "succeeded", reason, "")
        return view(conn, queue_row(conn, run_id, who.tenant_id))


@router.post("/queue-runs/{run_id}/stop", operation_id="stop_queue_run")
def stop_queue_run(run_id: str, who: auth.Who) -> dict[str, Any]:
    """Ask a live run to stop after the claim in hand."""
    with db.connect() as conn:
        if queue_row(conn, run_id, who.tenant_id)["status"] != "running":
            raise HTTPException(409, "The run is not running.")
        conn.execute(
            "UPDATE queue_runs SET status = 'stopping' WHERE run_id = ?", (run_id,)
        )
        return view(conn, queue_row(conn, run_id, who.tenant_id))
