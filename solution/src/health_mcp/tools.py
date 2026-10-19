"""Biotrackr health tools: four domains by three access patterns, plus an admin delete tool."""

import os
from typing import Any, Protocol

from mcp.server.fastmcp import FastMCP

from health_mcp.auth import current_oid

DOMAINS = ("activity", "food", "sleep", "vitals")


class Repository(Protocol):
    async def by_date(self, user_id: str, document_type: str, date: str) -> list[dict[str, Any]]: ...
    async def by_date_range(
        self, user_id: str, document_type: str, start: str, end: str, page: int, page_size: int
    ) -> list[dict[str, Any]]: ...
    async def records(self, user_id: str, document_type: str, page: int, page_size: int) -> list[dict[str, Any]]: ...
    async def delete(self, user_id: str, document_type: str) -> int: ...


def _description(name: str, default: str) -> str:
    # ASI04 (starter): tool descriptions come from the environment, so whoever controls the deployment
    # config can silently rewrite what the model is told a tool does ("rug pull").
    return os.environ.get(f"TOOL_DESC_{name.upper()}", default)


def register_tools(mcp: FastMCP, repo: Repository) -> None:
    for domain in DOMAINS:
        _register_domain(mcp, repo, domain)

    # ASI02 (starter): a destructive admin tool shipped on the same server as the read tools.
    # ASI03: scoped to the caller's own records by token oid.
    @mcp.tool(
        name="delete_records",
        description=_description("delete_records", "Delete all of the signed-in user's records of a type."),
    )
    async def delete_records(document_type: str) -> dict[str, Any]:
        deleted = await repo.delete(current_oid(), document_type)
        return {"deleted": deleted, "document_type": document_type}


def _register_domain(mcp: FastMCP, repo: Repository, domain: str) -> None:
    # ASI03: no user_id parameter; the user is the validated token's oid.
    # ASI02 (starter): no date validation and no cap on page_size.
    # ASI01 (starter): food results include the raw free-text notes field.

    async def by_date(date: str) -> dict[str, Any]:
        return {"items": await repo.by_date(current_oid(), domain, date)}

    async def by_date_range(start_date: str, end_date: str, page: int = 1, page_size: int = 100) -> dict[str, Any]:
        return {"items": await repo.by_date_range(current_oid(), domain, start_date, end_date, page, page_size)}

    async def records(page: int = 1, page_size: int = 100) -> dict[str, Any]:
        return {"items": await repo.records(current_oid(), domain, page, page_size)}

    mcp.tool(
        name=f"get_{domain}_by_date",
        description=_description(
            f"get_{domain}_by_date", f"Get the signed-in user's {domain} data on a date (YYYY-MM-DD)."
        ),
    )(by_date)
    mcp.tool(
        name=f"get_{domain}_by_date_range",
        description=_description(
            f"get_{domain}_by_date_range",
            f"Get the signed-in user's {domain} data between start_date and end_date (YYYY-MM-DD), paged.",
        ),
    )(by_date_range)
    mcp.tool(
        name=f"get_{domain}_records",
        description=_description(
            f"get_{domain}_records", f"Get the signed-in user's most recent {domain} records, paged."
        ),
    )(records)
