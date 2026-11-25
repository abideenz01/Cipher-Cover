"""Trace steps saved in the background: in order, complete when a run ends."""

import threading
import time

from backend import db, runs, trace
from backend.tests import sessions


def events(run_id):
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT kind, name FROM run_events WHERE run_id = ? ORDER BY id", (run_id,)
        ).fetchall()
    return [tuple(r) for r in rows]


def usage(run_id):
    with db.connect() as conn:
        row = conn.execute(
            "SELECT tokens, model_calls, model FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
    return tuple(row)


def step(kind, name, tokens=0):
    detail = {"tokens": tokens} if kind == "usage" else {}
    return {"kind": kind, "name": name, "detail": detail}


def test_steps_are_saved_in_order_and_usage_is_added_up():
    run_id = runs.begin("CLM-1001", sessions.TENANT)
    runs.record(run_id, step("usage", "model-a", 100))
    for i in range(30):
        runs.record(run_id, step("tool_call", f"call-{i}"))
    runs.record(run_id, step("usage", "model-b", 50))
    trace.WRITER.flush()
    assert events(run_id) == [("tool_call", f"call-{i}") for i in range(30)]
    assert usage(run_id) == (150, 2, "model-b")


def test_the_agent_does_not_wait_for_the_database(monkeypatch):
    run_id = runs.begin("CLM-1001", sessions.TENANT)
    gate = threading.Event()
    real = trace.write

    def slow(batch):
        gate.wait(5)
        real(batch)

    monkeypatch.setattr(trace, "write", slow)
    started = time.monotonic()
    for i in range(10):
        runs.record(run_id, step("tool_call", f"call-{i}"))
    assert time.monotonic() - started < 1
    gate.set()
    trace.WRITER.flush()
    assert len(events(run_id)) == 10


def test_a_batch_that_fails_does_not_stop_the_writer(monkeypatch):
    run_id = runs.begin("CLM-1001", sessions.TENANT)
    real = trace.write
    failures = [RuntimeError("The database went away.")]

    def flaky(batch):
        if failures:
            raise failures.pop()
        real(batch)

    monkeypatch.setattr(trace, "write", flaky)
    runs.record(run_id, step("tool_call", "lost"))
    trace.WRITER.flush()
    runs.record(run_id, step("tool_call", "kept"))
    trace.WRITER.flush()
    assert events(run_id) == [("tool_call", "kept")]


def test_a_run_has_its_whole_trace_once_it_ends(monkeypatch):
    run_id = runs.begin("CLM-1001", sessions.TENANT)
    real = trace.write

    def slow(batch):
        time.sleep(0.2)
        real(batch)

    monkeypatch.setattr(trace, "write", slow)
    for i in range(5):
        runs.record(run_id, step("tool_call", f"call-{i}"))
    runs.finish(run_id, "CLM-1001", "")
    assert len(events(run_id)) == 5
