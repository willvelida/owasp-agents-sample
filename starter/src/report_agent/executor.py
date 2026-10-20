"""Runs the generated chart code and returns the chart."""

import base64
import os
import tempfile
from dataclasses import dataclass

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


@dataclass
class ChartResult:
    title: str
    caption: str
    png: bytes

    @property
    def summary(self) -> str:
        return f"Title: {self.title}. {self.caption}".strip()

    @property
    def png_base64(self) -> str:
        return base64.b64encode(self.png).decode()


def run_chart_code(code: str, data: list) -> ChartResult:
    # ASI05 (starter): model-written code runs with exec() inside the report agent's own process, with its
    # environment variables (REPORT_AGENT_CANARY included), its network, and its file system.
    workdir = tempfile.mkdtemp(prefix="chart-")
    cwd = os.getcwd()
    os.chdir(workdir)
    try:
        plt.close("all")
        scope: dict = {"data": data, "plt": plt}
        exec(code, scope)  # noqa: S102
        title = plt.gca().get_title()
        with open("chart.png", "rb") as handle:
            png = handle.read()
    finally:
        os.chdir(cwd)
        plt.close("all")
    return ChartResult(title=title, caption=str(scope.get("caption", "")), png=png)
