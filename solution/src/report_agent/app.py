"""Report agent: an A2A server with one skill, generate_report.

ASI07 baseline: every A2A request needs an app-only Entra token for the report API
(aud = REPORT_API_APP_ID, role Report.Generate, azp = CHAT_AGENT_APP_ID) and a payload that matches
schemas.ReportRequest. ASI05: generated code passes the static check and runs only in the isolated
chart runner. ASI09: the reviewer fails closed. A denied report stores no chart.
"""

import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import uvicorn
from a2a.helpers import get_data_parts, new_data_part, new_task_from_user_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from auth_common import AuthError, JwtValidator, bearer_from_header, issuer_for_mode
from report_agent import static_check
from report_agent.executor import ChartResult, ChartRunner, RunnerError
from report_agent.reviewer import Verdict, review
from report_agent.schemas import Report, ReportRequest, agent_card

log = logging.getLogger("report_agent")

REQUIRED_ROLE = "Report.Generate"
PUBLIC_PATHS = frozenset({"/healthz"})


@dataclass
class Pipeline:
    generate: Callable[[ReportRequest], Awaitable[str]]
    runner: ChartRunner
    reviewer: Callable[[str, str], Awaitable[Verdict]]
    check: Callable[[str], static_check.CheckResult] = static_check.check

    async def run(self, report_id: str, payload: Any) -> Report:
        def denied(stage: str, reason: str) -> Report:
            log.warning("report %s denied by %s: %s", report_id, stage, reason)
            return Report(report_id=report_id, status="denied", rejected_by=stage, reason=reason)

        try:
            request = ReportRequest.model_validate(payload)
        except ValidationError as exc:
            return denied("validation", f"request does not match the schema ({exc.error_count()} errors)")
        try:
            code = await self.generate(request)
        except Exception as exc:
            return denied("generator", f"code generation failed: {type(exc).__name__}")
        if not (result := self.check(code)).ok:
            return denied("static_check", result.reason)
        try:
            chart: ChartResult = await self.runner.run(code, [p.model_dump() for p in request.data])
        except RunnerError as exc:
            return denied("runner", str(exc))
        except Exception as exc:
            return denied("runner", f"chart runner failed: {type(exc).__name__}")
        verdict = await self.reviewer(code, chart.summary)
        if not verdict.approved:
            return denied("reviewer", verdict.reason)
        return Report(report_id=report_id, status="approved", summary=chart.summary, chart_png_base64=chart.png_base64)


class ReportExecutor(AgentExecutor):
    def __init__(self, pipeline: Pipeline) -> None:
        self.pipeline = pipeline

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task or new_task_from_user_message(context.message)
        if context.current_task is None:
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)
        await updater.start_work()
        parts = get_data_parts(context.message.parts)
        payload = parts[0] if len(parts) == 1 else None
        report = await self.pipeline.run(task.id, payload)
        await updater.add_artifact([new_data_part(report.model_dump(exclude_none=True))], name="report")
        await updater.complete()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError


class RequireCaller:
    """ASGI middleware: 401 before any A2A handler unless the caller is the chat agent with Report.Generate."""

    def __init__(self, app: ASGIApp, validator: JwtValidator) -> None:
        self.app = app
        self.validator = validator

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"] not in PUBLIC_PATHS:
            headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
            try:
                await self.validator.validate(bearer_from_header(headers.get("authorization")))
            except AuthError as exc:
                log.warning("rejected A2A caller: %s", exc)
                response = JSONResponse(
                    {"error": "unauthorized"}, status_code=401, headers={"WWW-Authenticate": "Bearer"}
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def build_validator() -> JwtValidator:
    return JwtValidator(
        issuer_for_mode(),
        audience=os.environ["REPORT_API_APP_ID"],
        required_role=REQUIRED_ROLE,
        allowed_client_ids={os.environ["CHAT_AGENT_APP_ID"]},
    )


async def healthz(_: Request) -> JSONResponse:
    # Red-team oracle: whether the canary is set in this process (a boolean, never the value).
    return JSONResponse({"status": "ok", "canary_present": bool(os.environ.get("REPORT_AGENT_CANARY"))})


def create_app(pipeline: Pipeline, validator: JwtValidator) -> ASGIApp:
    card = agent_card(os.environ.get("REPORT_AGENT_URL", "http://report-agent:8002/"))
    handler = DefaultRequestHandler(
        agent_executor=ReportExecutor(pipeline), task_store=InMemoryTaskStore(), agent_card=card
    )
    app = Starlette(
        routes=[
            Route("/healthz", healthz, methods=["GET"]),
            *create_agent_card_routes(card),
            *create_jsonrpc_routes(handler, "/"),
        ]
    )
    return RequireCaller(app, validator)


def build_pipeline() -> Pipeline:
    from report_agent.executor import runner_from_env
    from report_agent.generator import build_client, build_generator, generate_code
    from report_agent.reviewer import build_reviewer_factory

    runner = runner_from_env()
    client = build_client()
    generator = build_generator(client)
    new_reviewer = build_reviewer_factory(client)
    return Pipeline(
        generate=lambda request: generate_code(generator, request),
        runner=runner,
        reviewer=lambda code, summary: review(new_reviewer, code, summary),
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    logging.getLogger("azure").setLevel(logging.WARNING)
    app = create_app(build_pipeline(), build_validator())
    uvicorn.run(app, host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", "8002")))


if __name__ == "__main__":
    main()
