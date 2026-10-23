"""One telemetry bootstrap for the solution's three networked services."""

import os
from typing import Final

from agent_framework import observability
from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

# ASI10: export metadata only, never prompts, tool arguments, or health records.
SENSITIVE_DATA: Final = False
_configured = False


def excluded_urls() -> str:
    """Exclude liveness probes from HTTP telemetry in every service."""
    return r"/healthz(?:/[^?]*)?(?:\?.*)?$"


def setup_telemetry(service_name: str) -> None:
    """Configure one asynchronous provider set per process, using Entra on Azure."""
    global _configured
    if _configured:
        return

    connection_string = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if connection_string:
        from azure.identity import ManagedIdentityCredential
        from azure.monitor.opentelemetry import configure_azure_monitor

        configure_azure_monitor(
            connection_string=connection_string,
            credential=ManagedIdentityCredential(client_id=os.environ["AZURE_CLIENT_ID"]),
            resource=observability.create_resource(service_name=service_name),
            enable_live_metrics=True,
            logger_name="biotrackr.telemetry.export",
            instrumentation_options={"fastapi": {"enabled": False}},
        )
        observability.enable_instrumentation(enable_sensitive_data=SENSITIVE_DATA)
    else:
        observability.configure_otel_providers(service_name=service_name, enable_sensitive_data=SENSITIVE_DATA)
        HTTPXClientInstrumentor().instrument()
    _configured = True


def instrument_app(app: FastAPI) -> None:
    """Instrument an already-built app only after telemetry has been configured."""
    if _configured:
        FastAPIInstrumentor.instrument_app(app, excluded_urls=excluded_urls())
