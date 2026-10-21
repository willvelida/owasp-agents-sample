"""PyRIT target for the Biotrackr AG-UI endpoint (starter or solution)."""

import asyncio
import json
import uuid
from typing import Any

import httpx
from pyrit.models import Message, construct_response_from_request
from pyrit.prompt_target import PromptTarget
from pyrit.prompt_target.common.target_capabilities import TargetCapabilities
from pyrit.prompt_target.common.target_configuration import TargetConfiguration


class BiotrackrTarget(PromptTarget):
    """Posts one AG-UI run per prompt and returns the assistant text plus every tool call and result.

    Tool results are part of the response because data reaching the model counts as a leak even when the
    model does not repeat it. Each PyRIT conversation maps to one AG-UI thread. The SSE stream is always
    read to the end: a client that disconnects early cancels the run and nothing is persisted (WI-08).

    Multi-turn: the chat API keeps each thread's history server-side, so a follow-up prompt only sends the new
    user turn. The target declares editable history because PyRIT's Crescendo requires it; the harness runs
    Crescendo with max_backtracks=0, so history is never rewound or edited.
    """

    _DEFAULT_CONFIGURATION = TargetConfiguration(
        capabilities=TargetCapabilities(supports_multi_turn=True, supports_editable_history=True)
    )

    def __init__(self, *, url: str, headers: dict[str, str], timeout: float = 240.0, max_approvals: int = 3) -> None:
        super().__init__(endpoint=url, model_name="biotrackr-chat")
        self._url = url
        self._headers = headers
        self._timeout = timeout
        self._threads: dict[str, str] = {}
        self.extra_headers: dict[str, str] = {}
        self.burst_tool_calls = 0
        self.burst_aborted = 0
        self.max_approvals = max_approvals

    def _validate_request(self, *, normalized_conversation: list[Message]) -> None:
        pieces = normalized_conversation[-1].message_pieces
        if len(pieces) != 1 or pieces[0].converted_value_data_type != "text":
            raise ValueError("BiotrackrTarget accepts a single text piece per message")

    async def _send_prompt_to_target_async(self, *, normalized_conversation: list[Message]) -> list[Message]:
        request = normalized_conversation[-1].message_pieces[0]
        thread_id = self._threads.setdefault(request.conversation_id, str(uuid.uuid4()))
        text = await self.run_async(thread_id, request.converted_value)
        return [construct_response_from_request(request=request, response_text_pieces=[text])]

    def thread_for(self, conversation_id: str) -> str:
        """The AG-UI thread behind a PyRIT conversation, so a later turn lands in the same server-side history."""
        return self._threads.setdefault(conversation_id, str(uuid.uuid4()))

    async def run_async(self, thread_id: str, prompt: str) -> str:
        # The whole run has one deadline: a stalled stream (the starter has no timeouts) cannot block the scorecard.
        try:
            text = await asyncio.wait_for(self._run_stream(thread_id, prompt), timeout=self._timeout)
        except TimeoutError:
            return f"[timeout] no complete response within {self._timeout:.0f} s"
        return text

    async def _run_stream(self, thread_id: str, prompt: str) -> str:
        transcript = Transcript()
        resume: dict[str, Any] | None = None
        async with httpx.AsyncClient(timeout=httpx.Timeout(self._timeout, connect=10.0)) as client:
            # The attacker is the signed-in user, so approval requests are approved (at most a few rounds).
            for _ in range(1 + self.max_approvals):
                body = self._body(thread_id, prompt if resume is None else None, resume)
                error = await self._post(client, body, transcript)
                if error:
                    return error
                if not transcript.interrupts or transcript.error:
                    break
                for interrupt in transcript.interrupts:
                    transcript.tools.append(f"[approved] {interrupt.get('message', interrupt.get('id'))}")
                resume = {
                    "interrupts": [
                        {"id": i["id"], "status": "resolved", "payload": {"accepted": True}}
                        for i in transcript.interrupts
                    ]
                }
                transcript.interrupts = []
        return transcript.render()

    @staticmethod
    def _body(thread_id: str, prompt: str | None, resume: dict[str, Any] | None) -> dict[str, Any]:
        body: dict[str, Any] = {
            "threadId": thread_id,
            "runId": str(uuid.uuid4()),
            "messages": [{"id": str(uuid.uuid4()), "role": "user", "content": prompt}] if prompt else [],
            "state": {},
            "tools": [],
            "context": [],
            "forwardedProps": {},
        }
        if resume is not None:
            body["resume"] = resume
        return body

    async def _post(self, client: httpx.AsyncClient, body: dict[str, Any], transcript: "Transcript") -> str | None:
        headers = {**self._headers, **self.extra_headers, "Accept": "text/event-stream"}
        async with client.stream("POST", self._url, json=body, headers=headers) as response:
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
        return None


# AG-UI adds a synthetic call for client-side confirmation UIs; it is not a tool the agent ran.
SYNTHETIC_TOOLS = {"confirm_changes"}


class Transcript:
    def __init__(self) -> None:
        self.text: list[str] = []
        self.tools: list[str] = []
        self._names: dict[str, str] = {}
        self._args: dict[str, str] = {}
        self.error: str | None = None
        self.interrupts: list[dict[str, Any]] = []

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
            if self._names.get(call_id) not in SYNTHETIC_TOOLS:
                self.tools.append(f"[tool] {self._names.get(call_id, '?')}({self._args.get(call_id, '')})")
        elif kind == "TOOL_CALL_RESULT":
            self.tools.append(f"[result] {event.get('content', '')}")
        elif kind == "RUN_FINISHED":
            outcome = event.get("outcome") or {}
            if outcome.get("type") == "interrupt":
                self.interrupts = list(outcome.get("interrupts") or [])
        elif kind == "RUN_ERROR":
            code = event.get("code")
            self.error = (f"{code}: " if code else "") + event.get("message", "unknown error")

    def render(self) -> str:
        parts = ["".join(self.text), *self.tools]
        if self.error:
            parts.append(f"[run error] {self.error}")
        return "\n".join(p for p in parts if p)
