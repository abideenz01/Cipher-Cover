"""The UnderCover Agent: the claim agent, which works one claim."""

import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Literal

import httpx
import openai
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    ModelRetryMiddleware,
)
from langchain.agents.middleware.model_call_limit import ModelCallLimitExceededError
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.config import get_config
from pydantic import BaseModel, SecretStr


def load_settings(path: str | None = None) -> None:
    """Fill settings from .env without replacing ones the process was given.

    A harness that starts the backend with its own settings, such as the
    end-to-end tests with VOICE_PROVIDER=stub or a temporary DB_PATH, must not
    have them replaced by a developer's .env.
    """
    load_dotenv(path, override=False)


load_settings()

BACKEND_URL = "http://127.0.0.1:8000"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "deepseek/deepseek-v4.1-flash"
RETRY_DELAY = 1.0
PROVIDER_ERRORS = (
    openai.APITimeoutError,
    openai.APIConnectionError,
    openai.RateLimitError,
    openai.InternalServerError,
)

Step = dict[str, Any]

# The service token the backend issued for the run in hand. Every call to the
# backend sends it, and the backend allows only what that run may do.
TOKEN: ContextVar[str] = ContextVar("token", default="")


@contextmanager
def acting(token: str) -> Iterator[None]:
    """Send this token on every backend call made inside the block."""
    if not token:
        yield
        return
    reset = TOKEN.set(token)
    try:
        yield
    finally:
        TOKEN.reset(reset)


class ClaimTimeout(Exception):
    """The claim took longer than its time limit."""


class Line(BaseModel):
    """One item or expense to pay."""

    description: str
    amount: float
    electronic: bool


def backend() -> httpx.Client:
    """Return a client for the UnderCover backend."""
    return httpx.Client(base_url=BACKEND_URL, timeout=30)


def call(
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    params: dict[str, str] | None = None,
) -> Any:
    """Call the backend. A refusal comes back as an error for the agent to read."""
    token = TOKEN.get()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with backend() as client:
        response = client.request(
            method, path, json=body, params=params, headers=headers
        )
    if response.is_server_error:
        response.raise_for_status()
    if response.is_client_error:
        return {"error": response.json()["detail"]}
    return response.json()


def model_name() -> str:
    """Return the model named in MODEL_NAME, or DeepSeek V4.1 Flash by default."""
    return os.getenv("MODEL_NAME") or DEFAULT_MODEL


def setting(name: str, default: int) -> int:
    """Return a whole-number setting from the environment."""
    return int(os.getenv(name) or default)


def run_id() -> str:
    """Return the run this tool call belongs to, from the agent's config."""
    return get_config().get("configurable", {})["thread_id"]


def failure(error: Exception) -> str:
    """Sort a failed claim run into provider, step_limit, time_limit or error."""
    if isinstance(error, PROVIDER_ERRORS):
        return "provider"
    if isinstance(error, ModelCallLimitExceededError):
        return "step_limit"
    if isinstance(error, ClaimTimeout):
        return "time_limit"
    return "error"


def describe(error: Exception) -> str:
    """Return an error's message, or its type when it has none."""
    return str(error) or type(error).__name__


def retries() -> ModelRetryMiddleware:
    """Retry provider errors three times, waiting longer each time."""
    return ModelRetryMiddleware(
        max_retries=3,
        retry_on=PROVIDER_ERRORS,
        on_failure="error",
        initial_delay=RETRY_DELAY,
        backoff_factor=2,
        jitter=True,
    )


@tool
def get_claim(claim_id: str) -> Any:
    """Read one claim in full: the story, the items claimed and the documents."""
    return call("GET", f"/api/claims/{claim_id}")


@tool
def get_policy(policy_id: str) -> Any:
    """Read a policy with its plan's limits, add-ons, trip and travelers."""
    return call("GET", f"/api/policies/{policy_id}")


@tool
def get_customer_history(customer_id: str) -> Any:
    """Read a customer's earlier claims."""
    return call("GET", f"/api/customers/{customer_id}/history")


@tool
def list_sections(source: Literal["wording", "manual"]) -> Any:
    """List the numbered sections of the policy wording or the claims manual."""
    return call("GET", f"/api/documents/{source}/sections")


@tool
def read_section(source: Literal["wording", "manual"], number: int) -> Any:
    """Read one section of the policy wording or the claims manual."""
    path = f"/api/documents/{source}/sections/{number}"
    return call("GET", path, params={"run_id": run_id()})


