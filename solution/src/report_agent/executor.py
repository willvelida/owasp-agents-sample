"""Sends checked chart code to the isolated chart runner. Code never runs in this process (ASI05).

Locally the runner is a prestarted container with no network, reached over a Unix socket on a dedicated
volume. On Azure it is a Dynamic Sessions custom-container pool with egress disabled, called with the
report agent's managed identity; every job gets a fresh session that is stopped afterwards.
"""

import base64
import binascii
import logging
import os
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

log = logging.getLogger("report_agent.executor")

RUNNER_TIMEOUT_SECONDS = 20.0
MAX_PNG_BYTES = 1_000_000
MAX_TEXT_CHARS = 200
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
SESSIONS_SCOPE = "https://dynamicsessions.io/.default"
SESSIONS_API_VERSION = "2025-02-02-preview"


class RunnerError(Exception):
    """The runner refused the job, the code failed, or the output was not a valid chart."""


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


class ChartRunner(Protocol):
    async def run(self, code: str, data: list[dict[str, Any]]) -> ChartResult: ...


def parse_result(payload: Any) -> ChartResult:
    if not isinstance(payload, dict):
        raise RunnerError("runner returned no result")
    if not payload.get("ok"):
        raise RunnerError(str(payload.get("error") or "chart code failed")[:MAX_TEXT_CHARS])
    try:
        png = base64.b64decode(str(payload.get("png_base64", "")), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise RunnerError("runner returned an invalid image") from exc
    if not png.startswith(PNG_MAGIC) or len(png) > MAX_PNG_BYTES:
        raise RunnerError("runner output is not a PNG under the size cap")
    return ChartResult(
        title=str(payload.get("title", ""))[:MAX_TEXT_CHARS],
        caption=str(payload.get("caption", ""))[:MAX_TEXT_CHARS],
        png=png,
    )


class UnixSocketRunner:
    def __init__(self, socket_path: str, timeout: float = RUNNER_TIMEOUT_SECONDS) -> None:
        self.socket_path = socket_path
        self.timeout = timeout

    async def run(self, code: str, data: list[dict[str, Any]]) -> ChartResult:
        transport = httpx.AsyncHTTPTransport(uds=self.socket_path)
        try:
            async with httpx.AsyncClient(transport=transport, timeout=self.timeout) as client:
                response = await client.post("http://chart-runner/run", json={"code": code, "data": data})
        except httpx.HTTPError as exc:
            raise RunnerError(f"chart runner unavailable: {type(exc).__name__}") from exc
        if response.status_code != 200:
            raise RunnerError(f"chart runner returned HTTP {response.status_code}")
        return parse_result(response.json())


class DynamicSessionsRunner:
    def __init__(self, endpoint: str, credential: Any, timeout: float = RUNNER_TIMEOUT_SECONDS) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.credential = credential
        self.timeout = timeout

    async def run(self, code: str, data: list[dict[str, Any]]) -> ChartResult:
        identifier = f"chart-{uuid.uuid4().hex}"
        try:
            token = await self.credential.get_token(SESSIONS_SCOPE)
        except Exception as exc:
            raise RunnerError(f"no token for chart sessions: {type(exc).__name__}") from exc
        headers = {"Authorization": f"Bearer {token.token}"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout, headers=headers) as client:
                try:
                    response = await client.post(
                        f"{self.endpoint}/run", params={"identifier": identifier}, json={"code": code, "data": data}
                    )
                finally:
                    # A fresh session per job; stop it so nothing a job leaves behind outlives it.
                    try:
                        await client.post(
                            f"{self.endpoint}/.management/stopSession",
                            params={"identifier": identifier, "api-version": SESSIONS_API_VERSION},
                        )
                    except httpx.HTTPError as exc:
                        log.warning("could not stop session %s: %s", identifier, type(exc).__name__)
        except httpx.HTTPError as exc:
            raise RunnerError(f"chart sessions unavailable: {type(exc).__name__}") from exc
        if response.status_code != 200:
            raise RunnerError(f"chart sessions returned HTTP {response.status_code}")
        return parse_result(response.json())


def runner_from_env() -> ChartRunner:
    """Fail closed: with no isolated runner configured the report agent does not start."""
    if socket_path := os.environ.get("CHART_RUNNER_SOCKET"):
        return UnixSocketRunner(socket_path)
    if endpoint := os.environ.get("CHART_SESSIONS_ENDPOINT"):
        from auth_common.azure_credential import azure_credential

        return DynamicSessionsRunner(endpoint, azure_credential())
    raise SystemExit("no isolated chart runner configured (CHART_RUNNER_SOCKET or CHART_SESSIONS_ENDPOINT)")
