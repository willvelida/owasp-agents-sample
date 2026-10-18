"""FastAPI host: AG-UI endpoint, conversation endpoints, and liveness."""

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import uvicorn
from agent_framework.ag_ui import add_agent_framework_fastapi_endpoint
from agent_framework.observability import configure_otel_providers
from fastapi import FastAPI, HTTPException
from starlette.types import ASGIApp, Receive, Scope, Send

from chat_api.agent import build_agent
from chat_api.history import CosmosConversationStore, CosmosHistoryProvider, current_user

# ASI10 (starter): prompts, tool arguments, and health data are written into traces.
configure_otel_providers(service_name="biotrackr-chat-api", enable_sensitive_data=True)

store = CosmosConversationStore()
agent = build_agent(CosmosHistoryProvider(store))


class UserHeaderMiddleware:
    """ASI03 (starter): trusts an X-User-Id header. No token, no signature, no check."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = dict(scope["headers"])
            user = headers.get(b"x-user-id")
            if user:
                current_user.set(user.decode())
        await self.app(scope, receive, send)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await store.close()


app = FastAPI(title="Biotrackr Chat API (starter)", lifespan=lifespan)
app.add_middleware(UserHeaderMiddleware)

# ASI03 (starter): no dependencies (auth) and no snapshot scope, so any caller can drive any thread.
add_agent_framework_fastapi_endpoint(app, agent, "/")


@app.get("/healthz/liveness")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/conversations")
async def list_conversations() -> list[dict]:
    return await store.list_all()


@app.get("/conversations/{session_id}")
async def get_conversation(session_id: str) -> dict:
    doc = await store.get(session_id)
    if doc is None:
        raise HTTPException(status_code=404)
    return doc


@app.delete("/conversations/{session_id}", status_code=204)
async def delete_conversation(session_id: str) -> None:
    if not await store.delete(session_id):
        raise HTTPException(status_code=404)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    logging.getLogger("azure").setLevel(logging.WARNING)
    uvicorn.run(app, host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", "8000")))


if __name__ == "__main__":
    main()
