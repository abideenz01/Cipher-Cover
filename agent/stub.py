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

Script = tuple[str, list[tuple[str, dict[str, Any]]]]


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
    every call, and fail_on on every call for that claim. loop keeps reading the
    claim forever. cite_unread first cites a section it never read, then reads it
    and decides again.
    """

    errors: list[Exception] = Field(default_factory=list)
    always: Exception | None = None
    fail_on: str = ""
    loop: bool = False
    cite_unread: bool = False

    def _generate(self, messages: list[BaseMessage], *_: Any, **__: Any) -> ChatResult:
        if self.always:
            raise self.always
        if self.fail_on and self.fail_on in messages[1].text:
            raise RuntimeError(f"The claim agent broke on {self.fail_on}.")
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


class QueueScript(BaseChatModel):
    """Run the queue in order: plan, work each claim, tick it off, finish.

    finish_early tries to finish before working anything, to meet the check for
    missed claims.
    """

    finish_early: bool = False

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "QueueScript":  # noqa: ARG002
        return self

    def _generate(self, messages: list[BaseMessage], *_: Any, **__: Any) -> ChatResult:
        message = self.next_message(messages)
        return ChatResult(generations=[ChatGeneration(message=message)])

    def next_message(self, messages: list[BaseMessage]) -> AIMessage:
        """Return the next step of the run, from the last tool it called."""
        last = messages[-1]
        done = (last.name or "") if isinstance(last, ToolMessage) else ""
        steps = {
            "": lambda _: ("", [("get_run_status", {})]),
            "get_run_status": lambda _: ("", [("list_waiting_claims", {})]),
            "list_waiting_claims": self.plan,
            "work_claim": self.tick,
            "finish_run": self.after_finish,
        }
        content, calls = steps.get(done, self.after_todos)(messages)
        return reply(content, calls, len(messages))

    def plan(self, messages: list[BaseMessage]) -> Script:
        """Write a to-do list of the waiting claims, up to the cap."""
        cap = result(messages, "get_run_status")["cap"]
        waiting = [c["claim_id"] for c in result(messages, "list_waiting_claims")]
        return "", [
            ("write_todos", {"todos": items(waiting[:cap] if cap else waiting)})
        ]

    def tick(self, messages: list[BaseMessage]) -> Script:
        """Tick off the item in progress, or finish when the run refused it."""
        outcome = messages[-1].text
        if "not started" in outcome:
            return "", [("finish_run", {"summary": outcome})]
        todos = ticked(latest_todos(messages), outcome)
        return "", [("write_todos", {"todos": todos})]

    def after_finish(self, messages: list[BaseMessage]) -> Script:
        """End, or add the claims the run said were missed."""
        finished = result(messages, "finish_run")
        if "error" not in finished:
            return "Run finished.", []
        cap = result(messages, "get_run_status")["cap"]
        todos = latest_todos(messages)
        have = {t["claim_id"] for t in todos}
        extra = [c for c in re.findall(r"CLM-\d+", finished["error"]) if c not in have]
        room = cap - len(todos)
        extra = extra[:room] if cap else extra
        return "", [("write_todos", {"todos": todos + items(extra)})]

    def after_todos(self, messages: list[BaseMessage]) -> Script:
        """Work the item in progress, start the next one, or finish."""
        todos = latest_todos(messages)
        if self.finish_early and not result(messages, "finish_run"):
            return "", [("finish_run", {"summary": "Nothing to do."})]
        working = [t for t in todos if t["status"] == "in_progress"]
        if working:
            return "", [("work_claim", {"claim_id": working[0]["claim_id"]})]
        waiting = [t for t in todos if t["status"] == "to_do"]
        if waiting:
            started = [
                t | {"status": "in_progress"} if t is waiting[0] else t for t in todos
            ]
            return "", [("write_todos", {"todos": started})]
        decided = sum(t["status"] == "done" for t in todos)
        return "", [("finish_run", {"summary": f"Decided {decided} claims."})]


def items(claim_ids: list[str]) -> list[dict[str, Any]]:
    """Return new to-do items for claims."""
    return [{"claim_id": c, "status": "to_do", "note": ""} for c in claim_ids]


def latest_todos(messages: list[BaseMessage]) -> list[dict[str, Any]]:
    """Return the to-do list as last written."""
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            for tool_call in message.tool_calls:
                if tool_call["name"] == "write_todos":
                    return tool_call["args"]["todos"]
    return []


def ticked(todos: list[dict[str, Any]], outcome: str) -> list[dict[str, Any]]:
    """Mark the item in progress from the claim agent's one-line outcome."""
    if "left for a handler" in outcome:
        status = "left_for_handler"
    elif "back in the queue" in outcome:
        status = "to_do"
    else:
        status = "done"
    return [
        t | {"status": status, "note": outcome} if t["status"] == "in_progress" else t
        for t in todos
    ]
