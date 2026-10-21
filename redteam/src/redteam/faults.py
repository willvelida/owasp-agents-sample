"""Fault steps for operational attacks (ASI08, ASI10): change the running stack, run the attack, put it back.

Local targets drive `podman compose` in starter/ or solution/. The Azure target changes live resources, so its faults
run only with --azure-faults (otherwise the attack is SKIPPED):

* stop-health-mcp: `podman compose stop health-mcp`, or stop the health-mcp container app; restored and waited for,
                   then one request closes the solution's half-open circuit breaker before the next attack.
* kill-switch:     solution only. Recreates chat-api with AGENT_KILL_SWITCH=on, or sets the App Configuration key.
                   The starter has no kill switch, so there is nothing to flip.
"""

import asyncio
import json
import os
import shutil
import subprocess
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx

from redteam.config import ResolvedTarget

REPO = Path(__file__).resolve().parents[3]
LOCAL_STACKS = {"starter": REPO / "starter", "solution-local": REPO / "solution", "solution-offline": REPO / "solution"}
SOLUTION = REPO / "solution"
# The solution's circuit breaker stays open for 30 s after the outage; let it close before the next attack.
BREAKER_COOLDOWN_SECONDS = 35.0
# The App Configuration kill switch is cached for 10 s in chat-api.
APP_CONFIG_CACHE_SECONDS = 12.0
KILL_SWITCH_KEY = "agent-kill-switch"


class FaultError(RuntimeError):
    pass


@dataclass
class FaultContext:
    target: ResolvedTarget
    azure_allowed: bool
    note: str = ""


