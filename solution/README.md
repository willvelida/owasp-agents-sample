---
title: Solution (hardened)
description: Hardened Python port of the Biotrackr chat agent, with a marked, tested control for each OWASP Agentic Top 10 risk, slice by slice
ms.date: 2026-10-19
ms.topic: how-to
---

## Overview

The solution keeps the [starter](../starter/README.md)'s file names, so `git diff --no-index starter solution` shows every control. Slice S1 (`s1-identity`) fixes ASI03: alice and bob sign in with Entra, the chat agent reaches the health MCP server on their behalf through an Entra Agent ID, and the MCP server returns only the token owner's data. Slice S2 (`s2-tools`) adds tool governance for ASI01, ASI02, and the runtime half of ASI04 (see [Tool governance](#tool-governance-asi01-asi02-asi04)). It runs in three ways:

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

## Tool governance (ASI01, ASI02, ASI04)

The governance middleware is attached to the `Agent` in [chat_api/agent.py](src/chat_api/agent.py), so AG-UI runs and DevUI runs pass through the same controls. Policy lives in versioned files under [policies/](policies/), which the Containerfile copies into every image (`POLICY_DIR=/app/policies`).

| File | Purpose |
|------|---------|
| [system_prompt.md](policies/system_prompt.md), [system_prompt.sha256](policies/system_prompt.sha256) | Tiered prompt (data with citations, general information, hedged personal observations, refuse diagnosis and medication changes); tool output is untrusted data |
| [governance.yaml](policies/governance.yaml) | Allowlisted tools, denied patterns (`*delete*`), 20 tool calls per conversation, `page_size` at most 50 |
| [blocked_patterns.yaml](policies/blocked_patterns.yaml) | Injection patterns added to AGT `PromptInjectionDetector`'s built-in rules |
| [mcp_tools.lock.json](policies/mcp_tools.lock.json) | SHA-256 of each MCP tool's name, description, and input schema |

The fail-closed contract ([ADR-0019](../docs/adr/0019-fail-closed-control-contract.md)) for S2:

| Control | Where | On detection, error, or breach |
|---------|-------|--------------------------------|
| Input screening | [middleware/input_guard.py](src/chat_api/middleware/input_guard.py) | `MiddlewareFailure` before identity, model, or tool calls. It normalises Unicode, rejects mixed Latin and Cyrillic or Greek words, and screens decoded Base64 runs too |
| Tool batch policy | [middleware/tool_policy.py](src/chat_api/middleware/tool_policy.py) | A chat middleware checks every tool call the model asks for. One unknown or denied tool, an out-of-policy `page_size`, or a budget breach aborts the whole parallel batch before any call starts |
| AGT governance stack | `create_governance_middleware` (audit trail, capability guard, rogue detection) | AGT's `MiddlewareTermination` denials are converted to `MiddlewareFailure` by `FailClosed`, because termination lets sibling calls run |
| Tool result screening | [middleware/tool_result_guard.py](src/chat_api/middleware/tool_result_guard.py) | `MiddlewareFailure`: the result never reaches the model and no further call starts. Clean results are wrapped in `<untrusted-data>` |
| Call budget | [session_store.py](src/chat_api/session_store.py) | Atomic reservation per `oid` and session id |
| Prompt pin | [prompts.py](src/chat_api/prompts.py) | chat-api exits non-zero at startup |
| MCP descriptor pin | [health_mcp/server.py](src/health_mcp/server.py), [mcp_pinning.py](src/chat_api/mcp_pinning.py) | health-mcp exits with code 3 at startup; chat-api fails the run before the model call on any `tools/list` that differs |
| MCP arguments | [health_mcp/tools.py](src/health_mcp/tools.py) | `{"error": ...}` without a Cosmos DB query for bad dates, reversed ranges, or ranges over 31 days; `page_size` clamped to 1..50 |
| Notes withheld | [health_mcp/tools.py](src/health_mcp/tools.py) | Free-text `notes` never leave the MCP server; results carry `has_note: true` ([ADR-0020](../docs/adr/0020-indirect-injection-containment.md)) |

`delete_records` is gone, and tool descriptions are static. The starter's `rugpull.env` has no effect here: Compose loads it for health-mcp, but the descriptors still match the lock.

> [!NOTE]
> AGT 5.0's `create_governance_middleware(policy=GovernancePolicy(...))` path needs the ACS engine, which ships for Linux x86_64 only. The solution uses the adapter's allow-list path and `PromptInjectionDetector`, which run on arm64 and Windows too.

The AG-UI endpoint never sends exception text to clients. A blocked run ends with `RUN_ERROR` code `MiddlewareFailure`; the reason is in the chat-api log.

After a reviewed change to a tool or to the prompt, regenerate the pins:

```powershell
uv run python -m governance.descriptors --write
(Get-FileHash policies/system_prompt.md -Algorithm SHA256).Hash.ToLower() + "  system_prompt.md" | Set-Content -NoNewline policies/system_prompt.sha256
```

[.gitattributes](../.gitattributes) checks the policy files out with LF on every platform, so the prompt hash is the same everywhere.

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

| Risk  | Where                                             | Control                                                                             |
|-------|---------------------------------------------------|-------------------------------------------------------------------------------------|
| ASI01 | `policies/system_prompt.md`, `src/chat_api/prompts.py` | (S2) Tiered, hash-pinned prompt; tool output treated as untrusted data         |
| ASI01 | `src/chat_api/middleware/input_guard.py`, `screening.py` | (S2) AGT injection screening on input, fail closed                           |
| ASI01 | `src/chat_api/middleware/tool_result_guard.py`    | (S2) Every tool result screened; abort on detection; clean results wrapped          |
| ASI01 | `src/health_mcp/tools.py`                         | (S2) Notes withheld; `has_note` flag only                                           |
| ASI02 | `policies/governance.yaml`, `src/chat_api/middleware/tool_policy.py` | (S2) Allowlist, denied patterns, `page_size` policy, whole-batch abort |
| ASI02 | `src/chat_api/session_store.py`                   | (S2) Atomic 20-call budget per `oid` and session                                    |
| ASI02 | `src/health_mcp/tools.py`, `repository.py`        | (S2) Read tools only; date and range validation; `page_size` clamped                |
| ASI03 | `src/auth_common/jwt_validator.py`                | One issuer per `IDENTITY_MODE`; audience, scope, client, tenant, expiry, `oid`      |
| ASI03 | `src/chat_api/auth.py`, `app.py`                  | Inbound JWT on every route; threads scoped to `oid`; `/conversations` owner-only    |
| ASI03 | `src/chat_api/identity.py`, `agent.py`            | OBO as the chat agent identity; fails closed before the model call                  |
| ASI03 | `src/chat_api/history.py`                         | Refuses to load or append to another user's session                                 |
| ASI03 | `src/health_mcp/auth.py`, `tools.py`              | Token verifier (`aud`, `Health.Read`, `azp`); no `user_id` parameter                |
| ASI03 | `src/auth_common/azure_credential.py`, `agent.py` | Entra for Foundry and Cosmos DB; the key is used only for the plain-HTTP emulator   |
| ASI03 | `compose.yaml`, `infra/`                          | Sidecar on loopback only; internal MCP ingress; keyless Foundry and Cosmos DB       |
| ASI03 | `src/local_issuer/app.py`                         | Stage-only simulator: offline profile, 127.0.0.1, refuses Azure markers             |
| ASI04 | `pyproject.toml`, `uv.lock`, `Containerfile`      | Exact pins, hashed lock, `uv sync --frozen`                                         |
| ASI04 | `policies/mcp_tools.lock.json`, `src/governance/descriptors.py`, `src/chat_api/mcp_pinning.py` | (S2) MCP descriptor pinning at server startup and on every `tools/list` |

## Test

```powershell
uv run ruff check
uv run pytest                                                 # unit tests, no network
$env:RUN_INTEGRATION = "1"; uv run pytest tests/integration    # against the running entra-mode stack
```

The unit tests cover the fail-closed contract. S1: 401 with zero agent runs, MCP 401 with zero Cosmos queries, alice's token never reading bob's records, and the simulator's negative cases. S2: input screening with zero model and tool calls; a poisoned tool result with no further model or tool call; denied, unknown, and out-of-policy calls and budget breaches aborting whole parallel batches (streaming and non-streaming); concurrent budget reservations; prompt and descriptor tampering exiting non-zero in a subprocess; and the governed agent against the real MCP server in process. The integration tests check that health-mcp cannot reach the sidecar and that `DefaultAzureCredential` gets a Foundry token inside chat-api.
