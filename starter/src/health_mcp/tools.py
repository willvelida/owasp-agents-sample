"""Biotrackr health tools: four domains by three access patterns, plus an admin delete tool."""

import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from health_mcp.repository import HealthRepository

DOMAINS = ("activity", "food", "sleep", "vitals")


def _description(name: str, default: str) -> str:
    # ASI04 (starter): tool descriptions come from the environment, so whoever controls the deployment
    # config can silently rewrite what the model is told a tool does ("rug pull").
    return os.environ.get(f"TOOL_DESC_{name.upper()}", default)


def register_tools(mcp: FastMCP, repo: HealthRepository) -> None:
    for domain in DOMAINS:
        _register_domain(mcp, repo, domain)

    # ASI02 (starter): a destructive admin tool shipped on the same server as the read tools.
    @mcp.tool(
        name="delete_records",
        description=_description("delete_records", "Delete all records of a type (activity, food, sleep, vitals)."),
    )
    async def delete_records(user_id: str, document_type: str) -> dict[str, Any]:
        deleted = await repo.delete(user_id, document_type)
        return {"deleted": deleted, "user_id": user_id, "document_type": document_type}


def _register_domain(mcp: FastMCP, repo: HealthRepository, domain: str) -> None:
    # ASI03 (starter): every tool takes user_id as a plain argument chosen by the model.
    # ASI02 (starter): no date validation and no cap on page_size.
    # ASI01 (starter): food results include the raw free-text notes field.

    async def by_date(user_id: str, date: str) -> dict[str, Any]:
        return {"items": await repo.by_date(user_id, domain, date)}

    async def by_date_range(
        user_id: str, start_date: str, end_date: str, page: int = 1, page_size: int = 100
    ) -> dict[str, Any]:
        return {"items": await repo.by_date_range(user_id, domain, start_date, end_date, page, page_size)}

    async def records(user_id: str, page: int = 1, page_size: int = 100) -> dict[str, Any]:
        return {"items": await repo.records(user_id, domain, page, page_size)}

    mcp.tool(
        name=f"get_{domain}_by_date",
        description=_description(f"get_{domain}_by_date", f"Get {domain} data for a user on a date (YYYY-MM-DD)."),
    )(by_date)
    mcp.tool(
        name=f"get_{domain}_by_date_range",
        description=_description(
            f"get_{domain}_by_date_range",
            f"Get {domain} data for a user between start_date and end_date (YYYY-MM-DD), paged.",
        ),
    )(by_date_range)
    mcp.tool(
        name=f"get_{domain}_records",
        description=_description(f"get_{domain}_records", f"Get the most recent {domain} records for a user, paged."),
    )(records)
