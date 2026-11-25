"""A step's reads run side by side; everything else runs alone, in order."""

import threading
import time
from contextvars import ContextVar

from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from agent import graph
from agent.stub import ScriptedModel

WHO: ContextVar[str] = ContextVar("WHO", default="")
LOG: list[tuple[str, str, float, float]] = []
LOCK = threading.Lock()


def logged(name, arg):
    started = time.monotonic()
    time.sleep(0.2)
    with LOCK:
        LOG.append((name, arg, started, time.monotonic()))
    return f"{name} {arg} as {WHO.get()}"


@tool
def read(what: str) -> str:
    """Read something."""
    return logged("read", what)


@tool
def decide(what: str) -> str:
    """Decide something."""
    return logged("decide", what)


def nodes():
    return graph.Nodes(
        ScriptedModel(),
        [read, decide],
        "",
        limit=30,
        retry=lambda invoke: invoke(),
        pay=lambda *_: {},
        reads=frozenset({"read"}),
    )


def call(name, what, i):
    return {"name": name, "args": {"what": what}, "id": f"c{i}", "type": "tool_call"}


def act(calls):
    LOG.clear()
    message = AIMessage("", tool_calls=calls)
    state = graph.ClaimState(
        messages=[message], claim_id="CLM-1", model_calls=1, decision={}, reply=""
    )
    return nodes().act(state, {})["messages"]


def test_reads_in_a_row_run_side_by_side_and_keep_their_order():
    WHO.set("run-7")
    calls = [call("read", f"section-{i}", i) for i in range(3)]
    started = time.monotonic()
    results = act(calls)
    assert time.monotonic() - started < 0.5  # three 0.2 s reads, at once
    assert [r.tool_call_id for r in results] == ["c0", "c1", "c2"]
    assert [r.content for r in results] == [
        f"read section-{i} as run-7" for i in range(3)
    ]


def test_a_decision_waits_for_the_reads_before_it_and_goes_before_the_ones_after():
    calls = [
        call("read", "a", 0),
        call("read", "b", 1),
        call("decide", "approve", 2),
        call("read", "c", 3),
    ]
    results = act(calls)
    assert [r.tool_call_id for r in results] == ["c0", "c1", "c2", "c3"]
    ended = {arg: end for _, arg, _, end in LOG}
    began = {arg: start for _, arg, start, _ in LOG}
    assert began["approve"] >= max(ended["a"], ended["b"])
    assert began["c"] >= ended["approve"]


def test_batches_split_only_runs_of_reads():
    calls = [
        call("read", "a", 0),
        call("decide", "x", 1),
        call("decide", "y", 2),
        call("read", "b", 3),
        call("read", "c", 4),
    ]
    assert [
        [c["id"] for c in b] for b in graph.batches(calls, frozenset({"read"}))
    ] == [
        ["c0"],
        ["c1"],
        ["c2"],
        ["c3", "c4"],
    ]
