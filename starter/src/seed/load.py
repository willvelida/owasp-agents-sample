"""Load data/seed into the Cosmos DB emulator."""

import json
import logging
import os
import time
from pathlib import Path

from azure.core.exceptions import ServiceRequestError
from azure.cosmos import CosmosClient, PartitionKey
from azure.cosmos.exceptions import CosmosHttpResponseError

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
log = logging.getLogger("seed")

DOMAINS = ("activity", "food", "sleep", "vitals")


def connect() -> CosmosClient:
    endpoint = os.environ.get("COSMOS_ENDPOINT", "http://localhost:8081")
    key = os.environ["COSMOS_KEY"]
    for attempt in range(1, 31):
        try:
            client = CosmosClient(endpoint, credential=key, enable_endpoint_discovery=False)
            list(client.list_databases())
            return client
        except (ServiceRequestError, CosmosHttpResponseError) as exc:
            log.info("waiting for Cosmos DB (attempt %d): %s", attempt, exc)
            time.sleep(2)
    raise RuntimeError(f"Cosmos DB not reachable at {endpoint}")


def main() -> None:
    seed_dir = Path(os.environ.get("SEED_DIR", "../data/seed"))
    client = connect()
    db = client.create_database_if_not_exists(os.environ.get("COSMOS_DATABASE", "biotrackr"))
    health = db.create_container_if_not_exists("health", partition_key=PartitionKey(path="/userId"))
    # ASI06 (starter): no default TTL, so conversations (and anything poisoned in them) live forever.
    db.create_container_if_not_exists("conversations", partition_key=PartitionKey(path="/sessionId"))

    for user in json.loads((seed_dir / "users.json").read_text(encoding="utf-8")):
        health.upsert_item({"id": f"{user['userId']}-profile", "documentType": "profile", **user})

    total = 0
    for domain in DOMAINS:
        for doc in json.loads((seed_dir / f"{domain}.json").read_text(encoding="utf-8")):
            health.upsert_item(doc)
            total += 1
    log.info("seeded %d health documents into %s", total, db.id)


if __name__ == "__main__":
    main()
