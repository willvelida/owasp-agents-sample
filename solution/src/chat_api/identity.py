"""Downstream identity: an on-behalf-of token for the health MCP server.

ASI03: the chat agent never holds a credential that can read health data by itself. For each run it
asks the Agent ID sidecar (entra mode) or the stage-only simulator (local mode, same contract) to
exchange the signed-in user's token for an MCP token as the chat agent identity:
aud = HEALTH_MCP_APP_ID, scp = Health.Read, oid = user, azp = CHAT_AGENT_APP_ID.
"""

import contextvars
import logging
import os

import httpx

from auth_common import identity_mode
from chat_api.auth import Principal

log = logging.getLogger("chat_api.identity")

mcp_authorization: contextvars.ContextVar[str | None] = contextvars.ContextVar("mcp_authorization", default=None)


class IdentityError(Exception):
    pass


class DownstreamTokenProvider:
    def __init__(self, base_url: str | None = None, agent_identity: str | None = None, timeout: float = 15.0) -> None:
        if base_url is None:
            # Both endpoints expose the same /AuthorizationHeader/HealthMcp contract.
            base_url = os.environ["LOCAL_ISSUER_URL"] if identity_mode() == "local" else os.environ["SIDECAR_URL"]
        self.base_url = base_url.rstrip("/")
        self.agent_identity = agent_identity or os.environ["CHAT_AGENT_APP_ID"]
        self._timeout = timeout

    async def health_mcp_header(self, principal: Principal) -> str:
        url = f"{self.base_url}/AuthorizationHeader/HealthMcp"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(
                    url,
                    params={"AgentIdentity": self.agent_identity},
                    headers={"Authorization": f"Bearer {principal.token}"},
                )
        except httpx.HTTPError as exc:
            raise IdentityError(f"identity endpoint unreachable: {exc}") from exc
        if response.status_code != 200:
            raise IdentityError(f"OBO exchange failed with HTTP {response.status_code}: {response.text[:200]}")
        header = response.json().get("authorizationHeader", "")
        if not header.startswith("Bearer "):
            raise IdentityError("OBO exchange returned no bearer header")
        return header

    async def report_api_header(self) -> str:
        """ASI07: an app-only token for the report agent (aud = REPORT_API_APP_ID, role Report.Generate).

        The report agent never sees user data access rights: no user token is sent, so this is the
        sidecar's autonomous endpoint, not OBO.
        """
        url = f"{self.base_url}/AuthorizationHeaderUnauthenticated/ReportApi"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(url, params={"AgentIdentity": self.agent_identity})
        except httpx.HTTPError as exc:
            raise IdentityError(f"identity endpoint unreachable: {exc}") from exc
        if response.status_code != 200:
            raise IdentityError(f"report API token request failed with HTTP {response.status_code}")
        header = response.json().get("authorizationHeader", "")
        if not header.startswith("Bearer "):
            raise IdentityError("report API token request returned no bearer header")
        return header


def mcp_headers(_: dict) -> dict[str, str]:
    """header_provider for MCPStreamableHTTPTool. Without an OBO header the MCP server returns 401."""
    header = mcp_authorization.get()
    return {"Authorization": header} if header else {}
