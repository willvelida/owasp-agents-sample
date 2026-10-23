"""Cross-service parentage and metadata-only server spans."""

from types import SimpleNamespace

import pytest
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import RequestParams
from opentelemetry import trace
from opentelemetry.trace import SpanKind, StatusCode

from health_mcp.tracing import TracedFastMCP

TRACE_ID = "1234567890abcdef1234567890abcdef"
PARENT_ID = "1234567890abcdef"
TRACEPARENT = f"00-{TRACE_ID}-{PARENT_ID}-01"
MARKER = "PRIVATE-HEALTH-PAYLOAD"


@pytest.mark.parametrize("metadata", ["parent", "missing", "empty", "outside"])
async def test_given_mcp_metadata_when_tool_called_then_server_parentage(monkeypatch, span_exporter, metadata):
    server = TracedFastMCP("test")

    @server.tool()
    async def probe(value: str) -> str:
        return value

    if metadata != "outside":
        meta = (
            RequestParams.Meta(traceparent=TRACEPARENT)
            if metadata == "parent"
            else RequestParams.Meta()
            if metadata == "empty"
            else None
        )
        monkeypatch.setattr(server, "get_context", lambda: SimpleNamespace(request_context=SimpleNamespace(meta=meta)))

    with trace.get_tracer(__name__).start_as_current_span("unrelated"):
        result = await server.call_tool("probe", {"value": MARKER})

    assert MARKER in str(result)
    span = next(s for s in span_exporter.get_finished_spans() if s.name == "tools/call probe")
    assert span.kind == SpanKind.SERVER
    assert span.attributes == {
        "mcp.method.name": "tools/call",
        "gen_ai.tool.name": "probe",
        "gen_ai.operation.name": "execute_tool",
    }
    if metadata == "parent":
        assert span.context.trace_id == int(TRACE_ID, 16)
        assert span.parent.span_id == int(PARENT_ID, 16)
    else:
        assert span.parent is None
        assert span.context.trace_id != int(TRACE_ID, 16)
    assert not span.events


async def test_given_failing_mcp_tool_when_traced_then_exception_text_is_absent(span_exporter):
    server = TracedFastMCP("test")

    @server.tool()
    async def probe() -> str:
        raise ValueError(MARKER)

    with pytest.raises(ToolError, match=MARKER):
        await server.call_tool("probe", {})

    (span,) = span_exporter.get_finished_spans()
    assert span.status.status_code == StatusCode.ERROR
    assert span.status.description is None
    assert span.attributes["error.type"] == "ToolError"
    assert MARKER not in str(span.attributes)
    assert not span.events


def test_given_a2a_traceparent_when_bearer_rejected_then_401_in_same_trace(sim, span_exporter):
    from starlette.testclient import TestClient
    from test_report_agent import A2A_KEY, Spies, report_validator

    from report_agent.a2a_security import SignatureVerifier
    from report_agent.app import create_app

    app = create_app(Spies().pipeline(), report_validator(sim), SignatureVerifier([A2A_KEY.public_key()]))

    with TestClient(app) as client:
        response = client.post("/", json={}, headers={"traceparent": TRACEPARENT, "Authorization": "Bearer invalid"})
        health = client.get("/healthz")

    assert response.status_code == 401
    assert health.status_code == 200
    servers = [s for s in span_exporter.get_finished_spans() if s.kind == SpanKind.SERVER]
    assert len(servers) == 1
    (span,) = servers
    assert span.context.trace_id == int(TRACE_ID, 16)
    assert span.parent.span_id == int(PARENT_ID, 16)
    assert span.attributes.get("http.response.status_code", span.attributes.get("http.status_code")) == 401
