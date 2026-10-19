"""Biotrackr health tools: four domains by three access patterns, read only."""

from datetime import date
from typing import Any, Protocol

from mcp.server.fastmcp import FastMCP

from health_mcp.auth import current_oid

DOMAINS = ("activity", "food", "sleep", "vitals")
MAX_PAGE_SIZE = 50
MAX_RANGE_DAYS = 31


class Repository(Protocol):
    async def by_date(self, user_id: str, document_type: str, date: str) -> list[dict[str, Any]]: ...
    async def by_date_range(
        self, user_id: str, document_type: str, start: str, end: str, page: int, page_size: int
    ) -> list[dict[str, Any]]: ...
    async def records(self, user_id: str, document_type: str, page: int, page_size: int) -> list[dict[str, Any]]: ...


class InvalidArgument(ValueError):
    pass


def register_tools(mcp: FastMCP, repo: Repository) -> None:
    # ASI02: read tools only. No delete_records: a destructive admin tool does not belong on a chat agent's server.
    for domain in DOMAINS:
        _register_domain(mcp, repo, domain)


def _parse_date(value: str, name: str) -> date:
    # ASI02: strict yyyy-MM-dd before any query.
    if len(value) != 10:
        raise InvalidArgument(f"{name} must be yyyy-MM-dd")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise InvalidArgument(f"{name} must be yyyy-MM-dd") from exc


def _paging(page: int, page_size: int) -> tuple[int, int]:
    # ASI02: page_size clamped to 1..50, so no single call can pull a user's whole history.
    return max(page, 1), min(max(page_size, 1), MAX_PAGE_SIZE)


def withhold_notes(item: Any) -> Any:
    """ASI01 (ADR-0020): free-text notes never reach the model; the result only says a note exists."""
    if isinstance(item, dict):
        out: dict[str, Any] = {}
        for key, value in item.items():
            if key == "notes":
                out["has_note"] = bool(value)
            else:
                out[key] = withhold_notes(value)
        return out
    if isinstance(item, list):
        return [withhold_notes(v) for v in item]
    return item


def _items(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"items": withhold_notes(rows)}


def _register_domain(mcp: FastMCP, repo: Repository, domain: str) -> None:
    # ASI03: no user_id parameter; the user is the validated token's oid.
    # ASI02: invalid arguments return {"error": ...} without touching Cosmos DB.

    async def by_date(date: str) -> dict[str, Any]:
        try:
            _parse_date(date, "date")
        except InvalidArgument as exc:
            return {"error": str(exc)}
        return _items(await repo.by_date(current_oid(), domain, date))

    async def by_date_range(start_date: str, end_date: str, page: int = 1, page_size: int = 20) -> dict[str, Any]:
        try:
            start, end = _parse_date(start_date, "start_date"), _parse_date(end_date, "end_date")
            if start > end:
                raise InvalidArgument("start_date must not be after end_date")
            if (end - start).days + 1 > MAX_RANGE_DAYS:
                raise InvalidArgument(f"the range must be at most {MAX_RANGE_DAYS} days")
        except InvalidArgument as exc:
            return {"error": str(exc)}
        page, page_size = _paging(page, page_size)
        return _items(await repo.by_date_range(current_oid(), domain, start_date, end_date, page, page_size))

    async def records(page: int = 1, page_size: int = 20) -> dict[str, Any]:
        page, page_size = _paging(page, page_size)
        return _items(await repo.records(current_oid(), domain, page, page_size))

    # ASI04: static descriptions, pinned in policies/mcp_tools.lock.json; nothing can override them at deploy time.
    mcp.tool(
        name=f"get_{domain}_by_date",
        description=f"Get the signed-in user's {domain} data on one date (yyyy-MM-dd).",
    )(by_date)
    mcp.tool(
        name=f"get_{domain}_by_date_range",
        description=(
            f"Get the signed-in user's {domain} data from start_date to end_date (yyyy-MM-dd, at most "
            f"{MAX_RANGE_DAYS} days), paged with page_size 1 to {MAX_PAGE_SIZE}."
        ),
    )(by_date_range)
    mcp.tool(
        name=f"get_{domain}_records",
        description=(
            f"Get the signed-in user's most recent {domain} records, paged with page_size 1 to {MAX_PAGE_SIZE}."
        ),
    )(records)
