"""Fixed replies that replace a run without calling the model (kill switch, quarantine, budgets, degradation).

AG-UI turns any exception into a generic RUN_ERROR, so controls that refuse a run for an operational reason answer
with a fixed message instead. The reply is set as the agent middleware result, so nothing downstream runs: no
context provider, no model call, no tool call, and nothing is written to the conversation history.
"""

import uuid
from collections.abc import AsyncIterator

from agent_framework import AgentContext, AgentResponse, AgentResponseUpdate, Content, Message, ResponseStream


def response_for(text: str) -> AgentResponse:
    return AgentResponse(messages=[Message(role="assistant", contents=[Content.from_text(text)])])


def stream_for(text: str) -> ResponseStream[AgentResponseUpdate, AgentResponse]:
    message_id = str(uuid.uuid4())

    async def updates() -> AsyncIterator[AgentResponseUpdate]:
        yield AgentResponseUpdate(role="assistant", contents=[Content.from_text(text)], message_id=message_id)

    return ResponseStream(updates(), finalizer=lambda _: response_for(text))


def reply_with(context: AgentContext, text: str) -> None:
    """Answer the run with `text`; the caller must not call call_next()."""
    context.result = stream_for(text) if context.stream else response_for(text)
