"""Continue the caller's W3C context from MCP request metadata."""

from collections.abc import Sequence
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ContentBlock
from opentelemetry import propagate, trace
from opentelemetry.context import Context
from opentelemetry.trace import SpanKind


class TracedFastMCP(FastMCP):
    """Trace tool execution using the starter's default exception capture."""

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Sequence[ContentBlock] | dict[str, Any]:
        try:
            meta = self.get_context().request_context.meta
        except ValueError:
            meta = None
        carrier = (meta.model_extra or {}) if meta is not None else {}
        with trace.get_tracer(__name__).start_as_current_span(
            f"tools/call {name}",
            context=propagate.extract(carrier, context=Context()),
            kind=SpanKind.SERVER,
            attributes={
                "mcp.method.name": "tools/call",
                "gen_ai.tool.name": name,
                "gen_ai.operation.name": "execute_tool",
            },
        ):
            return await super().call_tool(name, arguments)
