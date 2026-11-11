"""Agent runs on claims and their trace."""

import json
import threading
import uuid
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException

from agent import main
from backend import auth, clock, db, runner, store

router = APIRouter(prefix="/api")


def spawn(work: Callable[[], None]) -> None:
    """Do work in a background thread. Tests replace this to run it inline."""
    threading.Thread(target=work, daemon=True).start()


def lease(conn: db.Connection, claim_id: str, queue_run_id: str, tenant_id: str) -> str:
    """Move a waiting claim to in progress under a new claim run, or raise 409.

    The claim is taken in one conditional update, so two callers can never both
    take it.
    """
    store.claim_row(conn, claim_id, tenant_id)
    taken = conn.execute(
        "UPDATE claims SET state = 'in_progress', state_since = ?"
        " WHERE claim_id = ? AND tenant_id = ? AND state = 'waiting'",
        (clock.stamp(), claim_id, tenant_id),
    ).rowcount
    if not taken:
        raise HTTPException(409, f"Claim {claim_id} is not waiting.")
    attempt = conn.execute(
        "SELECT COUNT(*) FROM runs WHERE claim_id = ?", (claim_id,)
    ).fetchone()[0]
    run_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO runs (run_id, claim_id, status, error, started_at, ended_at,"
        " queue_run_id, attempt, failure, tokens, model_calls, model, tenant_id, seq)"
        " VALUES (?, ?, 'running', '', ?, '', ?, ?, '', 0, 0, '', ?,"
        " (SELECT COALESCE(MAX(seq), 0) + 1 FROM runs))",
        (run_id, claim_id, clock.stamp(), queue_run_id, attempt + 1, tenant_id),
    )
    return run_id


def begin(claim_id: str, tenant_id: str) -> str:
    """Create a claim run on its own and move its claim to in progress."""
    with db.connect() as conn:
        return lease(conn, claim_id, "", tenant_id)


def claim_token(conn: db.Connection, run_id: str) -> str:
    """Issue the token a claim agent works its run with, bound to its claim."""
    run = conn.execute(
        "SELECT claim_id, tenant_id FROM runs WHERE run_id = ?", (run_id,)
    ).fetchone()
    company = db.reference(conn, "company", run["tenant_id"])
    seconds = company["agent_run_timeout_seconds"] + 60
    return auth.issue(
        conn,
        run["tenant_id"],
        "claim",
        seconds,
        run_id=run_id,
        claim_id=run["claim_id"],
    )


def tenant_of(conn: db.Connection, run_id: str) -> str:
    """Return the tenant of a claim run or a queue run."""
    row = conn.execute(
        "SELECT tenant_id FROM runs WHERE run_id = ?"
        " UNION ALL SELECT tenant_id FROM queue_runs WHERE run_id = ?",
        (run_id, run_id),
    ).fetchone()
    return row["tenant_id"] if row else ""


def record(run_id: str, step: dict[str, Any]) -> None:
    """Store one step of a trace, or add a model call's usage to its run.

    The run is a claim run or a queue run; both keep their steps in run_events.
    """
    with db.connect() as conn:
        if step["kind"] == "usage":
            for table in ("runs", "queue_runs"):
                conn.execute(
                    f"UPDATE {table} SET tokens = tokens + ?,"  # noqa: S608 - fixed names
                    " model_calls = model_calls + 1 WHERE run_id = ?",
                    (step["detail"]["tokens"], run_id),
                )
            conn.execute(
                "UPDATE runs SET model = ? WHERE run_id = ?", (step["name"], run_id)
            )
            return
        conn.execute(
            "INSERT INTO run_events (run_id, kind, name, detail, created_at,"
            " tenant_id) VALUES (?, ?, ?, ?, ?, ?)",
            (
                run_id,
                step["kind"],
                step["name"],
                json.dumps(step["detail"]),
                clock.stamp(),
                tenant_of(conn, run_id),
            ),
        )


def waiting(conn: db.Connection, run_id: str, claim: db.Row) -> bool:
    """Say whether this run approved the claim and waits for its sign-off."""
    if claim["state"] != "waiting_for_signoff":
        return False
    latest = store.latest_decision(conn, claim["claim_id"])
    return latest is not None and latest["run_id"] == run_id


