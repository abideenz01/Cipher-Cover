"""Runs the UnderCover Agent. Tests replace execute and execute_queue."""

import os
from collections.abc import Callable
from typing import Any

from agent import main, queue
from agent.stub import QueueScript, ScriptedModel
from backend import db


def execute(
    claim_id: str, run_id: str, on_step: Callable[[dict[str, Any]], None]
) -> None:
    """Run the agent, with the scripted model when AGENT_STUB=1."""
    llm = ScriptedModel() if os.getenv("AGENT_STUB") == "1" else None
    with db.connect() as conn:
        seconds = db.reference(conn, "company")["agent_run_timeout_seconds"]
    main.run(claim_id, run_id, llm, on_step, seconds)


def execute_queue(run_id: str, on_step: Callable[[str, dict[str, Any]], None]) -> None:
    """Run the queue agent, with the scripted models when AGENT_STUB=1."""
    if os.getenv("AGENT_STUB") == "1":
        queue.run_queue(run_id, QueueScript(), ScriptedModel(), on_step)
    else:
        queue.run_queue(run_id, None, None, on_step)
