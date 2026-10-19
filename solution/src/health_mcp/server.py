"""Health MCP server over streamable HTTP."""

import asyncio
import logging
import os
from typing import Any, cast

from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse

from auth_common import issuer_for_mode
from governance import PolicyError, descriptors
from health_mcp.auth import REQUIRED_SCOPE, HealthTokenVerifier, build_validator
from health_mcp.repository import HealthRepository
from health_mcp.tools import Repository, register_tools

log = logging.getLogger("health_mcp.server")


def build_server(repo: Repository, verifier: TokenVerifier, *, issuer_url: str) -> FastMCP:
    port = int(os.environ.get("MCP_PORT", "8001"))
    allowed_hosts = [h.strip() for h in os.environ.get("MCP_ALLOWED_HOSTS", "").split(",") if h.strip()]
    allowed_hosts += ["localhost", f"localhost:{port}", "127.0.0.1", f"127.0.0.1:{port}"]
    # ASI03: every MCP request needs a valid OBO bearer token; the verifier enforces aud, scp, and azp.
    mcp = FastMCP(
        "biotrackr-health",
        host=os.environ.get("MCP_HOST", "0.0.0.0"),
        port=port,
        stateless_http=True,
        token_verifier=verifier,
        auth=AuthSettings(
            issuer_url=issuer_url,
            resource_server_url=os.environ.get("MCP_RESOURCE_URL", f"http://health-mcp:{port}/mcp"),
            required_scopes=[REQUIRED_SCOPE],
            validate_token_resource=False,
        ),
        # Binding to 0.0.0.0 inside a container: keep DNS rebinding protection with explicit hosts.
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=allowed_hosts,
        ),
    )
    register_tools(mcp, repo)

    @mcp.custom_route("/healthz", methods=["GET"])
    async def healthz(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    return mcp


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    logging.getLogger("azure").setLevel(logging.WARNING)
    verify_descriptor_pins()
    mcp = build_server(HealthRepository(), HealthTokenVerifier(build_validator()), issuer_url=issuer_for_mode().issuer)
    mcp.run(transport="streamable-http")


async def registered_tools() -> list[Any]:
    """The tool descriptors this code registers, independent of auth and storage."""
    mcp = FastMCP("biotrackr-health")
    register_tools(mcp, cast(Repository, None))
    return await mcp.list_tools()


def verify_descriptor_pins() -> None:
    """ASI04: refuse to start if any served descriptor differs from policies/mcp_tools.lock.json."""
    try:
        problems = descriptors.mismatches(descriptors.digests(asyncio.run(registered_tools())), descriptors.load_lock())
    except PolicyError as exc:
        problems = [str(exc)]
    if problems:
        for problem in problems:
            log.critical("MCP descriptor pin mismatch: %s", problem)
        raise SystemExit(3)
    log.info("MCP tool descriptors match the lock")


if __name__ == "__main__":
    main()
