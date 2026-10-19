"""Cosmos DB access for the health MCP server."""

import os
from typing import Any

from azure.cosmos.aio import ContainerProxy, CosmosClient

from auth_common.azure_credential import cosmos_credential


class HealthRepository:
    def __init__(self) -> None:
        endpoint = os.environ.get("COSMOS_ENDPOINT", "http://localhost:8081")
        self._client = CosmosClient(
            endpoint,
            # ASI03: Entra identity (managed identity on Azure); the key is used only for the local emulator.
            credential=cosmos_credential(endpoint),
            enable_endpoint_discovery=False,
        )
        self._container: ContainerProxy = self._client.get_database_client(
            os.environ.get("COSMOS_DATABASE", "biotrackr")
        ).get_container_client("health")

    async def _query(self, query: str, params: list[dict[str, Any]], user_id: str) -> list[dict[str, Any]]:
        items = self._container.query_items(query, parameters=params, partition_key=user_id)
        return [_strip(item) async for item in items]

    async def by_date(self, user_id: str, document_type: str, date: str) -> list[dict[str, Any]]:
        return await self._query(
            "SELECT * FROM c WHERE c.userId = @u AND c.documentType = @t AND c.date = @d",
            [{"name": "@u", "value": user_id}, {"name": "@t", "value": document_type}, {"name": "@d", "value": date}],
            user_id,
        )

    async def by_date_range(
        self, user_id: str, document_type: str, start: str, end: str, page: int, page_size: int
    ) -> list[dict[str, Any]]:
        return await self._query(
            "SELECT * FROM c WHERE c.userId = @u AND c.documentType = @t AND c.date >= @s AND c.date <= @e "
            "ORDER BY c.date OFFSET @o LIMIT @l",
            [
                {"name": "@u", "value": user_id},
                {"name": "@t", "value": document_type},
                {"name": "@s", "value": start},
                {"name": "@e", "value": end},
                {"name": "@o", "value": max(page - 1, 0) * page_size},
                {"name": "@l", "value": page_size},
            ],
            user_id,
        )

    async def records(self, user_id: str, document_type: str, page: int, page_size: int) -> list[dict[str, Any]]:
        return await self._query(
            "SELECT * FROM c WHERE c.userId = @u AND c.documentType = @t ORDER BY c.date DESC OFFSET @o LIMIT @l",
            [
                {"name": "@u", "value": user_id},
                {"name": "@t", "value": document_type},
                {"name": "@o", "value": max(page - 1, 0) * page_size},
                {"name": "@l", "value": page_size},
            ],
            user_id,
        )

    async def close(self) -> None:
        await self._client.close()


def _strip(item: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in item.items() if not k.startswith("_")}
