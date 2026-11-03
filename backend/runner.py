"""Runs the UnderCover Agent. Tests replace execute and execute_queue."""

import os
from collections.abc import Callable
from typing import Any

from agent import main, queue
from agent.stub import QueueScript, ScriptedModel
from backend import db


def execute(
    claim_id: str, run_id: str, on_step: Callable[[dict[str, Any]], None], token: str
) -> None:
    """Run the agent under its run's token, with the scripted model if AGENT_STUB=1."""
    llm = ScriptedModel() if os.getenv("AGENT_STUB") == "1" else None
    with db.connect() as conn:
        tenant_id = conn.execute(
            "SELECT tenant_id FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()["tenant_id"]
        company = db.reference(conn, "company", tenant_id)
        seconds = company["agent_run_timeout_seconds"]
    with main.acting(token):
        main.run(claim_id, run_id, llm, on_step, seconds)


def execute_queue(
    run_id: str, on_step: Callable[[str, dict[str, Any]], None], token: str
) -> None:
    """Run the queue agent under its token, with scripted models if AGENT_STUB=1."""
    if os.getenv("AGENT_STUB") == "1":
        queue.run_queue(run_id, QueueScript(), ScriptedModel(), on_step, token=token)
    else:
        queue.run_queue(run_id, None, None, on_step, token=token)
