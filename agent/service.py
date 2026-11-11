"""The agent's service: the agent's entry point beside the backend and the dashboard.

It carries claims on: claims a handler signed off while their claim agent
waited, and claims a stopped process left partway. The backend calls /resume
once a sign-off is saved, and the service does the same when it starts, so a
claim signed off while it was away is picked up the next time it runs.

Both directions use AGENT_SERVICE_KEY. The service asks the backend for the
runs that are due; the backend hands each over with that run's own token, and
the service works the claim, reports each step and ends the run under it. The
service holds no connection to the database except the claim agent's
checkpointer.
"""

import hmac
import logging
import os
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

import httpx
from fastapi import FastAPI, Header, HTTPException

from agent import main, tracing
from agent.stub import ScriptedModel

DEFAULT_URL = "http://127.0.0.1:8002"
log = logging.getLogger(__name__)


class Worker:
    """Carries due claims on, a pass at a time; a call mid-pass asks for one more."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.again = threading.Event()

    def wake(self) -> None:
        """Start a pass in the background, or ask the running one to go again."""
        self.again.set()
        if self.lock.acquire(blocking=False):
            threading.Thread(target=self.passes, daemon=True).start()

    def passes(self) -> None:
        """Work passes until no call came in during the last one."""
        try:
            while self.again.is_set():
                self.again.clear()
                carry_on_all()
        finally:
            self.lock.release()
        tracing.flush()


WORKER = Worker()


def key() -> str:
    """Return the key the backend and the service share."""
    return os.getenv("AGENT_SERVICE_KEY") or ""


def carry_on_all() -> list[str]:
    """Take every run that is due from the backend and carry each on."""
    try:
        with main.acting(key()):
            due = main.call("POST", "/api/agent/resumable")
    except httpx.HTTPError as error:
        log.warning("The backend could not be reached: %s", error)
        return []
    if "error" in due:
        log.warning("The backend refused the agent's service: %s", due["error"])
        return []
    for run in due:
        carry_on(run)
    return [run["run_id"] for run in due]


def carry_on(run: dict[str, Any]) -> None:
    """Carry one claim on under its run's token, then end the run."""
    run_id = run["run_id"]
    llm = ScriptedModel() if os.getenv("AGENT_STUB") == "1" else None
    error, failure = "", ""
    with main.acting(run["token"]):
        try:
            main.resume(
                run["claim_id"],
                run_id,
                run["signoff"],
                llm,
                lambda step: main.call("POST", f"/api/runs/{run_id}/steps", step),
                run["seconds"],
            )
        except Exception as caught:  # noqa: BLE001 - the run must end however it went
            error, failure = main.describe(caught), main.failure(caught)
        main.call(
            "POST", f"/api/runs/{run_id}/end", {"error": error, "failure": failure}
        )


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """On start, carry on whatever came due while the service was away."""
    if key():
        WORKER.wake()
    yield


app = FastAPI(title="UnderCover agent", lifespan=lifespan, openapi_url=None)


@app.get("/health", operation_id="agent_health")
def health() -> dict[str, str]:
    """Check that the agent's service is running."""
    return {"status": "ok"}


@app.post("/resume", operation_id="resume_due_claims", status_code=202)
def resume(authorization: Annotated[str, Header()]) -> dict[str, str]:
    """Carry on every claim that is due, in the background."""
    given = authorization.removeprefix("Bearer ").strip()
    if not key() or not hmac.compare_digest(given, key()):
        raise HTTPException(401, "Only the backend may call the agent's service.")
    WORKER.wake()
    return {"status": "accepted"}
