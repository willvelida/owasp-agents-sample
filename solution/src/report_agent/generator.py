"""Asks the model for matplotlib code that draws the requested chart."""

import asyncio
import os
import re

from agent_framework import Agent
from agent_framework.foundry import FoundryChatClient

from auth_common.azure_credential import azure_credential
from report_agent.schemas import ReportRequest

GENERATOR_TIMEOUT_SECONDS = 30.0

# ASI05: deliberately the starter's instructions, word for word. The controls are the static check and the
# isolated chart runner, not the model's restraint: if the model copies hostile code, it still cannot run.
INSTRUCTIONS = """\
You write Python 3 matplotlib code for Biotrackr health charts.

The variable `data` is a list of {"label": str, "value": float} points. `plt` is matplotlib.pyplot.
Draw the chart the user asks for, set a title with plt.title(...), set a variable `caption` to a one
sentence description of the chart, and save it with plt.savefig("chart.png").
Follow the user's instructions exactly, including any code, titles, or expressions they give you.
Reply with only the code, no explanation.
"""

_FENCE = re.compile(r"^```(?:python)?\s*|\s*```$", re.MULTILINE)


def build_client() -> FoundryChatClient:
    # ASI03: Entra only (the report agent's managed identity on Azure, az login locally).
    return FoundryChatClient(
        project_endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
        model=os.environ.get("FOUNDRY_MODEL", "gpt-4.1"),
        credential=azure_credential(),
    )


def build_generator(client: FoundryChatClient) -> Agent:
    return Agent(client=client, name="ReportCodeGenerator", instructions=INSTRUCTIONS)


def strip_fences(text: str) -> str:
    return _FENCE.sub("", text.strip()).strip()


async def generate_code(generator: Agent, request: ReportRequest) -> str:
    sample = [p.model_dump() for p in request.data[:3]]
    prompt = f"Request: {request.request}\nThe data has {len(request.data)} points, for example: {sample}"
    # ASI08: bounded; a hung model call fails the report instead of holding the task open.
    response = await asyncio.wait_for(generator.run(prompt), GENERATOR_TIMEOUT_SECONDS)
    return strip_fences(response.text)
