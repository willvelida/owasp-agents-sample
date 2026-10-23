"""Telemetry export selection and the solution's fixed no-content contract."""

from unittest.mock import Mock

import pytest
from agent_framework import (
    Agent,
    BaseChatClient,
    ChatMiddlewareLayer,
    Content,
    FunctionInvocationLayer,
    Message,
    observability,
)
from agent_framework.observability import ChatTelemetryLayer
from fastapi import FastAPI

import telemetry


@pytest.mark.parametrize("use_azure", [False, True])
def test_given_export_destination_when_setup_then_fixed_no_content(monkeypatch, use_azure):
    import azure.identity
    import azure.monitor.opentelemetry

    local = Mock()
    distro = Mock()
    credential = Mock()
    enable = Mock()
    httpx = Mock()
    monkeypatch.setattr(observability, "configure_otel_providers", local)
    monkeypatch.setattr(observability, "enable_instrumentation", enable)
    monkeypatch.setattr(azure.identity, "ManagedIdentityCredential", credential)
    monkeypatch.setattr(azure.monitor.opentelemetry, "configure_azure_monitor", distro)
    monkeypatch.setattr(telemetry, "HTTPXClientInstrumentor", httpx)
    if use_azure:
        monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "test-connection")
        monkeypatch.setenv("AZURE_CLIENT_ID", "test-client")

    telemetry.setup_telemetry("test-service")
    telemetry.setup_telemetry("ignored-second-call")

    assert telemetry.SENSITIVE_DATA is False
    if use_azure:
        local.assert_not_called()
        credential.assert_called_once_with(client_id="test-client")
        enable.assert_called_once_with(enable_sensitive_data=False)
        distro.assert_called_once()
        options = distro.call_args.kwargs
        assert options["connection_string"] == "test-connection"
        assert options["credential"] is credential.return_value
        assert options["resource"].attributes["service.name"] == "test-service"
        assert options["enable_live_metrics"] is True
        assert options["logger_name"] == "biotrackr.telemetry.export"
        assert options["instrumentation_options"] == {"fastapi": {"enabled": False}}
        assert "views" not in options
        httpx.assert_not_called()
    else:
        distro.assert_not_called()
        local.assert_called_once_with(service_name="test-service", enable_sensitive_data=False)
        httpx.return_value.instrument.assert_called_once_with()


def test_given_unconfigured_bootstrap_when_instrument_app_then_noop(monkeypatch):
    instrument = Mock()
    monkeypatch.setattr(telemetry.FastAPIInstrumentor, "instrument_app", instrument)

    telemetry.instrument_app(FastAPI())

    instrument.assert_not_called()


def test_given_configured_bootstrap_when_instrument_app_then_excludes_health(monkeypatch):
    instrument = Mock()
    monkeypatch.setattr(telemetry, "_configured", True)
    monkeypatch.setattr(telemetry.FastAPIInstrumentor, "instrument_app", instrument)
    app = FastAPI()

    telemetry.instrument_app(app)

    instrument.assert_called_once_with(app, excluded_urls=telemetry.excluded_urls())


def test_given_built_chat_app_when_authenticated_then_server_span_without_probes(
    monkeypatch, chat_validator, sim, span_exporter
):
    from fastapi.testclient import TestClient
    from opentelemetry.trace import SpanKind
    from test_chat_auth import SpyAgent, SpyStore

    import chat_api.agent
    import chat_api.history
    from chat_api import app

    agent = SpyAgent()
    agent.user_tools = SpyStore()
    monkeypatch.setattr(app, "setup_telemetry", lambda _: None)
    monkeypatch.setattr(telemetry, "_configured", True)
    monkeypatch.setattr(chat_api.history, "CosmosConversationStore", SpyStore)
    monkeypatch.setattr(chat_api.agent, "build_agent", lambda *a, **k: agent)
    monkeypatch.setattr(app, "build_validator", lambda: chat_validator)

    with TestClient(app.build_app()) as client:
        response = client.get("/conversations", headers={"Authorization": f"Bearer {sim.user_token('alice')}"})
        health = client.get("/healthz/liveness")

    assert response.status_code == health.status_code == 200
    servers = [s for s in span_exporter.get_finished_spans() if s.kind == SpanKind.SERVER]
    assert len(servers) == 1
    assert servers[0].name == "GET /conversations"


@pytest.mark.parametrize("sensitive", [False, True], ids=["solution", "positive-control"])
async def test_given_governed_agent_when_exported_then_content_gate_is_effective(sensitive, span_exporter):
    from conftest import ENV
    from test_tool_governance import ScriptedClient, Tools, call

    from chat_api.auth import current_principal, principal_from_claims
    from chat_api.middleware import build_middleware, load_governance
    from chat_api.middleware.audit import AuditTrail, MemorySink

    class TelemetryClient(FunctionInvocationLayer, ChatMiddlewareLayer, ChatTelemetryLayer, BaseChatClient):
        def __init__(self, turns: list[list[Content]]) -> None:
            super().__init__()
            self.turns = list(turns)
            self.requests: list[list[Message]] = []

        _inner_get_response = ScriptedClient._inner_get_response

    forbidden = {
        "gen_ai.input.messages",
        "gen_ai.output.messages",
        "gen_ai.system_instructions",
        "gen_ai.tool.call.arguments",
        "gen_ai.tool.call.result",
    }
    tools = Tools()
    token = current_principal.set(principal_from_claims({"oid": ENV["ALICE_OID"], "name": "alice"}, "token"))
    observability.enable_instrumentation(enable_sensitive_data=sensitive, force=True)
    try:
        client = TelemetryClient([[call("get_sleep_records")], [Content.from_text("Sleep summary complete.")]])
        agent = Agent(
            client=client,
            name="telemetry-test",
            instructions="Summarise the user's sleep.",
            tools=tools.all,
            middleware=build_middleware(load_governance(), audit=AuditTrail(MemorySink())),
        )
        await agent.run("How did I sleep?", session=agent.create_session())
        spans = span_exporter.get_finished_spans()
        operations = {s.attributes.get("gen_ai.operation.name") for s in spans}
        assert {"invoke_agent", "chat", "execute_tool"} <= operations
        assert tools.executed == ["get_sleep_records"]
        attributes = [s.attributes for s in spans] + [e.attributes for s in spans for e in s.events]
        assert ENV["ALICE_OID"] not in str(attributes)
        if sensitive:
            assert any(forbidden.intersection(attrs) for attrs in attributes)
            assert "minutesAsleep" in str(attributes)
        else:
            assert not any(forbidden.intersection(attrs) for attrs in attributes)
            assert "minutesAsleep" not in str(attributes)
    finally:
        observability.enable_instrumentation(enable_sensitive_data=False, force=True)
        current_principal.reset(token)
