"""The Cipher Cover voice assistant for claims handlers."""

import os
from typing import Any, Literal

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import BaseTool, tool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel, SecretStr

from agent.main import DEFAULT_MODEL, OPENROUTER_BASE_URL, call

SESSIONS = InMemorySaver()


class UiAction(BaseModel):
    """What the dashboard should do on screen."""

    type: Literal["none", "open_claim", "focus_signoff"]
    claim_id: str


class VoiceReply(BaseModel):
    """The reply to show, the words to speak and the screen action."""

    reply: str
    speech: str
    ui_action: UiAction


def tools(handler_id: str) -> list[BaseTool]:
    """Return the nine tools, acting for one handler."""

    @tool
    def find_claims(text: str) -> Any:
        """Find claims by a spoken or typed claim number or a customer's surname."""
        return {"claims": call("GET", "/api/claims/search", params={"text": text})}

    @tool
    def get_claim_brief(claim_id: str) -> Any:
        """Give the facts of one claim."""
        return call("GET", f"/api/claims/{claim_id}/brief")

    @tool
    def get_decision_brief(claim_id: str) -> Any:
        """Explain the latest decision on a claim."""
        return call("GET", f"/api/claims/{claim_id}/decision-brief")

    @tool
    def list_signoff_queue() -> Any:
        """List the payouts waiting for a handler's sign-off."""
        return {"signoffs": call("GET", "/api/signoffs")}

    @tool
    def get_latest_run_status(claim_id: str) -> Any:
        """Report on the latest agent run on a claim."""
        return call("GET", f"/api/claims/{claim_id}/run-status")

    @tool
    def get_analytics_brief() -> Any:
        """Give the number of claims in each state and the total paid."""
        return call("GET", "/api/analytics/brief")

    @tool
    def start_claim_run(claim_id: str) -> Any:
        """Start the UnderCover Agent on one waiting claim."""
        return call("POST", f"/api/claims/{claim_id}/runs")

    @tool
    def open_claim(claim_id: str) -> Any:
        """Open a claim on the handler's screen."""
        return {"ui_action": {"type": "open_claim", "claim_id": claim_id}}

    @tool
    def request_signoff(claim_id: str) -> Any:
        """Highlight a payout on the Sign-off screen for the handler to confirm."""
        body = {"handler_id": handler_id}
        return call("POST", f"/api/claims/{claim_id}/signoff-request", body)

    return [
        find_claims,
        get_claim_brief,
        get_decision_brief,
        list_signoff_queue,
        get_latest_run_status,
        get_analytics_brief,
        start_claim_run,
        open_claim,
        request_signoff,
    ]


def model() -> ChatOpenAI:
    """Return the voice model: VOICE_MODEL_NAME, else the claims agent's model."""
    name = os.getenv("VOICE_MODEL_NAME") or os.getenv("MODEL_NAME")
    return ChatOpenAI(
        model=name or DEFAULT_MODEL,
        base_url=OPENROUTER_BASE_URL,
        api_key=SecretStr(os.environ["OPENROUTER_API_KEY"]),
        reasoning_effort=None if name else "low",
    )


def run_turn(
    session_id: str, handler_id: str, text: str, llm: BaseChatModel | None = None
) -> dict[str, Any]:
    """Answer one spoken or typed request from a handler."""
    agent = create_agent(
        llm or model(),
        tools=tools(handler_id),
        system_prompt=call("GET", "/api/voice/instructions")["text"],
        response_format=ToolStrategy(VoiceReply),
        checkpointer=SESSIONS,
    )
    result = agent.invoke(
        {"messages": [{"role": "user", "content": f"[{handler_id}] {text}"}]},
        config={"configurable": {"thread_id": session_id}},
    )
    reply: VoiceReply = result["structured_response"]
    messages = result["messages"]
    start = max(i for i, m in enumerate(messages) if isinstance(m, HumanMessage))
    called = [
        c["name"]
        for m in messages[start:]
        if isinstance(m, AIMessage)
        for c in m.tool_calls
        if c["name"] != "VoiceReply"
    ]
    return reply.model_dump() | {"tools": called}
