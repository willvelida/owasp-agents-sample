"""Continue the caller's W3C context from MCP request metadata."""

from collections.abc import Sequence
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ContentBlock
from opentelemetry import propagate, trace
from opentelemetry.context import Context
from opentelemetry.trace import SpanKind, Status, StatusCode


class TracedFastMCP(FastMCP):
    """Trace tool execution without exporting arguments, results, or exception text."""

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Sequence[ContentBlock] | dict[str, Any]:
        try:
            meta = self.get_context().request_context.meta
        except ValueError:
            # FastMCP raises outside an active request, including direct local calls.
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
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            try:
                return await super().call_tool(name, arguments)
            except Exception as exc:
                span.set_status(Status(StatusCode.ERROR))
                span.set_attribute("error.type", type(exc).__name__)
                raise
