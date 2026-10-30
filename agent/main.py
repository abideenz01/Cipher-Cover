"""The UnderCover Agent."""

import os
from collections.abc import Callable
from typing import Any, Literal

import httpx
from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.config import get_config
from pydantic import BaseModel, SecretStr

load_dotenv(override=True)

BACKEND_URL = "http://127.0.0.1:8000"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "openai/gpt-6-luna"

Step = dict[str, Any]


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
    with backend() as client:
        response = client.request(method, path, json=body, params=params)
    if response.is_server_error:
        response.raise_for_status()
    if response.is_client_error:
        return {"error": response.json()["detail"]}
    return response.json()


def model_name() -> str:
    """Return the model named in MODEL_NAME, or GPT-6 Luna by default."""
    return os.getenv("MODEL_NAME") or DEFAULT_MODEL


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
def calculate_payout(claim_id: str, lines: list[Line], paid_by_others: float) -> Any:
    """Work out the payout for the lines to pay, under section 10 of the wording."""
    body = {
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
    section: str,
) -> Any:
    """Record the decision, the payout, the reason and the section relied on."""
    body = {
        "decision": decision,
        "payout": payout,
        "reason": reason,
        "section": section,
        "model": get_config().get("configurable", {}).get("model", model_name()),
    }
    return call("POST", f"/api/claims/{claim_id}/decision", body)


@tool
def pay_claim(claim_id: str, amount: float) -> Any:
    """Pay an approved claim. Over $1,000.00 it waits for a handler's sign-off."""
    return call("POST", f"/api/claims/{claim_id}/pay", {"amount": amount})


TOOLS = [
    get_claim,
    get_policy,
    get_customer_history,
    calculate_payout,
    record_decision,
    pay_claim,
]


def model() -> ChatOpenAI:
    """Return the chat model on OpenRouter."""
    name = os.getenv("MODEL_NAME")
    return ChatOpenAI(
        model=name or DEFAULT_MODEL,
        base_url=OPENROUTER_BASE_URL,
        api_key=SecretStr(os.environ["OPENROUTER_API_KEY"]),
        reasoning_effort=None if name else "low",
    )


def system_prompt() -> str:
    """Return the instructions and the policy wording, read from the backend."""
    instructions = call("GET", "/api/instructions")["text"]
    wording = call("GET", "/api/wording")
    return (
        f"{instructions}\n\n# Policy wording, version {wording['version']}\n\n"
        f"{wording['text']}"
    )


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


def run(
    claim_id: str,
    thread_id: str,
    llm: BaseChatModel | None = None,
    on_step: Callable[[Step], None] | None = None,
) -> str:
    """Run the agent on one claim and return its final reply."""
    llm = llm or model()
    label = getattr(llm, "model_name", None) or llm._llm_type
    agent = create_agent(llm, tools=TOOLS, system_prompt=system_prompt())
    reply = ""
    for update in agent.stream(
        {"messages": [{"role": "user", "content": f"Claim {claim_id}"}]},
        config={"configurable": {"thread_id": thread_id, "model": label}},
        stream_mode="updates",
    ):
        for data in update.values():
            for message in (data or {}).get("messages", []):
                for step in steps(message):
                    if on_step:
                        on_step(step)
                reply = message.text
    return reply
