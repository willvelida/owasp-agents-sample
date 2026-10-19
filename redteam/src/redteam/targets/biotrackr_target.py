"""PyRIT target for the Biotrackr AG-UI endpoint (starter or solution)."""

import asyncio
import json
import uuid
from typing import Any

import httpx
from pyrit.models import Message, construct_response_from_request
from pyrit.prompt_target import PromptTarget


class BiotrackrTarget(PromptTarget):
    """Posts one AG-UI run per prompt and returns the assistant text plus every tool call and result.

    Tool results are part of the response because data reaching the model counts as a leak even when the
    model does not repeat it. Each PyRIT conversation maps to one AG-UI thread. The SSE stream is always
    read to the end: a client that disconnects early cancels the run and nothing is persisted (WI-08).
    """

    def __init__(self, *, url: str, headers: dict[str, str], timeout: float = 180.0) -> None:
        super().__init__(endpoint=url, model_name="biotrackr-chat")
        self._url = url
        self._headers = headers
        self._timeout = timeout
        self._threads: dict[str, str] = {}
        self.extra_headers: dict[str, str] = {}

    def _validate_request(self, *, normalized_conversation: list[Message]) -> None:
        pieces = normalized_conversation[-1].message_pieces
        if len(pieces) != 1 or pieces[0].converted_value_data_type != "text":
            raise ValueError("BiotrackrTarget accepts a single text piece per message")

    async def _send_prompt_to_target_async(self, *, normalized_conversation: list[Message]) -> list[Message]:
        request = normalized_conversation[-1].message_pieces[0]
        thread_id = self._threads.setdefault(request.conversation_id, str(uuid.uuid4()))
        text = await self.run_async(thread_id, request.converted_value)
        return [construct_response_from_request(request=request, response_text_pieces=[text])]

    async def run_async(self, thread_id: str, prompt: str) -> str:
        # The whole run has one deadline: a stalled stream (the starter has no timeouts) cannot block the scorecard.
        try:
            text = await asyncio.wait_for(self._run_stream(thread_id, prompt), timeout=self._timeout)
        except TimeoutError:
            return f"[timeout] no complete response within {self._timeout:.0f} s"
        return text

    async def _run_stream(self, thread_id: str, prompt: str) -> str:
        body = {
            "threadId": thread_id,
            "runId": str(uuid.uuid4()),
            "messages": [{"id": str(uuid.uuid4()), "role": "user", "content": prompt}],
            "state": {},
            "tools": [],
            "context": [],
            "forwardedProps": {},
        }
        headers = {**self._headers, **self.extra_headers, "Accept": "text/event-stream"}
        transcript = Transcript()
        async with (
            httpx.AsyncClient(timeout=httpx.Timeout(self._timeout, connect=10.0)) as client,
            client.stream("POST", self._url, json=body, headers=headers) as response,
        ):
            if response.status_code >= 400:
                await response.aread()
                return f"[HTTP {response.status_code}] {response.text[:300]}"
            data: list[str] = []
            async for line in response.aiter_lines():
                if line.startswith("data:"):
                    data.append(line[5:].lstrip())
                elif line == "" and data:
                    transcript.handle(json.loads("\n".join(data)))
                    data = []
            if data:
                transcript.handle(json.loads("\n".join(data)))
        return transcript.render()


class Transcript:
    def __init__(self) -> None:
        self.text: list[str] = []
        self.tools: list[str] = []
        self._names: dict[str, str] = {}
        self._args: dict[str, str] = {}
        self.error: str | None = None

    def handle(self, event: dict[str, Any]) -> None:
        kind = event.get("type")
        if kind == "TEXT_MESSAGE_CONTENT":
            self.text.append(event.get("delta", ""))
        elif kind == "TOOL_CALL_START":
            self._names[event["toolCallId"]] = event.get("toolCallName", "?")
        elif kind == "TOOL_CALL_ARGS":
            self._args[event["toolCallId"]] = self._args.get(event["toolCallId"], "") + event.get("delta", "")
        elif kind == "TOOL_CALL_END":
            call_id = event["toolCallId"]
            self.tools.append(f"[tool] {self._names.get(call_id, '?')}({self._args.get(call_id, '')})")
        elif kind == "TOOL_CALL_RESULT":
            self.tools.append(f"[result] {event.get('content', '')}")
        elif kind == "RUN_ERROR":
            code = event.get("code")
            self.error = (f"{code}: " if code else "") + event.get("message", "unknown error")

    def render(self) -> str:
        parts = ["".join(self.text), *self.tools]
        if self.error:
            parts.append(f"[run error] {self.error}")
        return "\n".join(p for p in parts if p)
