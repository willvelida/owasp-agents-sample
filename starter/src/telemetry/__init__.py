"""Local-only telemetry bootstrap for the starter's three services."""

import logging
import os
from typing import Final

from agent_framework import observability
from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

# ASI10 (starter): prompts, tool arguments, and health records are exported to local traces.
SENSITIVE_DATA: Final = True
_configured = False
log = logging.getLogger(__name__)


def excluded_urls() -> str:
    """Exclude liveness probes from HTTP telemetry in every service."""
    return r"/healthz(?:/[^?]*)?(?:\?.*)?$"


def setup_telemetry(service_name: str) -> None:
    """Configure OTLP once; ignore Azure ingestion settings for the starter."""
    global _configured
    if _configured:
        return

    if os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING"):
        log.warning("Starter telemetry is local only; ignoring APPLICATIONINSIGHTS_CONNECTION_STRING.")
    observability.configure_otel_providers(service_name=service_name, enable_sensitive_data=SENSITIVE_DATA)
    HTTPXClientInstrumentor().instrument()
    _configured = True


def instrument_app(app: FastAPI) -> None:
    """Instrument an already-built app only after telemetry has been configured."""
    if _configured:
        FastAPIInstrumentor.instrument_app(app, excluded_urls=excluded_urls())
