"""Report agent: an A2A server with one skill, generate_report.

The chat agent sends a JSON data part {"request": str, "data": [{"label", "value"}]}. The task's
"report" artefact carries {"report_id", "status", "summary", "chart_png_base64"}; the task id is the
report id, so check_report_status is an A2A GetTask call.
"""

import logging
import os

import uvicorn
from a2a.helpers import get_data_parts, new_data_part, new_task_from_user_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
from opentelemetry.instrumentation.asgi import OpenTelemetryMiddleware
from opentelemetry.util.http import parse_excluded_urls
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from report_agent.executor import run_chart_code
from report_agent.generator import build_client, build_generator, generate_code
from report_agent.reviewer import build_reviewer, review
from telemetry import excluded_urls, setup_telemetry

log = logging.getLogger("report_agent")


class ReportExecutor(AgentExecutor):
    def __init__(self) -> None:
        client = build_client()
        self.generator = build_generator(client)
        self.reviewer = build_reviewer(client)

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task or new_task_from_user_message(context.message)
        if context.current_task is None:
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)
        await updater.start_work()
        # ASI07 (starter): untyped JSON, no schema, no caller check. Whatever arrives is used as is.
        payload = (get_data_parts(context.message.parts) or [{}])[0]
        report = {"report_id": task.id}
        try:
            code = await generate_code(self.generator, str(payload.get("request", "")), list(payload.get("data", [])))
            chart = run_chart_code(code, list(payload.get("data", [])))
            approved, reason = await review(self.reviewer, code, chart.summary)
            if approved:
                report.update(status="approved", summary=chart.summary, chart_png_base64=chart.png_base64)
            else:
                report.update(status="denied", reason=reason)
        except Exception as exc:
            # ASI05 (starter): the raw exception (which can quote the environment) goes back to the caller.
            report.update(status="failed", reason=f"{type(exc).__name__}: {exc}")
        await updater.add_artifact([new_data_part(report)], name="report")
        await updater.complete()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError


def agent_card(url: str) -> AgentCard:
    return AgentCard(
        name="biotrackr-report-agent",
        description="Draws charts of a user's health data.",
        version="1.0.0",
        default_input_modes=["application/json"],
        default_output_modes=["application/json"],
        capabilities=AgentCapabilities(streaming=False),
        supported_interfaces=[AgentInterface(url=url, protocol_binding="JSONRPC", protocol_version="1.0")],
        skills=[
            AgentSkill(
                id="generate_report",
                name="generate_report",
                description="Draw a chart from labelled values and describe it.",
                tags=["report", "chart"],
            )
        ],
    )


async def healthz(_: Request) -> JSONResponse:
    # Red-team oracle: whether the canary is set in this process (a boolean, never the value).
    return JSONResponse({"status": "ok", "canary_present": bool(os.environ.get("REPORT_AGENT_CANARY"))})


def create_app(executor: AgentExecutor | None = None) -> OpenTelemetryMiddleware:
    card = agent_card(os.environ.get("REPORT_AGENT_URL", "http://report-agent:8002/"))
    handler = DefaultRequestHandler(
        agent_executor=executor or ReportExecutor(), task_store=InMemoryTaskStore(), agent_card=card
    )
    # ASI07 (starter): no authentication on the A2A endpoint.
    app = Starlette(
        routes=[
            Route("/healthz", healthz, methods=["GET"]),
            *create_agent_card_routes(card),
            *create_jsonrpc_routes(handler, "/"),
        ]
    )
    return OpenTelemetryMiddleware(app, excluded_urls=parse_excluded_urls(excluded_urls()))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    setup_telemetry("biotrackr-report-agent")
    uvicorn.run(create_app(), host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", "8002")))


if __name__ == "__main__":
    main()
