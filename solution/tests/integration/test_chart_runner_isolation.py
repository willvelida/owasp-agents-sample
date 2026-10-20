"""Live checks of the chart runner's container isolation (ASI05). Run with the stack up:

$env:RUN_INTEGRATION = "1"; uv run pytest tests/integration -q

The jobs are sent straight to the runner socket from report-agent, so the static check is out of the
picture: these prove the runner holds on its own.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("RUN_INTEGRATION") != "1", reason="needs the running Compose stack")

SOLUTION = Path(__file__).resolve().parents[2]
ENGINE_SOCKETS = ["/var/run/docker.sock", "/run/docker.sock", "/run/podman/podman.sock", "/var/run/podman/podman.sock"]


def exec_in(service: str, code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        ["podman", "compose", "exec", "-T", service, "python", "-c", code],  # noqa: S607
        cwd=SOLUTION,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )


def run_job(code: str) -> dict:
    """Send a job to the runner over its socket, from inside report-agent."""
    probe = (
        f"CODE = {code!r}\n"
        "import asyncio, json\n"
        "from report_agent.executor import UnixSocketRunner, RunnerError\n"
        "async def main():\n"
        "    try:\n"
        "        r = await UnixSocketRunner('/sockets/chart/runner.sock').run(CODE, [{'label': 'a', 'value': 1}])\n"
        "        print(json.dumps({'ok': True, 'title': r.title}))\n"
        "    except RunnerError as e:\n"
        "        print(json.dumps({'ok': False, 'error': str(e)}))\n"
        "asyncio.run(main())\n"
    )
    result = exec_in("report-agent", probe)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def chart(body: str) -> str:
    return f"{body}\nplt.title(str(t))\nplt.savefig('chart.png')"


def test_report_agent_has_the_canary():
    result = exec_in("report-agent", "import os; print(bool(os.environ.get('REPORT_AGENT_CANARY')))")
    assert result.stdout.strip() == "True"


def test_runner_environment_has_no_canary():
    out = run_job(chart("import os\nt = os.environ.get('REPORT_AGENT_CANARY', 'ABSENT')"))
    assert out == {"ok": True, "title": "ABSENT"}


def test_runner_has_no_network():
    code = chart(
        "import socket\ntry:\n    socket.create_connection(('1.1.1.1', 443), timeout=3); t = 'CONNECTED'\n"
        "except OSError as e:\n    t = 'BLOCKED ' + type(e).__name__"
    )
    out = run_job(code)
    assert out["ok"] and out["title"].startswith("BLOCKED"), out


def test_runner_cannot_write_outside_tmp():
    code = chart(
        "try:\n    open('/app/pwned', 'w').write('x'); t = 'WROTE'\n"
        "except OSError as e:\n    t = 'BLOCKED ' + type(e).__name__"
    )
    out = run_job(code)
    assert out["ok"] and out["title"].startswith("BLOCKED"), out


def test_runner_runs_as_app_user_without_engine_socket():
    code = chart(f"import os\nt = str(os.getuid()) + ' ' + str([p for p in {ENGINE_SOCKETS!r} if os.path.exists(p)])")
    out = run_job(code)
    assert out == {"ok": True, "title": "10001 []"}, out


@pytest.mark.parametrize("service", ["report-agent", "chat-api", "chart-runner"])
def test_no_engine_socket_in_any_service(service):
    result = exec_in(service, f"import os; print([p for p in {ENGINE_SOCKETS!r} if os.path.exists(p)])")
    assert result.stdout.strip() == "[]", result.stdout + result.stderr


def test_runaway_job_is_killed():
    out = run_job("while True:\n    pass")
    assert not out["ok"] and "exceeded" in out["error"], out
