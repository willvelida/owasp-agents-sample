"""Report tools: the chat agent asks the report agent (over A2A) to draw a chart.

ASI09: generate_report needs the user's approval before it runs (approval_mode from governance.yaml) and
is capped per conversation by the tool budget. ASI07 baseline: each call carries an app-only token for the
report API from the Agent ID sidecar (autonomous, no user token), the agent card is a local pinned copy,
and requests and responses are typed. ASI03: a user can only check reports they generated. ASI08: every
call is bounded (connect 5 s, read 30 s), status polls are retried with jitter, and a circuit breaker fails fast
while the report agent is down. Submissions are never retried, so a report is never requested twice.
"""

import asyncio
import json
import logging
import os
from collections import OrderedDict
from collections.abc import Sequence
from typing import Annotated, Any

import httpx
from a2a.client import ClientConfig, ClientFactory
from a2a.helpers import get_data_parts, new_data_part, new_message
from a2a.types import GetTaskRequest, Role, SendMessageRequest, TaskState
from agent_framework import FunctionTool, tool
from pydantic import Field, ValidationError

from chat_api.auth import require_principal
from chat_api.identity import DownstreamTokenProvider, IdentityError
from chat_api.middleware.resilience import HTTP_TIMEOUT, CircuitBreaker, CircuitOpenError, is_transient, retry
from report_agent.schemas import MAX_POINTS, DataPoint, Report, ReportRequest, agent_card

log = logging.getLogger("chat_api.tools_report")

WAIT_FOR_REPORT_SECONDS = 75.0
POLL_INTERVAL_SECONDS = 1.0
TERMINAL_STATES = {TaskState.TASK_STATE_COMPLETED, TaskState.TASK_STATE_FAILED, TaskState.TASK_STATE_CANCELED}


class ReportOwners:
    """Which signed-in user generated each report id (in-process, like the tool budget)."""

    def __init__(self, max_reports: int = 10_000) -> None:
        self._owners: OrderedDict[str, str] = OrderedDict()
        self._lock = asyncio.Lock()
        self._max = max_reports

    async def record(self, report_id: str, oid: str) -> None:
        async with self._lock:
            self._owners[report_id] = oid
            while len(self._owners) > self._max:
                self._owners.popitem(last=False)

    async def owned_by(self, report_id: str, oid: str) -> bool:
        async with self._lock:
            return self._owners.get(report_id) == oid


def _unavailable(reason: str) -> str:
    return json.dumps({"status": "unavailable", "reason": reason})


def _for_model(report: Report) -> str:
    body = report.model_dump(exclude_none=True, exclude={"chart_png_base64"})
    if report.chart_png_base64:
        body["chart_png_bytes"] = len(report.chart_png_base64) * 3 // 4
    return json.dumps(body)


def _report_of(task: Any) -> Report | None:
    """The typed report artefact, or None while the task is still running."""
    if task.status.state not in TERMINAL_STATES:
        return None
    for artifact in task.artifacts:
        for part in get_data_parts(artifact.parts):
            return Report.model_validate(part)
    raise ValueError("finished task has no report")


