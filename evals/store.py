"""Evaluation runs and their per-claim results, in a database of their own.

Kept apart from the backend's database, so no answer key or score ever sits
where the API or an agent could read it. EVAL_DB_PATH, or evals.db.
"""

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS eval_runs (
    eval_run_id TEXT PRIMARY KEY, dataset TEXT NOT NULL, version TEXT NOT NULL,
    sha256 TEXT NOT NULL, provenance TEXT NOT NULL, model TEXT NOT NULL,
    fingerprint TEXT NOT NULL, medical INTEGER NOT NULL, tiny INTEGER NOT NULL,
    n INTEGER NOT NULL, started_at TEXT NOT NULL, ended_at TEXT NOT NULL,
    scores TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS eval_results (
    eval_run_id TEXT NOT NULL, claim_id TEXT NOT NULL,
    expected_decision TEXT NOT NULL, actual_decision TEXT NOT NULL,
    expected_cents INTEGER NOT NULL, actual_cents INTEGER NOT NULL,
    expected_sections TEXT NOT NULL, cited_sections TEXT NOT NULL,
    status TEXT NOT NULL, failure TEXT NOT NULL, tokens INTEGER NOT NULL,
    seconds REAL NOT NULL, PRIMARY KEY (eval_run_id, claim_id));
"""


def path() -> str:
    """Return the evaluation database file."""
    return os.getenv("EVAL_DB_PATH") or "evals.db"


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Open the evaluation database, creating its tables, and commit on success."""
    conn = sqlite3.connect(path())
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def save(
    meta: dict[str, Any], rows: list[dict[str, Any]], scores: dict[str, Any]
) -> None:
    """Store one evaluation run with its per-claim results."""
    with connect() as conn:
        conn.execute(
            "INSERT INTO eval_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                meta["eval_run_id"],
                meta["dataset"],
                meta["version"],
                meta["sha256"],
                meta["provenance"],
                meta["model"],
                meta["fingerprint"],
                int(meta["medical"]),
                int(meta["tiny"]),
                scores["n"],
                meta["started_at"],
                meta["ended_at"],
                json.dumps(scores),
            ),
        )
        conn.executemany(
            "INSERT INTO eval_results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    meta["eval_run_id"],
                    r["claim_id"],
                    r["expected_decision"],
                    r["decision"],
                    r["expected_cents"],
                    r["payout_cents"],
                    json.dumps(r["expected_sections"]),
                    json.dumps(r["sections"]),
                    r["status"],
                    r["failure"],
                    r["tokens"],
                    r["seconds"],
                )
                for r in rows
            ],
        )


def run(eval_run_id: str) -> dict[str, Any]:
    """Return one stored evaluation run with its scores, or raise KeyError."""
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM eval_runs WHERE eval_run_id = ?", (eval_run_id,)
        ).fetchone()
    if row is None:
        raise KeyError(f"There is no evaluation run {eval_run_id}.")
    return dict(row) | {"scores": json.loads(row["scores"])}