def finish(run_id: str, claim_id: str, error: str, failure: str = "error") -> None:
    """End a run. A run that left its claim undecided has failed.

    A run whose claim waits for a sign-off is paused: it carries on, on the same
    thread, once a handler signs off.
    """
    with db.connect() as conn:
        auth.revoke(conn, run_id)
        tenant_id = tenant_of(conn, run_id)
        claim = store.claim_row(conn, claim_id, tenant_id)
        undecided = claim["state"] == "in_progress"
        status = "paused" if waiting(conn, run_id, claim) else "succeeded"
        if not error and undecided:
            error = "The agent finished without recording a decision."
        if undecided:
            store.set_state(conn, claim_id, "waiting")
            conn.execute(
                "UPDATE claims SET failed_attempts = failed_attempts + 1"
                " WHERE claim_id = ?",
                (claim_id,),
            )
        conn.execute(
            "UPDATE runs SET status = ?, error = ?, failure = ?, ended_at = ?"
            " WHERE run_id = ?",
            (
                "failed" if error else status,
                error,
                failure if error else "",
                clock.stamp(),
                run_id,
            ),
        )


def attempt(run_id: str, claim_id: str, go: Callable[[str], None]) -> None:
    """Work a run under a new token and record how it ended."""
    with db.connect() as conn:
        token = claim_token(conn, run_id)
    try:
        go(token)
    except Exception as error:  # noqa: BLE001 - a failed run must free its claim
        finish(run_id, claim_id, main.describe(error), main.failure(error))
        return
    finish(run_id, claim_id, "")


def work(run_id: str, claim_id: str) -> None:
    """Run the agent on a new run and record how the run ended."""

    def go(token: str) -> None:
        runner.execute(claim_id, run_id, lambda step: record(run_id, step), token)

    attempt(run_id, claim_id, go)


def reopen(run_id: str) -> str:
    """Take a paused or interrupted run back to running and return its claim.

    The run is taken in one conditional update, so it can't be resumed twice
    at once. Returns '' when it is not paused or interrupted.
    """
    with db.connect() as conn:
        taken = conn.execute(
            "UPDATE runs SET status = 'running', ended_at = ''"
            " WHERE run_id = ? AND status IN ('paused', 'interrupted')",
            (run_id,),
        ).rowcount
        if not taken:
            return ""
        return conn.execute(
            "SELECT claim_id FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()[0]


def resume(run_id: str, signoff: dict[str, Any] | None) -> None:
    """Carry a run on, on its own thread, with no new attempt.

    With a sign-off it pays the claim it was waiting on; without, it goes on
    from where it was stopped.
    """
    claim_id = reopen(run_id)
    if not claim_id:
        return

    def go(token: str) -> None:
        on_step = lambda step: record(run_id, step)  # noqa: E731 - one line
        runner.resume(claim_id, run_id, signoff, on_step, token)

    attempt(run_id, claim_id, go)


def resume_interrupted(tenant_id: str) -> list[str]:
    """Carry on every run of a tenant that a restart stopped, oldest first."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT run_id FROM runs WHERE status = 'interrupted' AND tenant_id = ?"
            " ORDER BY seq",
            (tenant_id,),
        ).fetchall()
    for row in rows:
        resume(row["run_id"], None)
    return [r["run_id"] for r in rows]


def run_view(conn: Any, run_id: str, tenant_id: str) -> dict[str, Any]:
    """Return one of the tenant's runs, or raise 404."""
    row = conn.execute(
        "SELECT * FROM runs WHERE run_id = ? AND tenant_id = ?", (run_id, tenant_id)
    ).fetchone()
    if row is None:
        raise HTTPException(404, f"There is no run {run_id}.")
    return store.run_view(conn, row)


@router.post("/claims/{claim_id}/runs", operation_id="start_run")
def start_run(claim_id: str, who: auth.Who) -> dict[str, Any]:
    """Start the agent on one claim."""
    run_id = begin(claim_id, who.tenant_id)
    spawn(lambda: work(run_id, claim_id))
    return {"run_id": run_id, "claim_id": claim_id, "status": "running"}


@router.get("/runs/{run_id}", operation_id="get_run")
def get_run(run_id: str, who: auth.Who) -> dict[str, Any]:
    """Return a run's status and outcome."""
    with db.connect() as conn:
        return run_view(conn, run_id, who.tenant_id)


def events(run_id: str) -> list[dict[str, Any]]:
    """Return a run's stored steps in order."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM run_events WHERE run_id = ? ORDER BY id", (run_id,)
        ).fetchall()
    return [
        {
            "kind": r["kind"],
            "name": r["name"],
            "detail": json.loads(r["detail"]),
            "created_at": r["created_at"],
        }
        for r in rows
    ]


@router.get("/runs/{run_id}/events", operation_id="list_run_events")
def list_run_events(run_id: str, who: auth.Who) -> list[dict[str, Any]]:
    """Return the run's trace so far."""
    with db.connect() as conn:
        run_view(conn, run_id, who.tenant_id)
    return events(run_id)
