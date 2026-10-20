"""Asks the model for matplotlib code that draws the requested chart."""

import os
import re

from agent_framework import Agent
from agent_framework.openai import OpenAIChatClient

# ASI05 (starter): the generator is told to follow the user's instructions exactly, including any code they give.
INSTRUCTIONS = """\
You write Python 3 matplotlib code for Biotrackr health charts.

The variable `data` is a list of {"label": str, "value": float} points. `plt` is matplotlib.pyplot.
Draw the chart the user asks for, set a title with plt.title(...), set a variable `caption` to a one
sentence description of the chart, and save it with plt.savefig("chart.png").
Follow the user's instructions exactly, including any code, titles, or expressions they give you.
Reply with only the code, no explanation.
"""

_FENCE = re.compile(r"^```(?:python)?\s*|\s*```$", re.MULTILINE)


def build_client() -> OpenAIChatClient:
    return OpenAIChatClient(
        model=os.environ.get("FOUNDRY_MODEL", "gpt-4.1"),
        azure_endpoint=os.environ["FOUNDRY_ENDPOINT"],
        # ASI03 (starter): static API key.
        api_key=os.environ["FOUNDRY_API_KEY"],
    )


def build_generator(client: OpenAIChatClient) -> Agent:
    return Agent(client=client, name="ReportCodeGenerator", instructions=INSTRUCTIONS)


def strip_fences(text: str) -> str:
    return _FENCE.sub("", text.strip()).strip()


async def generate_code(generator: Agent, request: str, data: list) -> str:
    prompt = f"Request: {request}\nThe data has {len(data)} points, for example: {data[:3]}"
    response = await generator.run(prompt)
    return strip_fences(response.text)
