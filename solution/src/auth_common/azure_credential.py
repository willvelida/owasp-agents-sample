"""Azure credentials for data-plane access.

ASI03: outside the local emulator, services use Entra (managed identity on Azure, the developer's
az login in local Compose) and never an account key.
"""

import os
from typing import Any


def is_emulator(endpoint: str) -> bool:
    # The vNext emulator speaks plain HTTP; real Cosmos DB accounts are always HTTPS.
    return endpoint.startswith("http://")


def cosmos_credential(endpoint: str, *, aio: bool = True) -> Any:
    if is_emulator(endpoint):
        return os.environ["COSMOS_KEY"]
    return azure_credential(aio=aio)


def azure_credential(*, aio: bool = True) -> Any:
    if aio:
        from azure.identity.aio import DefaultAzureCredential as AsyncDefaultAzureCredential

        return AsyncDefaultAzureCredential()
    from azure.identity import DefaultAzureCredential

    return DefaultAzureCredential()
