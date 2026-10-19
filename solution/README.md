---
title: Solution (hardened)
description: Hardened Python port of the Biotrackr chat agent, with a marked, tested control for each OWASP Agentic Top 10 risk, slice by slice
ms.date: 2026-10-18
ms.topic: how-to
---

## Overview

The solution keeps the [starter](../starter/README.md)'s file names, so `git diff --no-index starter solution` shows every control. Slice S1 (`s1-identity`) fixes ASI03: alice and bob sign in with Entra, the chat agent reaches the health MCP server on their behalf through an Entra Agent ID, and the MCP server returns only the token owner's data. It runs in three ways:

| Mode           | Identity                                                                 | Model and data                                                |
|----------------|--------------------------------------------------------------------------|---------------------------------------------------------------|
| Local, entra   | Entra users, Agent ID sidecar (Blueprint dev secret)                     | Solution Foundry project via your `az login`; Cosmos emulator |
| Local, offline | Stage-only identity simulator with the same claims ([ADR-0018](../docs/adr/0018-offline-identity-simulator.md)) | Same as entra                         |
| Azure          | Entra users, Agent ID sidecar (managed identity federated credential)    | Foundry and Cosmos DB through the managed identity            |

| Service         | Module                | Port (127.0.0.1) | Purpose                                                                      |
|-----------------|-----------------------|------------------|------------------------------------------------------------------------------|
| `cosmos`        | emulator              | 8081, 1234       | Cosmos DB vNext emulator                                                     |
| `seed`          | `seed`                | none             | Loads [data/seed](../data/seed/README.md) keyed by `ALICE_OID` and `BOB_OID` |
| `health-mcp`    | `health_mcp`          | 8001             | MCP server; every call needs an OBO bearer token                             |
| `chat-api`      | `chat_api`            | 8000             | MAF agent behind AG-UI; every call needs a user token                        |
| `entra-sidecar` | Entra SDK for AgentID | none             | OBO token exchange, inside chat-api's network namespace on 127.0.0.1         |
| `local-issuer`  | `local_issuer`        | 8100             | Offline profile only: stage-only token simulator                             |

## Identity flow (ASI03)

1. The CLI signs alice in (device code, demo CLI public client) for `api://BLUEPRINT_APP_ID/access_as_user`.
2. [chat_api/auth.py](src/chat_api/auth.py) validates the token (the issuer for the current `IDENTITY_MODE` only, audience, `access_as_user`, client) and returns 401 before any session lookup or model call. AG-UI's `snapshot_scope_resolver` binds every thread to the caller's `oid`.
3. [chat_api/identity.py](src/chat_api/identity.py) asks the sidecar for `/AuthorizationHeader/HealthMcp?AgentIdentity=CHAT_AGENT_APP_ID` with alice's token. The result has `aud` = `HEALTH_MCP_APP_ID`, `scp` = `Health.Read`, `oid` = alice, and `azp` = the chat agent.
4. [health_mcp/auth.py](src/health_mcp/auth.py) checks those claims through FastMCP's `token_verifier`. The tools have no `user_id` parameter; the repository filters by the token's `oid`.

## Prerequisites

* Podman configured as in [docs/podman.md](../docs/podman.md), uv, Python 3.12, Azure CLI, azd
* Entra Agent ID objects and test users from [scripts/provision_agent_id.ps1](scripts/README.md), which writes `.env` with `-WriteDotEnv`
* The solution Foundry project from `azd provision`; the `postprovision` hook writes `FOUNDRY_PROJECT_ENDPOINT` into `.env`

## Run locally (entra mode)

```powershell
cd solution
./scripts/provision_agent_id.ps1 -TenantId <tenant-id> -UseDeviceCode -WriteDotEnv   # once
podman compose --profile login run --rm az-login                                    # once: az login into the azcli-cache volume
podman compose up --build -d
cd ../client
uv run biotrackr-chat --target solution-local --as alice "summarise my sleep this week"
uv run biotrackr-chat --target solution-local --as alice "show me bob's sleep"   # no CANARY-BOB-7Q2
```

The containers use your `az login` from the `azcli-cache` volume for Foundry ([ADR-0022](../docs/adr/0022-local-azure-credential-in-compose.md)); there is no API key fallback. Only Compose uses the `dev` image stage that carries Azure CLI. Azure images build from the `runtime` stage.