class ReportService:
    def __init__(
        self,
        tokens: DownstreamTokenProvider,
        url: str | None = None,
        owners: ReportOwners | None = None,
        *,
        wait_seconds: float = WAIT_FOR_REPORT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
        breaker: CircuitBreaker | None = None,
    ) -> None:
        self.tokens = tokens
        self.card = agent_card(url or os.environ.get("REPORT_AGENT_URL", "http://report-agent:8002/"))
        self.owners = owners or ReportOwners()
        self.wait_seconds = wait_seconds
        self._transport = transport
        self.breaker = breaker or CircuitBreaker("report-agent")

    async def _http(self) -> httpx.AsyncClient:
        header = await self.tokens.report_api_header()
        return httpx.AsyncClient(headers={"Authorization": header}, timeout=HTTP_TIMEOUT, transport=self._transport)

    async def generate(self, request: ReportRequest) -> str:
        oid = require_principal().oid

        async def submit_and_wait() -> str:
            async with await self._http() as http:
                client = ClientFactory(ClientConfig(streaming=False, httpx_client=http)).create(self.card)
                message = new_message([new_data_part(request.model_dump())], role=Role.ROLE_USER)
                send = SendMessageRequest(message=message)
                send.configuration.return_immediately = True
                task = None
                async for event in client.send_message(send):
                    task = event.task
                if task is None or not task.id:
                    return _unavailable("the report service returned no report id")
                await self.owners.record(task.id, oid)
                deadline = asyncio.get_running_loop().time() + self.wait_seconds
                while (report := _report_of(task)) is None:
                    if asyncio.get_running_loop().time() >= deadline:
                        return json.dumps({"report_id": task.id, "status": "pending"})
                    await asyncio.sleep(POLL_INTERVAL_SECONDS)
                    poll = GetTaskRequest(id=task.id)
                    task = await retry(lambda poll=poll: client.get_task(poll))
            return _for_model(report)

        try:
            return await self.breaker.call(submit_and_wait, counts=is_transient)
        except CircuitOpenError:
            return _unavailable("the report service is temporarily unavailable; try again in a minute")
        except IdentityError as exc:
            log.warning("no report API token: %s", exc)
            return _unavailable("the report service could not be authorised")
        except (httpx.HTTPError, ValidationError, ValueError) as exc:
            log.warning("report request failed: %s", type(exc).__name__)
            return _unavailable("the report service did not answer correctly")
        except Exception as exc:
            log.warning("report request failed: %s", type(exc).__name__)
            return _unavailable("the report service is unavailable")

    async def status(self, report_id: str) -> str:
        if not await self.owners.owned_by(report_id, require_principal().oid):
            return json.dumps({"report_id": report_id, "status": "not_found"})

        async def fetch() -> Report | None:
            async with await self._http() as http:
                client = ClientFactory(ClientConfig(streaming=False, httpx_client=http)).create(self.card)
                return _report_of(await retry(lambda: client.get_task(GetTaskRequest(id=report_id))))

        try:
            report = await self.breaker.call(fetch, counts=is_transient)
        except CircuitOpenError:
            return _unavailable("the report service is temporarily unavailable; try again in a minute")
        except IdentityError:
            return _unavailable("the report service could not be authorised")
        except Exception as exc:
            log.warning("report status failed: %s", type(exc).__name__)
            return _unavailable("the report service did not answer correctly")
        if report is None:
            return json.dumps({"report_id": report_id, "status": "pending"})
        return _for_model(report)


def build_report_tools(
    service: ReportService, *, approval_required: Sequence[str] = ("generate_report",)
) -> list[FunctionTool]:
    async def generate_report(
        # Same wording as the starter: the controls behind this tool must not depend on the model cleaning input.
        request: Annotated[
            str, Field(min_length=1, max_length=500, description="The user's chart request, word for word.")
        ],
        data: Annotated[
            list[DataPoint],
            Field(
                min_length=1,
                max_length=MAX_POINTS,
                description='Points from the user\'s records, e.g. {"label": "2026-10-01", "value": 7939}',
            ),
        ],
    ) -> str:
        """Generate a chart report from the user's own records. The user approves it first. Returns its status."""
        try:
            typed = ReportRequest(request=request, data=data)
        except ValidationError as exc:
            return json.dumps({"status": "invalid", "reason": f"{exc.error_count()} invalid fields"})
        return await service.generate(typed)

    async def check_report_status(
        report_id: Annotated[
            str, Field(min_length=1, max_length=64, description="The report id from generate_report.")
        ],
    ) -> str:
        """Check the status of a report this user generated and get its summary."""
        return await service.status(report_id)

    def mode(name: str) -> str:
        return "always_require" if name in approval_required else "never_require"

    return [
        tool(generate_report, approval_mode=mode("generate_report")),
        tool(check_report_status, approval_mode=mode("check_report_status")),
    ]
