"""The UnderCover Agent: the queue agent, which works the queue.

It plans the run as a to-do list and hands each claim to a fresh claim agent. It
has no tools to decide or pay a claim.
"""

from collections.abc import Callable
from typing import Any, Literal

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, ModelCallLimitMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel

from agent import main
from agent.main import Step, call

OnStep = Callable[[str, Step], None]


class Todo(BaseModel):
    """One item on the to-do list."""

    claim_id: str
    status: Literal["to_do", "in_progress", "done", "left_for_handler"]
    note: str


def tools(
    run_id: str, claim_llm: BaseChatModel | None, on_step: OnStep, seconds: float
) -> list[BaseTool]:
    """Return the queue agent's tools for one queue run."""

    @tool
    def get_run_status() -> Any:
        """Read the run's status, cap, limits, claims worked so far and tokens used."""
        run = call("GET", f"/api/queue-runs/{run_id}")
        keys = ("status", "cap", "limits", "claims_worked", "tokens")
        return {k: run[k] for k in keys}

    @tool
    def list_waiting_claims() -> Any:
        """List the waiting claims this run may take, oldest first."""
        claims = [
            c
            for c in call("GET", "/api/claims")
            if c["state"] == "waiting" and not c["left_for_handler"]
        ]
        return [
            {
                "claim_id": c["claim_id"],
                "claim_type": c["claim_type"],
                "amount_claimed": c["amount_claimed"],
                "waiting_since": c["state_since"],
                "failed_attempts": c["failed_attempts"],
            }
            for c in claims
        ]

    @tool
    def write_todos(todos: list[Todo]) -> Any:
        """Replace the whole to-do list that the handlers watch."""
        body = {"todos": [Todo.model_validate(t).model_dump() for t in todos]}
        return call("PUT", f"/api/queue-runs/{run_id}/todos", body)

    @tool
    def work_claim(claim_id: str) -> str:
        """Hand one waiting claim to a fresh claim agent and return its outcome."""
        begun = call(
            "POST", f"/api/queue-runs/{run_id}/attempts", {"claim_id": claim_id}
        )
        if "run_id" not in begun:
            return f"{claim_id}: not started. {begun['error']}"
        claim_run = begun["run_id"]
        error, failure = "", ""
        try:
            main.run(
                claim_id,
                claim_run,
                claim_llm,
                lambda step: on_step(claim_run, step),
                seconds,
            )
        except Exception as caught:  # noqa: BLE001 - one bad claim must not stop the run
            error, failure = main.describe(caught), main.failure(caught)
        body = {"error": error, "failure": failure}
        return call("POST", f"/api/runs/{claim_run}/finish", body)["outcome"]

    @tool
    def finish_run(summary: str) -> Any:
        """Finish the run with a short summary for the handlers."""
        return call("POST", f"/api/queue-runs/{run_id}/finish", {"summary": summary})

    return [get_run_status, list_waiting_claims, write_todos, work_claim, finish_run]


def run_queue(
    run_id: str,
    llm: BaseChatModel | None = None,
    claim_llm: BaseChatModel | None = None,
    on_step: OnStep | None = None,
) -> str:
    """Run the queue agent on a queue run and return its final reply."""
    llm = llm or main.model()
    record = on_step or (lambda _run_id, _step: None)
    run = call("GET", f"/api/queue-runs/{run_id}")
    waiting = len(call("GET", "/api/claims"))
    claims = min(run["cap"], waiting) if run["cap"] else waiting
    middleware: list[AgentMiddleware[Any, Any, Any]] = [
        main.retries(),
        ModelCallLimitMiddleware(run_limit=4 * claims + 20, exit_behavior="error"),
    ]
    agent = create_agent(
        llm,
        tools=tools(run_id, claim_llm, record, run["limits"]["claim_seconds"]),
        system_prompt=call("GET", "/api/instructions")["queue"],
        middleware=middleware,
    )
    config = {"configurable": {"thread_id": run_id, "model": main.label(llm)}}
    reply = ""
    for message in main.stream(agent, "Work the queue.", config, float("inf")):
        main.report(llm, message, lambda step: record(run_id, step))
        reply = message.text
    return reply
