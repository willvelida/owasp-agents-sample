"""Live Compose checks. Run with the entra-mode stack up:

$env:RUN_INTEGRATION = "1"; uv run pytest tests/integration -q
"""

import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("RUN_INTEGRATION") != "1", reason="needs the running Compose stack")

SOLUTION = Path(__file__).resolve().parents[2]

PROBE = """
import urllib.request as u
try:
    u.urlopen(URL, timeout=3)
    print("REACHABLE")
except Exception as e:
    print("BLOCKED", type(e).__name__)
"""


def exec_in(service: str, code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        ["podman", "compose", "exec", "-T", service, "python", "-c", code],  # noqa: S607
        cwd=SOLUTION,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


@pytest.mark.parametrize("url", ["http://chat-api:5000/healthz", "http://entra-sidecar:5000/healthz"])
def test_health_mcp_cannot_reach_sidecar(url):
    result = exec_in("health-mcp", f"URL = {url!r}\n{PROBE}")
    assert "BLOCKED" in result.stdout, result.stdout + result.stderr


def test_chat_api_reaches_sidecar_on_loopback():
    result = exec_in("chat-api", "URL = 'http://127.0.0.1:5000/healthz'\n" + PROBE)
    assert "REACHABLE" in result.stdout, result.stdout + result.stderr


def test_azure_cli_cache_owned_by_app_user():
    result = exec_in("chat-api", "import os; print(os.stat('/home/app/.azure').st_uid)")
    assert result.stdout.strip() == "10001", result.stdout + result.stderr


def test_default_azure_credential_gets_foundry_token():
    # ADR-0022 clean-container token test (needs `podman compose --profile login run --rm az-login` once).
    code = (
        "from azure.identity import DefaultAzureCredential as D;"
        "t = D().get_token('https://cognitiveservices.azure.com/.default'); print('TOKEN', len(t.token) > 100)"
    )
    result = exec_in("chat-api", code)
    assert "TOKEN True" in result.stdout, result.stdout[-500:] + result.stderr[-500:]
