"""Load data/seed into Cosmos DB, keyed by each user's Entra object id."""

import json
import logging
import os
import time
from pathlib import Path

from azure.core.exceptions import ServiceRequestError
from azure.cosmos import CosmosClient, DatabaseProxy, PartitionKey
from azure.cosmos.exceptions import CosmosHttpResponseError

from auth_common.azure_credential import cosmos_credential, is_emulator

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
log = logging.getLogger("seed")

DOMAINS = ("activity", "food", "sleep", "vitals")


def user_oids() -> dict[str, str]:
    # ASI03: partitions are keyed by the token oid, the only user identifier the MCP server trusts.
    return {"alice": os.environ["ALICE_OID"], "bob": os.environ["BOB_OID"]}


def connect(endpoint: str) -> CosmosClient:
    credential = cosmos_credential(endpoint, aio=False)
    for attempt in range(1, 31):
        try:
            client = CosmosClient(endpoint, credential=credential, enable_endpoint_discovery=False)
            if is_emulator(endpoint):
                list(client.list_databases())
            return client
        except (ServiceRequestError, CosmosHttpResponseError) as exc:
            log.info("waiting for Cosmos DB (attempt %d): %s", attempt, exc)
            time.sleep(2)
    raise RuntimeError(f"Cosmos DB not reachable at {endpoint}")


def database(client: CosmosClient, endpoint: str) -> DatabaseProxy:
    name = os.environ.get("COSMOS_DATABASE", "biotrackr")
    if not is_emulator(endpoint):
        # On Azure, Bicep owns the database and containers; Entra data-plane roles cannot create them.
        return client.get_database_client(name)
    db = client.create_database_if_not_exists(name)
    db.create_container_if_not_exists("health", partition_key=PartitionKey(path="/userId"))
    # ASI06 (starter): no default TTL, so conversations (and anything poisoned in them) live forever.
    db.create_container_if_not_exists("conversations", partition_key=PartitionKey(path="/sessionId"))
    return db


def main() -> None:
    seed_dir = Path(os.environ.get("SEED_DIR", "../data/seed"))
    endpoint = os.environ.get("COSMOS_ENDPOINT", "http://localhost:8081")
    oids = user_oids()
    db = database(connect(endpoint), endpoint)
    health = db.get_container_client("health")

    for user in json.loads((seed_dir / "users.json").read_text(encoding="utf-8")):
        oid = oids[user["userId"]]
        health.upsert_item(
            {**user, "id": f"{oid}-profile", "documentType": "profile", "userId": oid, "userName": user["userId"]}
        )

    total = 0
    for domain in DOMAINS:
        for doc in json.loads((seed_dir / f"{domain}.json").read_text(encoding="utf-8")):
            health.upsert_item({**doc, "userId": oids[doc["userId"]]})
            total += 1
    log.info("seeded %d health documents into %s for %s", total, db.id, ", ".join(oids))


if __name__ == "__main__":
    main()
