"""Runs the UnderCover Agent on one claim. Tests replace execute."""

import os
from collections.abc import Callable
from typing import Any

from agent import main
from agent.stub import ScriptedModel
from backend import db


def execute(
    claim_id: str, run_id: str, on_step: Callable[[dict[str, Any]], None]
) -> None:
    """Run the agent, with the scripted model when AGENT_STUB=1."""
    llm = ScriptedModel() if os.getenv("AGENT_STUB") == "1" else None
    with db.connect() as conn:
        seconds = db.reference(conn, "company")["agent_run_timeout_seconds"]
    main.run(claim_id, run_id, llm, on_step, seconds)
