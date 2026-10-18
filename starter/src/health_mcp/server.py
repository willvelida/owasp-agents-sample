"""Health MCP server over streamable HTTP."""

import os

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from health_mcp.repository import HealthRepository
from health_mcp.tools import register_tools

# ASI03 (starter): no token_verifier and no auth settings, so any caller can invoke any tool.
mcp = FastMCP(
    "biotrackr-health",
    host=os.environ.get("MCP_HOST", "0.0.0.0"),
    port=int(os.environ.get("MCP_PORT", "8001")),
    stateless_http=True,
)
register_tools(mcp, HealthRepository())


@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


def main() -> None:
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
