"""ASI04 CI check: AGT mcp-scan against the live health-mcp server, from inside chat-api's container (offline mode).

    podman exec -i biotrackr-solution-chat-api-1 python - < scripts/ci_mcp_scan.py

health-mcp accepts only Host: health-mcp:8001 and an OBO token, so the scan runs on the Compose network with a
stage-only token from local-issuer (alice, Health.Read). Fails closed: exit 1 unless the server was inspected,
every tool in the descriptor lock was scanned, and nothing was flagged. health-mcp itself checks the descriptors
against policies/mcp_tools.lock.json at startup.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import httpx

LOCK = Path(os.environ.get("POLICY_DIR", "/app/policies")) / "mcp_tools.lock.json"


def main() -> int:
    expected_tools = len(json.loads(LOCK.read_text())["tools"])
    base = os.environ["LOCAL_ISSUER_URL"]
    user = httpx.get(f"{base}/token", params={"user": "alice"}, timeout=15.0).json()["access_token"]
    response = httpx.get(
        f"{base}/AuthorizationHeader/HealthMcp",
        params={"AgentIdentity": os.environ["CHAT_AGENT_APP_ID"]},
        headers={"Authorization": f"Bearer {user}"},
        timeout=15.0,
    )
    response.raise_for_status()
    config = {
        "mcpServers": {
            "health-mcp": {
                "url": os.environ["MCP_URL"],
                "headers": {"Authorization": response.json()["authorizationHeader"]},
            }
        }
    }
    path = "/tmp/mcp-scan.json"  # noqa: S108 - the container's private tmpfs
    with open(path, "w") as handle:
        json.dump(config, handle)
    scan = subprocess.run(  # noqa: S603
        [str(Path(sys.executable).with_name("mcp-scan")), "scan", path, "--format", "json"],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    os.remove(path)
    try:
        report = json.loads(scan.stdout)
    except ValueError:
        print(f"mcp-scan printed no JSON (exit {scan.returncode}): {scan.stderr[-500:]}", file=sys.stderr)
        return 1
    summary = report.get("summary", {})
    server = report.get("servers", {}).get("health-mcp", {})
    inspection = report.get("inspections", {}).get("health-mcp", {})
    print(json.dumps({"summary": summary, "server": server, "inspection_ok": inspection.get("ok")}, indent=2))
    problems = []
    if scan.returncode != 0:
        problems.append(f"mcp-scan exit {scan.returncode}")
    if not inspection.get("ok"):
        problems.append(f"inspection failed: {inspection.get('error')}")
    if report.get("inspection_errors") or report.get("config_findings"):
        problems.append("inspection errors or config findings")
    if server.get("safe") is not True or summary.get("warnings") or summary.get("critical"):
        problems.append("health-mcp flagged")
    if summary.get("tools_scanned", 0) != expected_tools:
        problems.append(f"{summary.get('tools_scanned', 0)} tools scanned, the descriptor lock has {expected_tools}")
    for problem in problems:
        print(f"FAIL: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