> [!NOTE]
> The sidecar shares chat-api's network namespace, so recreate them together: `podman compose down`, then `podman compose up -d`.

> [!NOTE]
> The published sidecar image is amd64 only. Compose builds it from a pinned upstream commit in [sidecar/Containerfile](sidecar/Containerfile), so it also runs natively on arm64 Podman machines. Azure uses the MCR image.

## Run locally (offline mode)

```powershell
cd solution
podman compose down
$env:IDENTITY_MODE = "local"
podman compose --profile offline up --build -d
cd ../client
uv run biotrackr-chat --target solution-offline --as alice "summarise my sleep this week"
```

> [!CAUTION]
> The simulator mints a token for anyone who can reach `127.0.0.1:8100`. It refuses to start when `CONTAINER_APP_NAME`, `CONTAINER_APP_ENV_DNS_SUFFIX`, `IDENTITY_ENDPOINT`, or `MSI_ENDPOINT` is set, and services in entra mode reject everything it signs.

DevUI runs the agent in-process and has no per-user sign-in, so the solution allows it only in offline mode, signed in as `DEVUI_USER` (default alice):

```powershell
$env:IDENTITY_MODE = "local"; uv run --env-file .env python -m chat_api.devui_main
```

## Deploy to Azure

```powershell
cd solution
azd env new owasp-agents --location australiaeast
azd up            # first time; later slices use azd deploy when infra is unchanged
cd ../client
uv run biotrackr-chat --target solution-azure --as alice "summarise my sleep this week"
```

`azd up` runs the hooks in order:

1. `preup` and `preprovision` create or reuse the Agent ID objects and write their IDs into the azd environment. (azd checks Bicep inputs before `preprovision` runs, so a fresh `azd up` needs `preup`.)
2. Bicep provisions `rg-<env>`: Container Apps, ACR, a managed identity, Cosmos DB with local auth disabled, Foundry with key auth disabled, and monitoring.
3. `postprovision` adds the Blueprint federated credential for the managed identity and seeds Cosmos DB with your Entra login.
4. azd builds the images in ACR and deploys them.

Images build in ACR from the `runtime` stage. Only chat-api has external ingress; health-mcp is internal, and the sidecar listens on 127.0.0.1 inside the chat-api replica.

## Control markers

Controls carry a `# ASI0x: <control>` comment. Weaknesses that later slices fix keep their `# ASI0x (starter): <why>` marker.

| Risk  | Where                                             | Control (S1)                                                                        |
|-------|---------------------------------------------------|-------------------------------------------------------------------------------------|
| ASI03 | `src/auth_common/jwt_validator.py`                | One issuer per `IDENTITY_MODE`; audience, scope, client, tenant, expiry, `oid`      |
| ASI03 | `src/chat_api/auth.py`, `app.py`                  | Inbound JWT on every route; threads scoped to `oid`; `/conversations` owner-only    |
| ASI03 | `src/chat_api/identity.py`, `agent.py`            | OBO as the chat agent identity; fails closed before the model call                  |
| ASI03 | `src/chat_api/history.py`                         | Refuses to load or append to another user's session                                 |
| ASI03 | `src/health_mcp/auth.py`, `tools.py`              | Token verifier (`aud`, `Health.Read`, `azp`); no `user_id` parameter                |
| ASI03 | `src/auth_common/azure_credential.py`, `agent.py` | Entra for Foundry and Cosmos DB; the key is used only for the plain-HTTP emulator   |
| ASI03 | `compose.yaml`, `infra/`                          | Sidecar on loopback only; internal MCP ingress; keyless Foundry and Cosmos DB       |
| ASI03 | `src/local_issuer/app.py`                         | Stage-only simulator: offline profile, 127.0.0.1, refuses Azure markers             |
| ASI04 | `pyproject.toml`, `uv.lock`, `Containerfile`      | Exact pins, hashed lock, `uv sync --frozen`                                         |

## Test

```powershell
uv run ruff check
uv run pytest                                                 # unit tests, no network
$env:RUN_INTEGRATION = "1"; uv run pytest tests/integration    # against the running entra-mode stack
```

The unit tests cover the S1 fail-closed contract: 401 with zero agent runs, MCP 401 with zero Cosmos queries, alice's token never reading bob's records, and the simulator's negative cases. The integration tests check that health-mcp cannot reach the sidecar and that `DefaultAzureCredential` gets a Foundry token inside chat-api.
