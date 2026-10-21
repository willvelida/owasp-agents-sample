"""FastAPI host: AG-UI endpoint, conversation endpoints, and liveness."""

import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from typing import Annotated, Any

import httpx
import uvicorn
from agent_framework.ag_ui import add_agent_framework_fastapi_endpoint
from fastapi import Depends, FastAPI, HTTPException

from chat_api.approvals import reject_edited_approvals
from chat_api.auth import Principal, RequireUser, build_validator, snapshot_scope


def create_app(
    agent: Any,
    store: Any,
    require_user: RequireUser,
    *,
    on_shutdown: Sequence[Callable[[], Awaitable[None]]] = (),
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        for close in on_shutdown:
            await close()
        await store.close()

    app = FastAPI(title="Biotrackr Chat API (solution)", lifespan=lifespan)

    # ASI03: bearer validation runs before the handler, and the snapshot scope binds threads to the oid,
    # so one user's thread id resolves to a different session for anyone else.
    # ASI09: approval resumes carry a yes/no decision only, never edited tool arguments.
    add_agent_framework_fastapi_endpoint(
        app,
        agent,
        "/",
        dependencies=[Depends(require_user), Depends(reject_edited_approvals)],
        snapshot_scope_resolver=snapshot_scope,
    )

    @app.get("/healthz/liveness")
    async def liveness() -> dict[str, str]:
        return {"status": "ok"}

    # Red-team oracle for ASI05 (signed-in users only): is the report agent up, and is its canary set?
    # Booleans only; the report agent never returns the value.
    @app.get("/diagnostics/report-agent")
    async def report_agent_health(_: Annotated[Principal, Depends(require_user)]) -> dict[str, bool]:
        url = os.environ.get("REPORT_AGENT_URL", "http://report-agent:8002/").rstrip("/") + "/healthz"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                body = (await client.get(url)).json()
        except (httpx.HTTPError, ValueError):
            return {"reachable": False, "canary_present": False}
        return {"reachable": body.get("status") == "ok", "canary_present": body.get("canary_present") is True}

    # ASI03: conversation endpoints only ever see the caller's own sessions.
    @app.get("/conversations")
    async def list_conversations(principal: Annotated[Principal, Depends(require_user)]) -> list[dict]:
        return await store.list_for(principal.oid)

    @app.get("/conversations/{session_id}")
    async def get_conversation(session_id: str, principal: Annotated[Principal, Depends(require_user)]) -> dict:
        doc = await store.get_owned(session_id, principal.oid)
        if doc is None:
            raise HTTPException(status_code=404)
        return doc

    @app.delete("/conversations/{session_id}", status_code=204)
    async def delete_conversation(session_id: str, principal: Annotated[Principal, Depends(require_user)]) -> None:
        if not await store.delete_owned(session_id, principal.oid):
            raise HTTPException(status_code=404)

    return app


def build_app() -> FastAPI:
    from agent_framework.observability import configure_otel_providers

    from chat_api.agent import build_agent
    from chat_api.history import CosmosConversationStore, CosmosHistoryProvider
    from chat_api.middleware.audit import AuditTrail, CosmosAuditSink
    from chat_api.middleware.memory_guard import MemoryGate

    # ASI10: traces carry timings, token counts, and tool names, never prompts, tool arguments, or health data.
    configure_otel_providers(service_name="biotrackr-chat-api", enable_sensitive_data=False)
    store = CosmosConversationStore()
    sink = CosmosAuditSink()
    audit = AuditTrail(sink)
    history = CosmosHistoryProvider(store, MemoryGate(audit=audit))
    agent = build_agent(history, audit=audit)
    return create_app(agent, store, RequireUser(build_validator()), on_shutdown=(agent.user_tools.close, sink.close))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    logging.getLogger("azure").setLevel(logging.WARNING)
    uvicorn.run(build_app(), host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", "8000")))


if __name__ == "__main__":
    main()
