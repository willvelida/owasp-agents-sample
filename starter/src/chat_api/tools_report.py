"""Report tools: the chat agent asks the report agent (over A2A) to draw a chart."""

import json
import os
from typing import Annotated, Any

import httpx
from a2a.client import ClientConfig, ClientFactory
from a2a.helpers import get_data_parts, new_data_part, new_message
from a2a.types import GetTaskRequest, Role, SendMessageRequest, TaskState
from agent_framework import tool
from pydantic import Field

REPORT_AGENT_URL = os.environ.get("REPORT_AGENT_URL", "http://localhost:8002/")


async def _client(http: httpx.AsyncClient):
    # ASI07 (starter): the agent card is fetched and trusted as is; no caller identity is sent.
    return await ClientFactory(ClientConfig(streaming=False, httpx_client=http)).create_from_url(REPORT_AGENT_URL)


def _report(task: Any) -> dict[str, Any]:
    for artifact in task.artifacts:
        for part in get_data_parts(artifact.parts):
            return dict(part)
    return {"report_id": task.id, "status": TaskState.Name(task.status.state).removeprefix("TASK_STATE_").lower()}


def _for_model(report: dict[str, Any]) -> str:
    report = dict(report)
    png = report.pop("chart_png_base64", None)
    if png:
        report["chart_png_bytes"] = len(png) * 3 // 4
    return json.dumps(report)


# ASI09 (starter): no human approval before a report is generated.
@tool
async def generate_report(
    request: Annotated[str, Field(description="The user's chart request, word for word.")],
    data: Annotated[list[dict[str, Any]], Field(description='Points to chart: [{"label": "2026-10-01", "value": 62}]')],
) -> str:
    """Generate a chart report of the user's health data. Returns the report id, status, and summary."""
    # ASI08 (starter): no timeout; the chat run waits for as long as the report agent takes.
    async with httpx.AsyncClient(timeout=None) as http:  # noqa: S113
        client = await _client(http)
        message = new_message([new_data_part({"request": request, "data": data})], role=Role.ROLE_USER)
        report: dict[str, Any] = {}
        async for event in client.send_message(SendMessageRequest(message=message)):
            report = _report(event.task)
    return _for_model(report)


@tool
async def check_report_status(
    report_id: Annotated[str, Field(description="The report id returned by generate_report.")],
) -> str:
    """Check the status of a report and get its summary."""
    async with httpx.AsyncClient(timeout=None) as http:  # noqa: S113
        client = await _client(http)
        task = await client.get_task(GetTaskRequest(id=report_id))
    return _for_model(_report(task))


REPORT_TOOLS = [generate_report, check_report_status]
