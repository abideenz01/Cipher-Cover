"""Scripted models for tests and end-to-end runs. They never call a real model.

ScriptedModel reads the claim, the policy, the history and section 10 of the
wording, pays every item claimed, approves and pays. Its decisions are not meant
to be right. FaultyModel adds the failures a long run meets.
"""

import json
import re
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

TOKENS_PER_CALL = 100


def result(messages: list[BaseMessage], name: str) -> Any:
    """Return the last result of a tool, parsed from JSON."""
    for message in reversed(messages):
        if isinstance(message, ToolMessage) and message.name == name:
            return json.loads(message.text)
    return None


def reply(content: str, calls: list[tuple[str, dict[str, Any]]], n: int) -> AIMessage:
    """Return a model reply with its tool calls and a fixed token count."""
    return AIMessage(
        content=content,
        tool_calls=[
            {"name": name, "args": args, "id": f"{name}-{n}-{i}"}
            for i, (name, args) in enumerate(calls)
        ],
        usage_metadata={
            "input_tokens": TOKENS_PER_CALL - 10,
            "output_tokens": 10,
            "total_tokens": TOKENS_PER_CALL,
        },
    )


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

    def sections(self, messages: list[BaseMessage]) -> list[str]:  # noqa: ARG002
        """Return the sections to cite."""
        return ["wording-10"]

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
                    "read_section",
                    {"source": "wording", "number": 10},
                ),
                "read_section": (
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
                        "sections": self.sections(messages),
                    },
                ),
                "record_decision": (
                    "pay_claim",
                    {"claim_id": claim_id, "amount": payout},
                ),
            }
        if done == "pay_claim":
            return reply(f"Approved {claim_id}.", [], len(messages))
        return reply("", [script[done]], len(messages))


class FaultyModel(ScriptedModel):
    """The scripted model, with the failures a long run meets.

    errors are raised one per call before the script goes on. always is raised on
    every call. loop keeps reading the claim forever. cite_unread first cites a
    section it never read, then reads it and decides again.
    """

    errors: list[Exception] = Field(default_factory=list)
    always: Exception | None = None
    loop: bool = False
    cite_unread: bool = False

    def _generate(self, messages: list[BaseMessage], *_: Any, **__: Any) -> ChatResult:
        if self.always:
            raise self.always
        if self.errors:
            raise self.errors.pop(0)
        return super()._generate(messages)

    def sections(self, messages: list[BaseMessage]) -> list[str]:
        if self.cite_unread and not result(messages, "record_decision"):
            return ["manual-9"]
        return ["wording-10", "manual-9"] if self.cite_unread else ["wording-10"]

    def next_message(self, messages: list[BaseMessage]) -> AIMessage:
        claim_id = re.findall(r"CLM-\d+", messages[1].text)[0]
        last = messages[-1]
        done = (last.name or "") if isinstance(last, ToolMessage) else ""
        n = len(messages)
        if self.loop:
            return reply("", [("get_claim", {"claim_id": claim_id})], n)
        refused = result(messages, "record_decision")
        if self.cite_unread and done == "record_decision" and "error" in refused:
            return reply("", [("read_section", {"source": "manual", "number": 9})], n)
        if self.cite_unread and done == "read_section" and refused:
            decision = {
                "claim_id": claim_id,
                "decision": "approve",
                "payout": result(messages, "calculate_payout")["payout"],
                "reason": "Scripted approval.",
                "sections": self.sections(messages),
            }
            return reply("", [("record_decision", decision)], n)
        return super().next_message(messages)
