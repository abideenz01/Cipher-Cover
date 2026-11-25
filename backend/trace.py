"""Trace steps, saved in the background so an agent never waits on them.

Against a remote database each write costs round trips, and a claim has dozens
of steps. The agent hands a step over and goes on; one writer saves steps in
order, a batch to a transaction. Whatever reads a whole run (its end, a token
budget) calls flush() first. Steps not yet saved when the process dies are
lost from the trace; decisions and payments never pass through here.
"""

import json
import logging
import queue
import threading
from collections import defaultdict
from typing import Any

from backend import clock, db

log = logging.getLogger(__name__)
BATCH = 100
FLUSH_SECONDS = 60


class Writer:
    """Save queued steps on one thread, in the order they were queued."""

    def __init__(self) -> None:
        self.steps: queue.Queue[tuple[str, dict[str, Any], str]] = queue.Queue()
        self.done = threading.Condition()
        self.outstanding = 0
        self.thread: threading.Thread | None = None

    def put(self, run_id: str, step: dict[str, Any]) -> None:
        """Queue one step, stamped now."""
        with self.done:
            self.outstanding += 1
            if self.thread is None or not self.thread.is_alive():
                self.thread = threading.Thread(target=self.loop, daemon=True)
                self.thread.start()
        self.steps.put((run_id, step, clock.stamp()))

    def loop(self) -> None:
        while True:
            batch = [self.steps.get()]
            while len(batch) < BATCH:
                try:
                    batch.append(self.steps.get_nowait())
                except queue.Empty:
                    break
            try:
                write(batch)
            except Exception:  # A lost trace step must not stop the writer.
                log.exception("Could not save %d trace steps.", len(batch))
            with self.done:
                self.outstanding -= len(batch)
                self.done.notify_all()

    def flush(self) -> None:
        """Wait until every queued step is saved."""
        with self.done:
            self.done.wait_for(lambda: self.outstanding == 0, FLUSH_SECONDS)


def write(batch: list[tuple[str, dict[str, Any], str]]) -> None:
    """Save a batch of steps in one transaction: usage added up per run."""
    tokens: dict[str, int] = defaultdict(int)
    calls: dict[str, int] = defaultdict(int)
    models: dict[str, str] = {}
    events = []
    with db.connect() as conn:
        tenants = {
            run_id: tenant_of(conn, run_id) for run_id in {r for r, _, _ in batch}
        }
        for run_id, step, stamp in batch:
            if step["kind"] == "usage":
                tokens[run_id] += step["detail"]["tokens"]
                calls[run_id] += 1
                models[run_id] = step["name"]
                continue
            events.append(
                (
                    run_id,
                    step["kind"],
                    step["name"],
                    json.dumps(step["detail"]),
                    stamp,
                    tenants[run_id],
                )
            )
        if events:
            conn.executemany(
                "INSERT INTO run_events (run_id, kind, name, detail, created_at,"
                " tenant_id) VALUES (?, ?, ?, ?, ?, ?)",
                events,
            )
        for run_id, model in models.items():
            for table in ("runs", "queue_runs"):
                conn.execute(
                    f"UPDATE {table} SET tokens = tokens + ?,"  # noqa: S608 - fixed names
                    " model_calls = model_calls + ? WHERE run_id = ?",
                    (tokens[run_id], calls[run_id], run_id),
                )
            conn.execute("UPDATE runs SET model = ? WHERE run_id = ?", (model, run_id))


def tenant_of(conn: db.Connection, run_id: str) -> str:
    """Return the tenant of a claim run or a queue run."""
    row = conn.execute(
        "SELECT tenant_id FROM runs WHERE run_id = ?"
        " UNION ALL SELECT tenant_id FROM queue_runs WHERE run_id = ?",
        (run_id, run_id),
    ).fetchone()
    return row["tenant_id"] if row else ""


WRITER = Writer()
