"""A scripted model for tests and end-to-end runs. It never calls a real model.

It reads the claim, the policy and the history, pays every item claimed, approves
and pays. Its decisions are not meant to be right.
"""

import json
import re
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field


def result(messages: list[BaseMessage], name: str) -> Any:
    """Return the last result of a tool, parsed from JSON."""
    for message in reversed(messages):
        if isinstance(message, ToolMessage) and message.name == name:
            return json.loads(message.text)
    return None


class ScriptedModel(BaseChatModel):
    """Approve and pay every claim, with every item as a line."""

    prompts: list[list[BaseMessage]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedModel":  # noqa: ARG002
        return self

    def _generate(self, messages: list[BaseMessage], *_: Any, **__: Any) -> ChatResult:
        self.prompts.append(messages)
        message = self.next_message(messages)
        return ChatResult(generations=[ChatGeneration(message=message)])

    def next_message(self, messages: list[BaseMessage]) -> AIMessage:
        """Return the next step of the script."""
        claim_id = re.findall(r"CLM-\d+", messages[1].text)[0]
        last = messages[-1]
        done = (last.name or "") if isinstance(last, ToolMessage) else ""
        claim = result(messages, "get_claim")
        calculation = result(messages, "calculate_payout")
        script: dict[str, tuple[str, dict[str, Any]]] = {
            "": ("get_claim", {"claim_id": claim_id}),
        }
        if claim:
            lines = [
                {
                    "description": i["description"],
                    "amount": i["amount"],
                    "electronic": i["category"] == "electronics",
                }
                for i in claim["items"]
            ]
            script |= {
                "get_claim": ("get_policy", {"policy_id": claim["policy_id"]}),
                "get_policy": (
                    "get_customer_history",
                    {"customer_id": claim["customer_id"]},
                ),
                "get_customer_history": (
                    "calculate_payout",
                    {"claim_id": claim_id, "lines": lines, "paid_by_others": 0},
                ),
            }
        if calculation:
            payout = calculation["payout"]
            script |= {
                "calculate_payout": (
                    "record_decision",
                    {
                        "claim_id": claim_id,
                        "decision": "approve",
                        "payout": payout,
                        "reason": f"Scripted approval for ${payout:,.2f}.",
                        "section": "Section 10. How we work out your payment",
                    },
                ),
                "record_decision": (
                    "pay_claim",
                    {"claim_id": claim_id, "amount": payout},
                ),
            }
        if done == "pay_claim":
            return AIMessage(content=f"Approved {claim_id}.")
        name, args = script[done]
        return AIMessage(
            content="",
            tool_calls=[{"name": name, "args": args, "id": f"{name}-{len(messages)}"}],
        )
