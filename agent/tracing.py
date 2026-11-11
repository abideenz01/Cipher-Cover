"""Traces of the agent's work in Langfuse, when its keys are set.

Each claim's work goes in one Langfuse session, named after the claim and its
thread, so a claim that waits for a sign-off or carries on after a restart keeps
one session. Langfuse sees what the model sees and no more: the backend already
withholds medical records from agents unless the tenant allows them, and never
returns contact details. The mask is a second line for email addresses.
"""

import os
import re
from functools import cache
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langfuse import Langfuse
from langfuse.langchain import CallbackHandler

KEYS = ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def enabled() -> bool:
    """Say whether all three Langfuse settings are present."""
    return all(os.getenv(key) for key in KEYS)


def mask(*, data: Any, **_: Any) -> Any:
    """Replace email addresses anywhere in what is sent to Langfuse."""
    if isinstance(data, str):
        return EMAIL.sub("[email]", data)
    if isinstance(data, dict):
        return {k: mask(data=v) for k, v in data.items()}
    if isinstance(data, list | tuple):
        return [mask(data=v) for v in data]
    return data


@cache
def client() -> Langfuse:
    """Return the Langfuse client, made once with the mask."""
    return Langfuse(
        public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
        secret_key=os.environ["LANGFUSE_SECRET_KEY"],
        base_url=os.environ["LANGFUSE_BASE_URL"],
        mask=mask,
    )


def session(claim_id: str, thread_id: str) -> str:
    """Return the Langfuse session of one claim's work."""
    return f"{claim_id}:{thread_id}"


def callbacks() -> list[BaseCallbackHandler]:
    """Return a handler that starts a new Langfuse trace, or none without keys."""
    if not enabled():
        return []
    langfuse = client()
    return [CallbackHandler(trace_context={"trace_id": langfuse.create_trace_id()})]


def config(session_id: str, name: str) -> dict[str, Any]:
    """Return the callbacks and metadata that put a run in its Langfuse session."""
    return {
        "callbacks": callbacks(),
        "run_name": name,
        "metadata": {"langfuse_session_id": session_id},
    }


def flush() -> None:
    """Send what is buffered, before a process that traced ends."""
    if enabled():
        client().flush()
