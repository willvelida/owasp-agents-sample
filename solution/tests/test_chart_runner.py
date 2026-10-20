"""Chart runner unit tests with the static check out of the picture (ASI05).

The runner must hold even when hostile code reaches it: the worker gets an empty environment, a wall clock,
and only a PNG comes back. Container isolation (no network, read-only image, no engine socket) is checked
against the running stack in tests/integration/test_chart_runner_isolation.py.
"""

import json

import pytest
from starlette.testclient import TestClient

from chart_runner import runner

CHART = (
    'plt.bar([p["label"] for p in data], [p["value"] for p in data])\n'
    'plt.title("Steps")\ncaption = "ok"\nplt.savefig("chart.png")'
)
DATA = [{"label": "2026-10-13", "value": 7939}]


async def test_valid_chart_returns_png():
    result = await runner.run_job(CHART, DATA)
    assert result["ok"], result
    assert result["title"] == "Steps" and result["caption"] == "ok"
    import base64

    assert base64.b64decode(result["png_base64"]).startswith(runner.PNG_MAGIC)


async def test_canary_is_not_in_the_worker_environment(monkeypatch):
    monkeypatch.setenv("REPORT_AGENT_CANARY", "CANARY-ENV-R5X")
    code = "import os\nplt.title(os.environ['REPORT_AGENT_CANARY'])\nplt.savefig('chart.png')"
    result = await runner.run_job(code, DATA)
    assert not result["ok"]
    assert "KeyError" in result["error"]
    assert "CANARY-ENV-R5X" not in json.dumps(result)


async def test_worker_environment_is_empty(monkeypatch):
    import os

    monkeypatch.setenv("SECRET_THING", "x")
    code = "import os\nplt.title(','.join(sorted(os.environ)))\nplt.savefig('chart.png')"
    result = await runner.run_job(code, DATA)
    assert result["ok"], result
    names = set(result["title"].split(","))
    assert "SECRET_THING" not in names
    # Only what the runner sets (plus what the OS injects into every process) is visible.
    platform = {"LC_CTYPE", "SYSTEMROOT", "PROCESSOR_ARCHITECTURE"} if os.name == "nt" else {"LC_CTYPE"}
    assert names <= {"HOME", "MPLCONFIGDIR"} | platform


async def test_runaway_code_is_killed():
    result = await runner.run_job("while True:\n    pass", DATA, limit=1.0)
    assert not result["ok"] and "exceeded" in result["error"]


@pytest.mark.parametrize(
    "code",
    ["plt.title('no file')", "open('chart.png', 'wb').write(b'not a png')"],
    ids=["no-chart", "not-png"],
)
async def test_only_a_png_comes_back(code):
    result = await runner.run_job(code, DATA)
    assert not result["ok"]


def test_http_rejects_bad_and_oversized_requests():
    client = TestClient(runner.app)
    assert client.post("/run", content=b"not json").status_code == 400
    assert client.post("/run", json={"code": 1, "data": []}).status_code == 400
    assert client.post("/run", json={"code": "x", "data": [{}] * 63}).status_code == 400
    assert client.post("/run", content=b"x" * (runner.MAX_BODY_BYTES + 1)).status_code == 413
