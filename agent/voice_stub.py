"""A scripted voice model for tests and end-to-end runs. It never calls a real model.

It picks one tool from keywords in the request, then repeats that tool's reply.
"""

import json
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field


def plan(text: str) -> list[str]:
    """Return the tools to call for a request, in order."""
    lowered = text.lower()
    if "waiting for my sign" in lowered:
        return ["list_signoff_queue"]
    if "sign off" in lowered:
        return ["find_claims", "request_signoff"]
    if "open" in lowered:
        return ["find_claims", "open_claim"]
    return ["get_analytics_brief"]


def reply(name: str, result: Any) -> dict[str, Any]:
    """Return the final reply from the last tool's result."""
    none = {"type": "none", "claim_id": ""}
    if name == "list_signoff_queue":
        ids = ", ".join(item["claim_id"] for item in result["signoffs"]) or "nothing"
        text = f"Waiting for sign-off: {ids}."
        return {"reply": text, "speech": text, "ui_action": none}
    if name == "open_claim":
        claim_id = result["ui_action"]["claim_id"]
        text = f"Opening {claim_id}."
        return {"reply": text, "speech": text, "ui_action": result["ui_action"]}
    if name == "find_claims":
        text = "I could not find that claim."
        return {"reply": text, "speech": text, "ui_action": none}
    if "error" in result:
        return {"reply": result["error"], "speech": result["error"], "ui_action": none}
    action = result.get("ui_action", none)
    return {"reply": result["reply"], "speech": result["speech"], "ui_action": action}


class ScriptedVoiceModel(BaseChatModel):
    """Answer a handler's request with a fixed plan of tool calls."""

    prompts: list[list[BaseMessage]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted-voice"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedVoiceModel":  # noqa: ARG002
        return self

    def _generate(self, messages: list[BaseMessage], *_: Any, **__: Any) -> ChatResult:
        self.prompts.append(messages)
        start = max(i for i, m in enumerate(messages) if isinstance(m, HumanMessage))
        turn = messages[start:]
        results = [m for m in turn if isinstance(m, ToolMessage)]
        steps = plan(turn[0].text)
        found = json.loads(results[-1].text) if results else {}
        if len(results) < len(steps) and found.get("claims") != []:
            name = steps[len(results)]
            args: dict[str, Any] = {}
            if name == "find_claims":
                args = {"text": turn[0].text}
            elif results:
                args = {"claim_id": found["claims"][0]["claim_id"]}
        else:
            name = "VoiceReply"
            args = reply(results[-1].name or "", found)
        call = {"name": name, "args": args, "id": f"{name}-{len(messages)}"}
        message = AIMessage(content="", tool_calls=[call])
        return ChatResult(generations=[ChatGeneration(message=message)])
