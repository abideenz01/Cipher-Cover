"""Agent runs on claims and their trace."""

import json
import threading
import uuid
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException

from agent import main
from backend import clock, db, runner, store

router = APIRouter(prefix="/api")


def spawn(work: Callable[[], None]) -> None:
    """Do work in a background thread. Tests replace this to run it inline."""
    threading.Thread(target=work, daemon=True).start()


def begin(claim_id: str) -> str:
    """Create a run and move its claim to in progress."""
    run_id = uuid.uuid4().hex
    with db.connect() as conn:
        claim = store.claim_row(conn, claim_id)
        if claim["state"] != "waiting":
            raise HTTPException(409, f"Claim {claim_id} is not waiting.")
        conn.execute(
            "INSERT INTO runs (run_id, claim_id, status, error, started_at, ended_at,"
            " queue_run_id, attempt, failure, tokens, model_calls, model)"
            " VALUES (?, ?, 'running', '', ?, '', '', 1, '', 0, 0, '')",
            (run_id, claim_id, clock.stamp()),
        )
        store.set_state(conn, claim_id, "in_progress")
    return run_id


def record(run_id: str, step: dict[str, Any]) -> None:
    """Store one step of a run's trace, or add a model call's usage to the run."""
    with db.connect() as conn:
        if step["kind"] == "usage":
            conn.execute(
                "UPDATE runs SET tokens = tokens + ?, model_calls = model_calls + 1,"
                " model = ? WHERE run_id = ?",
                (step["detail"]["tokens"], step["name"], run_id),
            )
            return
        conn.execute(
            "INSERT INTO run_events (run_id, kind, name, detail, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                run_id,
                step["kind"],
                step["name"],
                json.dumps(step["detail"]),
                clock.stamp(),
            ),
        )


def finish(run_id: str, claim_id: str, error: str, failure: str = "error") -> None:
    """End a run. A run that left its claim undecided has failed."""
    with db.connect() as conn:
        undecided = store.claim_row(conn, claim_id)["state"] == "in_progress"
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
                "failed" if error else "succeeded",
                error,
                failure if error else "",
                clock.stamp(),
                run_id,
            ),
        )


def work(run_id: str, claim_id: str) -> None:
    """Run the agent and record how the run ended."""
    try:
        runner.execute(claim_id, run_id, lambda step: record(run_id, step))
    except Exception as error:  # noqa: BLE001 - a failed run must free its claim
        finish(run_id, claim_id, main.describe(error), main.failure(error))
        return
    finish(run_id, claim_id, "")


def run_view(conn: Any, run_id: str) -> dict[str, Any]:
    """Return one run, or raise 404."""
    row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        raise HTTPException(404, f"There is no run {run_id}.")
    return store.run_view(conn, row)


@router.post("/claims/{claim_id}/runs", operation_id="start_run")
def start_run(claim_id: str) -> dict[str, Any]:
    """Start the agent on one claim."""
    run_id = begin(claim_id)
    spawn(lambda: work(run_id, claim_id))
    return {"run_id": run_id, "claim_id": claim_id, "status": "running"}


@router.post("/runs", operation_id="start_queue_run")
def start_queue_run() -> dict[str, list[str]]:
    """Start the agent on every waiting claim, one at a time."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT claim_id FROM claims WHERE state = 'waiting' ORDER BY claim_id"
        ).fetchall()
    claim_ids = [r["claim_id"] for r in rows]

    def work_queue() -> None:
        for claim_id in claim_ids:
            with db.connect() as conn:
                if store.claim_row(conn, claim_id)["state"] != "waiting":
                    continue
            work(begin(claim_id), claim_id)

    spawn(work_queue)
    return {"claim_ids": claim_ids}


@router.get("/runs/{run_id}", operation_id="get_run")
def get_run(run_id: str) -> dict[str, Any]:
    """Return a run's status and outcome."""
    with db.connect() as conn:
        return run_view(conn, run_id)


@router.get("/runs/{run_id}/events", operation_id="list_run_events")
def list_run_events(run_id: str) -> list[dict[str, Any]]:
    """Return the run's trace so far."""
    with db.connect() as conn:
        run_view(conn, run_id)
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