@tool
def calculate_payout(claim_id: str, lines: list[Line], paid_by_others: float) -> Any:
    """Work out the payout for the lines to pay, under section 10 of the wording."""
    body = {
        "run_id": run_id(),
        "lines": [Line.model_validate(line).model_dump() for line in lines],
        "paid_by_others": paid_by_others,
    }
    return call("POST", f"/api/claims/{claim_id}/calculate", body)


@tool
def record_decision(
    claim_id: str,
    decision: Literal["approve", "decline", "refer"],
    payout: float,
    reason: str,
    sections: list[str],
) -> Any:
    """Record the decision, the payout, the reason and the section ids relied on."""
    body = {
        "run_id": run_id(),
        "decision": decision,
        "payout": payout,
        "reason": reason,
        "sections": sections,
        "model": get_config().get("configurable", {}).get("model", model_name()),
    }
    return call("POST", f"/api/claims/{claim_id}/decision", body)


@tool
def pay_claim(claim_id: str, amount: float) -> Any:
    """Pay an approved claim. Over $1,000.00 it waits for a handler's sign-off."""
    body = {"run_id": run_id(), "amount": amount}
    return call("POST", f"/api/claims/{claim_id}/pay", body)


TOOLS = [
    get_claim,
    get_policy,
    get_customer_history,
    list_sections,
    read_section,
    calculate_payout,
    record_decision,
    pay_claim,
]


def model() -> ChatOpenAI:
    """Return the chat model on OpenRouter, with no retries of its own."""
    name = os.getenv("MODEL_NAME")
    return ChatOpenAI(
        model=name or DEFAULT_MODEL,
        base_url=OPENROUTER_BASE_URL,
        api_key=SecretStr(os.environ["OPENROUTER_API_KEY"]),
        reasoning_effort=None if name else "low",
        timeout=setting("MODEL_TIMEOUT_SECONDS", 60),
        max_retries=0,
    )


def label(llm: BaseChatModel) -> str:
    """Return the name of a chat model, as recorded on runs and decisions."""
    return getattr(llm, "model_name", None) or llm._llm_type


def tokens(message: AIMessage) -> int:
    """Return the tokens a model reply used."""
    return message.usage_metadata["total_tokens"] if message.usage_metadata else 0


def steps(message: BaseMessage) -> list[Step]:
    """Describe one message as trace steps."""
    if isinstance(message, ToolMessage):
        return [
            {
                "kind": "tool_result",
                "name": message.name or "",
                "detail": {"result": message.text[:400]},
            }
        ]
    if isinstance(message, AIMessage) and message.tool_calls:
        return [
            {"kind": "tool_call", "name": c["name"], "detail": c["args"]}
            for c in message.tool_calls
        ]
    return [{"kind": "message", "name": "agent", "detail": {"text": message.text}}]


def stream(
    agent: Any, prompt: str, config: dict[str, Any], deadline: float
) -> Iterator[BaseMessage]:
    """Yield each new message from an agent, failing once past the deadline."""
    for update in agent.stream(
        {"messages": [{"role": "user", "content": prompt}]},
        config=config,
        stream_mode="updates",
    ):
        for data in update.values():
            yield from (data or {}).get("messages", [])
        if time.monotonic() > deadline:
            raise ClaimTimeout("The claim took longer than its time limit.")


def report(
    llm: BaseChatModel, message: BaseMessage, on_step: Callable[[Step], None] | None
) -> None:
    """Pass a message's steps, and a model reply's usage, to on_step."""
    if not on_step:
        return
    if isinstance(message, AIMessage):
        on_step(
            {"kind": "usage", "name": label(llm), "detail": {"tokens": tokens(message)}}
        )
    for step in steps(message):
        on_step(step)


def run(
    claim_id: str,
    thread_id: str,
    llm: BaseChatModel | None = None,
    on_step: Callable[[Step], None] | None = None,
    seconds: float = 120,
) -> str:
    """Run a fresh claim agent on one claim and return its final reply.

    Call it inside acting(token) with the run's token, or the backend refuses.
    """
    llm = llm or model()
    middleware: list[AgentMiddleware[Any, Any, Any]] = [
        retries(),
        ModelCallLimitMiddleware(
            run_limit=setting("CLAIM_STEP_LIMIT", 30), exit_behavior="error"
        ),
    ]
    agent = create_agent(
        llm,
        tools=TOOLS,
        system_prompt=call("GET", "/api/instructions")["claim"],
        middleware=middleware,
    )
    config = {"configurable": {"thread_id": thread_id, "model": label(llm)}}
    reply = ""
    for message in stream(
        agent, f"Claim {claim_id}", config, time.monotonic() + seconds
    ):
        report(llm, message, on_step)
        reply = message.text
    return reply
