"""The claim agent's graph: its state, its nodes and its edges.

think calls the model, act runs the tools it asked for, and settle ends the
claim once the backend has accepted a decision. Settling an approval pays it:
straight away when no sign-off is needed, and after interrupt() returns when
the backend says the payout waits for a handler. The graph never applies the
payout limit itself; the backend does. Every step is saved by the checkpointer,
so a stopped claim carries on from where it got to, on the same thread.
"""

import json
from collections.abc import Callable
from typing import Annotated, Any, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt
from pydantic import ValidationError

Retry = Callable[[Callable[[], BaseMessage]], BaseMessage]
Pay = Callable[[str, float], Any]


class ClaimState(TypedDict):
    """What the claim agent has worked out so far, saved after every step."""

    messages: Annotated[list[AnyMessage], add_messages]
    claim_id: str
    model_calls: int
    decision: dict[str, Any]
    reply: str


class StepLimit(Exception):
    """The claim used all the model calls it is allowed."""


def start(claim_id: str) -> ClaimState:
    """Return the state a fresh claim agent starts from."""
    return {
        "messages": [HumanMessage(f"Claim {claim_id}")],
        "claim_id": claim_id,
        "model_calls": 0,
        "decision": {},
        "reply": "",
    }


def accepted(message: AIMessage, results: list[ToolMessage]) -> dict[str, Any]:
    """Return the decision the backend accepted in this step, or {}."""
    by_id = {r.tool_call_id: r for r in results}
    for call in message.tool_calls:
        result = by_id.get(call["id"] or "")
        if call["name"] != "record_decision" or result is None:
            continue
        reply = json.loads(result.text) if result.text.startswith("{") else {}
        if "state" in reply:
            return {
                "decision": call["args"]["decision"],
                "payout": call["args"]["payout"],
                "state": reply["state"],
            }
    return {}


class Nodes:
    """The graph's nodes, over one model, its tools and its instructions."""

    def __init__(  # noqa: PLR0913 - the graph's parts, each named
        self,
        llm: BaseChatModel,
        tools: list[BaseTool],
        prompt: str,
        *,
        limit: int,
        retry: Retry,
        pay: Pay,
    ) -> None:
        self.bound = llm.bind_tools(tools)
        self.tools = {t.name: t for t in tools}
        self.prompt, self.limit, self.retry, self.pay = prompt, limit, retry, pay

    def think(self, state: ClaimState) -> dict[str, Any]:
        """Ask the model for its next step, within the limit on model calls."""
        if state["model_calls"] >= self.limit:
            raise StepLimit(f"The claim reached its limit of {self.limit} model calls.")
        messages = [SystemMessage(self.prompt), *state["messages"]]
        message = self.retry(lambda: self.bound.invoke(messages))
        return {"messages": [message], "model_calls": state["model_calls"] + 1}

    def act(self, state: ClaimState, config: RunnableConfig) -> dict[str, Any]:
        """Run the tools the model asked for; a refusal goes back to the model."""
        message = state["messages"][-1]
        assert isinstance(message, AIMessage)  # noqa: S101 - think only routes here with tool calls
        results = [self.use(call, config) for call in message.tool_calls]
        update: dict[str, Any] = {"messages": results}
        if decision := accepted(message, results):
            update["decision"] = decision
        return update

    def use(self, call: Any, config: RunnableConfig) -> ToolMessage:  # noqa: ANN401 - a ToolCall dict
        """Run one tool call, or say why it could not run."""
        tool = self.tools.get(call["name"])
        if tool is None:
            return error(call, f"There is no tool {call['name']}.")
        try:
            return tool.invoke(call, config)
        except ValidationError as invalid:
            return error(call, str(invalid))

    def settle(self, state: ClaimState) -> dict[str, Any]:
        """Pay an approval, waiting first for a sign-off when the backend asks."""
        claim_id, decision = state["claim_id"], state["decision"]
        if decision["decision"] != "approve":
            return {"reply": f"{claim_id}: {decision['decision']}."}
        if decision["state"] == "waiting_for_signoff":
            interrupt({"claim_id": claim_id, "payout": decision["payout"]})
        paid = self.pay(claim_id, decision["payout"])
        if "error" in paid:
            raise RuntimeError(f"The payment was refused: {paid['error']}")
        result = ToolMessage(json.dumps(paid), name="pay_claim", tool_call_id="settle")
        reply = f"{claim_id}: approve, ${decision['payout']:,.2f}, paid."
        return {"messages": [result], "reply": reply}


def build(  # noqa: PLR0913 - the graph's parts, each named
    llm: BaseChatModel,
    tools: list[BaseTool],
    prompt: str,
    *,
    limit: int,
    retry: Retry,
    pay: Pay,
    checkpointer: BaseCheckpointSaver[str],
) -> CompiledStateGraph[ClaimState, None, ClaimState, ClaimState]:
    """Build the claim agent's graph."""
    nodes = Nodes(llm, tools, prompt, limit=limit, retry=retry, pay=pay)
    graph = StateGraph(ClaimState)
    graph.add_node("think", nodes.think)
    graph.add_node("act", nodes.act)
    graph.add_node("settle", nodes.settle)
    graph.add_edge(START, "think")
    graph.add_conditional_edges("think", after_think, ["act", END])
    graph.add_conditional_edges("act", after_act, ["settle", "think"])
    graph.add_edge("settle", END)
    return graph.compile(checkpointer=checkpointer)


def after_think(state: ClaimState) -> str:
    """Run the tools the model asked for, or stop when it asked for none."""
    message = state["messages"][-1]
    return "act" if isinstance(message, AIMessage) and message.tool_calls else END


def after_act(state: ClaimState) -> str:
    """Settle once a decision is accepted; otherwise give the model the results."""
    return "settle" if state["decision"] else "think"


def error(call: Any, text: str) -> ToolMessage:  # noqa: ANN401 - a ToolCall dict
    """Return a refused tool call as a message for the model."""
    return ToolMessage(
        json.dumps({"error": text}),
        name=call["name"],
        tool_call_id=call["id"],
        status="error",
    )
