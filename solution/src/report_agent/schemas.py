"""Typed A2A payloads between the chat agent and the report agent (ASI07 baseline; S5 adds signing)."""

from typing import Literal

from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
from pydantic import BaseModel, ConfigDict, Field

MAX_POINTS = 62
LABEL_PATTERN = r"^[A-Za-z0-9 .:/_-]{1,32}$"


class DataPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(pattern=LABEL_PATTERN)
    value: float = Field(allow_inf_nan=False)


class ReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request: str = Field(min_length=1, max_length=500)
    data: list[DataPoint] = Field(min_length=1, max_length=MAX_POINTS)


RejectedBy = Literal["validation", "generator", "static_check", "runner", "reviewer"]


class Report(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: str
    status: Literal["approved", "denied"]
    rejected_by: RejectedBy | None = None
    reason: str | None = None
    summary: str | None = None
    chart_png_base64: str | None = None


def agent_card(url: str) -> AgentCard:
    """The report agent's card. The chat agent uses this local copy and never trusts a fetched card's URL."""
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
