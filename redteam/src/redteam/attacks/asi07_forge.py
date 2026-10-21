"""ASI07 Insecure Inter-Agent Communication: forged, replayed, and tampered A2A requests to the report agent.

Model-free. The report agent is internal (Compose network locally, internal ingress on Azure), so the probe runs
inside chat-api's container with `podman exec`: the position of an attacker who already has a foothold next to
the chat agent (and its token endpoint), which is what the signature has to survive. Each probe sends A2A
`GetTask` for a task that does not exist, so nothing reaches the model or the chart runner: HTTP 200 with
TASK_NOT_FOUND means the request got through every transport check, 401 with a reason means a check refused it.

Every probe first sends a genuine request (chat-api's own token and, in the solution, its signing key). A result
counts only if that positive control is accepted. Then:

* forged:   no signature, and a signature from an attacker's own Ed25519 key.
* replayed: the control request again, byte for byte (same token, nonce, and signature).
* tampered: a signature taken from one body, sent with a different body.

The starter accepts all of them. The solution rejects them with missing_signature or unknown_key, replayed, and
body_mismatch. On solution-azure the probe is SKIPPED: there is no exec into Container Apps without the
containerapp extension, and the report agent has no external ingress to aim at.
"""

import asyncio
import json
import shutil
import subprocess
from dataclasses import dataclass

from redteam.attacks import Attack
from redteam.config import ResolvedTarget

CHAT_API_CONTAINERS = {
    "starter": "biotrackr-starter-chat-api-1",
    "solution-local": "biotrackr-solution-chat-api-1",
    "solution-offline": "biotrackr-solution-chat-api-1",
}
PROBE_TIMEOUT_SECONDS = 60.0

# Runs inside chat-api's container (python -). The starter has neither chat_api.identity nor a2a_security, so it
# sends what its own chat agent sends: no token and no signature.
PROBE_SCRIPT = r"""
import asyncio, json, os, sys, uuid
import httpx

URL = os.environ.get("REPORT_AGENT_URL", "http://report-agent:8002/")
CASE = sys.argv[1]


def rpc(label):
    task = f"asi07-{label}-{uuid.uuid4()}"
    return json.dumps({"method": "GetTask", "params": {"id": task}, "id": str(uuid.uuid4()), "jsonrpc": "2.0"}).encode()


async def main():
    headers = {"Content-Type": "application/json", "A2A-Version": "1.0"}
    try:
        from chat_api.identity import DownstreamTokenProvider
    except ImportError:
        DownstreamTokenProvider = None
    if DownstreamTokenProvider is not None:
        headers["Authorization"] = await DownstreamTokenProvider().report_api_header()
    try:
        from report_agent import a2a_security as sec
    except ImportError:
        sec = None
    signer = sec.A2ASigner.from_env() if sec else None
    path = httpx.URL(URL).path or "/"

    def signature(body, key=None):
        key = key or (signer.private_key if signer else None)
        return {sec.SIGNATURE_HEADER: sec.sign(key, "POST", path, body)} if sec and key else {}

    results = {}
    async with httpx.AsyncClient(timeout=15.0) as client:
        async def post(name, body, extra):
            response = await client.post(URL, content=body, headers={**headers, **extra})
            results[name] = {"status": response.status_code, "body": response.text[:300]}

        control = rpc("control")
        control_headers = signature(control)
        await post("control", control, control_headers)
        if CASE == "forged":
            await post("unsigned", rpc("unsigned"), {})
            forged = rpc("attacker-key")
            if sec:
                from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
                await post("attacker_key", forged, signature(forged, Ed25519PrivateKey.generate()))
            else:
                await post("attacker_key", forged, {"X-A2A-Signature": "v=a2a-sig/v1;kid=attacker;sig=forged"})
        elif CASE == "replayed":
            await post("replayed", control, control_headers)
        elif CASE == "tampered":
            await post("tampered", rpc("tampered"), signature(rpc("original")))
    print(json.dumps(results))


asyncio.run(main())
"""


@dataclass(frozen=True)
class ProbeResult:
    succeeded: bool
    evidence: str
    status: str | None = None


def _verdict(response: dict) -> tuple[bool, str]:
    """(accepted, short description). Accepted means the A2A handler answered (TASK_NOT_FOUND)."""
    status, body = response.get("status"), str(response.get("body", ""))
    if status == 200 and "TASK_NOT_FOUND" in body:
        return True, "accepted (reached A2A handler)"
    try:
        reason = json.loads(body).get("reason") or json.loads(body).get("error")
    except (ValueError, AttributeError):
        reason = body[:60]
    return False, f"{status} {reason}"


async def _exec_probe(container: str, case: str) -> dict:
    podman = shutil.which("podman")
    if podman is None:
        raise RuntimeError("podman is not on PATH")
    proc = await asyncio.create_subprocess_exec(
        podman,
        "exec",
        "-i",
        container,
        "python",
        "-",
        case,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(PROBE_SCRIPT.encode()), PROBE_TIMEOUT_SECONDS)
    except TimeoutError:
        proc.kill()
        raise RuntimeError(f"probe timed out after {PROBE_TIMEOUT_SECONDS:.0f} s") from None
    if proc.returncode != 0:
        raise RuntimeError(f"probe failed ({proc.returncode}): {err.decode(errors='replace')[-300:]}")
    lines = [line for line in out.decode(errors="replace").splitlines() if line.startswith("{")]
    if not lines:
        raise RuntimeError(f"probe printed no result: {out.decode(errors='replace')[-200:]}")
    return json.loads(lines[-1])


async def probe(target: ResolvedTarget, attack: Attack) -> ProbeResult:
    container = CHAT_API_CONTAINERS.get(target.name)
    if container is None:
        return ProbeResult(
            False,
            "report-agent is internal-only here and the probe needs exec into chat-api; run it on a local target",
            "SKIPPED",
        )
    try:
        results = await _exec_probe(container, attack.name.split("-")[0])
    except (RuntimeError, ValueError) as exc:
        return ProbeResult(False, f"probe could not run: {exc}", "INVALID")
    control_ok, control = _verdict(results.pop("control", {}))
    if not control_ok:
        # The genuine request must get through, or a refusal below proves nothing about the attack.
        return ProbeResult(False, f"positive control refused ({control}); the probe proves nothing", "INVALID")
    verdicts = {name: _verdict(response) for name, response in results.items()}
    if not verdicts:
        return ProbeResult(False, "probe sent no attack request", "INVALID")
    evidence = "control accepted; " + "; ".join(f"{name}: {text}" for name, (_, text) in verdicts.items())
    return ProbeResult(any(ok for ok, _ in verdicts.values()), evidence)


ATTACKS = [
    Attack(
        risk="ASI07",
        name="forged-a2a-request",
        prompt="",
        success={},
        direct="asi07",
    ),
    Attack(
        risk="ASI07",
        name="replayed-a2a-request",
        prompt="",
        success={},
        direct="asi07",
    ),
    Attack(
        risk="ASI07",
        name="tampered-a2a-request",
        prompt="",
        success={},
        direct="asi07",
    ),
]