async def _run(*args: str, cwd: Path | None = None, env: dict[str, str] | None = None) -> str:
    executable = shutil.which(args[0])
    if executable is None:
        raise FaultError(f"{args[0]} is not on PATH")
    proc = await asyncio.create_subprocess_exec(
        executable,
        *args[1:],
        cwd=cwd,
        env={**os.environ, **(env or {})},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    text = out.decode("utf-8", errors="replace")
    if proc.returncode != 0:
        raise FaultError(f"{' '.join(args[:4])} failed ({proc.returncode}): {text[-400:]}")
    return text


async def _compose(target: str, *args: str, env: dict[str, str] | None = None) -> str:
    profile = ["--profile", "offline"] if target == "solution-offline" else []
    extra = {"IDENTITY_MODE": "local"} if target == "solution-offline" else {}
    return await _run("podman", "compose", *profile, *args, cwd=LOCAL_STACKS[target], env={**extra, **(env or {})})


async def _wait_healthy(target: str, service: str, within: float = 240.0) -> None:
    deadline = asyncio.get_running_loop().time() + within
    while asyncio.get_running_loop().time() < deadline:
        out = await _compose(target, "ps", "--format", "json", service)
        text = out.strip()
        rows = (
            json.loads(text)
            if text.startswith("[")
            else [json.loads(x) for x in text.splitlines() if x.startswith("{")]
        )
        if rows and all(r.get("Health") == "healthy" for r in rows):
            return
        await asyncio.sleep(3)
    raise FaultError(f"{service} did not become healthy within {within:.0f} s")


async def _wait_chat_api(url: str, within: float = 240.0) -> None:
    deadline = asyncio.get_running_loop().time() + within
    async with httpx.AsyncClient(timeout=5.0) as client:
        while asyncio.get_running_loop().time() < deadline:
            try:
                if (await client.get(url.rstrip("/") + "/healthz/liveness")).status_code == 200:
                    # The Entra sidecar shares chat-api's network namespace and starts a moment later.
                    await asyncio.sleep(5)
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(3)
    raise FaultError(f"chat-api at {url} did not come back within {within:.0f} s")


def _azd(key: str) -> str:
    result = subprocess.run(  # noqa: S603
        [shutil.which("azd") or "azd", "env", "get-value", key, "--cwd", str(SOLUTION)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise FaultError(f"could not read {key} from the azd environment")
    return result.stdout.strip()


async def _container_app(action: str, name: str) -> None:
    subscription = (await _run("az", "account", "show", "--query", "id", "-o", "tsv")).strip()
    group = _azd("AZURE_RESOURCE_GROUP")
    url = (
        f"https://management.azure.com/subscriptions/{subscription}/resourceGroups/{group}"
        f"/providers/Microsoft.App/containerApps/{name}/{action}?api-version=2024-03-01"
    )
    await _run("az", "rest", "--method", "post", "--url", url)


async def _wait_container_app_running(name: str, within: float = 300.0) -> None:
    group = _azd("AZURE_RESOURCE_GROUP")
    deadline = asyncio.get_running_loop().time() + within
    while asyncio.get_running_loop().time() < deadline:
        state = await _run(
            "az",
            "resource",
            "show",
            "-g",
            group,
            "-n",
            name,
            "--resource-type",
            "Microsoft.App/containerApps",
            "--query",
            "properties.runningStatus",
            "-o",
            "tsv",
        )
        if state.strip().lower() == "running":
            return
        await asyncio.sleep(10)
    raise FaultError(f"{name} did not report Running within {within:.0f} s")


async def _kill_switch_azure(value: str) -> None:
    endpoint = _azd("APP_CONFIG_ENDPOINT")
    await _run(
        "az",
        "appconfig",
        "kv",
        "set",
        "--endpoint",
        endpoint,
        "--auth-mode",
        "login",
        "--key",
        KILL_SWITCH_KEY,
        "--value",
        value,
        "--yes",
        "--only-show-errors",
    )
    await asyncio.sleep(APP_CONFIG_CACHE_SECONDS)


async def _close_breaker(target: ResolvedTarget) -> None:
    """After the cooldown the breaker is half-open and admits one trial: send it, so later attacks see it closed."""
    from redteam.targets.biotrackr_target import BiotrackrTarget

    client = BiotrackrTarget(url=target.url, headers=target.headers, timeout=120.0)
    for _ in range(3):
        text = await client.run_async(str(uuid.uuid4()), "How many steps did I take on 2026-10-14?")
        if "[tool] " in text:
            return
        await asyncio.sleep(BREAKER_COOLDOWN_SECONDS)
    raise FaultError("health-mcp is back, but the chat API still cannot run a tool")


@asynccontextmanager
async def stop_health_mcp(ctx: FaultContext) -> AsyncIterator[None]:
    name = ctx.target.name
    if name == "solution-azure":
        await _container_app("stop", "health-mcp")
        await asyncio.sleep(20)
        try:
            yield
        finally:
            await _container_app("start", "health-mcp")
            await _wait_container_app_running("health-mcp")
            await asyncio.sleep(BREAKER_COOLDOWN_SECONDS)
            await _close_breaker(ctx.target)
        return
    await _compose(name, "stop", "health-mcp")
    try:
        yield
    finally:
        await _compose(name, "start", "health-mcp")
        await _wait_healthy(name, "health-mcp")
        if not ctx.target.is_starter:
            await asyncio.sleep(BREAKER_COOLDOWN_SECONDS)
            await _close_breaker(ctx.target)


@asynccontextmanager
async def kill_switch(ctx: FaultContext) -> AsyncIterator[None]:
    name = ctx.target.name
    if ctx.target.is_starter:
        ctx.note = "starter has no kill switch to flip"
        yield
        return
    if name == "solution-azure":
        await _kill_switch_azure("on")
        try:
            yield
        finally:
            await _kill_switch_azure("off")
        return
    await _recreate_chat_api(name, "on")
    await _wait_chat_api(ctx.target.url)
    try:
        yield
    finally:
        await _recreate_chat_api(name, "off")
        await _wait_chat_api(ctx.target.url)


async def _recreate_chat_api(target: str, value: str) -> None:
    env = {"AGENT_KILL_SWITCH": value}
    # The sidecar joins chat-api's network namespace: Podman will not replace chat-api while it exists, and it must
    # join the new container afterwards.
    await _compose(target, "rm", "--stop", "--force", "entra-sidecar", env=env)
    await _compose(target, "up", "-d", "--no-deps", "chat-api", env=env)
    await _compose(target, "up", "-d", "--no-deps", "entra-sidecar", env=env)


FAULTS = {"stop-health-mcp": stop_health_mcp, "kill-switch": kill_switch}


def needs_consent(name: str, target: ResolvedTarget) -> bool:
    return target.name == "solution-azure" and name in FAULTS
