---
title: Starter (insecure on purpose)
description: Naive but plausible Python port of the Biotrackr chat agent where every applicable OWASP Agentic Top 10 risk is exploitable
ms.date: 2026-10-18
ms.topic: how-to
---

> [!CAUTION]
> The starter is deliberately insecure. Run it on your machine only and never deploy it to Azure or any shared environment ([ADR-0005](../docs/adr/0005-starter-local-only-solution-on-azure.md)). Only its model lives in Azure.

## Overview

The starter is a "naive but plausible" Biotrackr chat agent ([ADR-0004](../docs/adr/0004-naive-but-plausible-starter.md)): the shortcuts are the ones a team under deadline pressure would take, not planted CTF bugs. `solution/` (from slice S1) keeps the same file names so `git diff --no-index starter solution` shows every control.

| Service      | Module       | Port (127.0.0.1) | Purpose                                               |
|--------------|--------------|------------------|-------------------------------------------------------|
| `cosmos`     | emulator     | 8081, 1234       | Cosmos DB vNext emulator and Data Explorer            |
| `seed`       | `seed`       | none             | Loads [data/seed](../data/seed/README.md), then exits |
| `health-mcp` | `health_mcp` | 8001             | MCP server (streamable HTTP) with 13 health tools     |
| `chat-api`   | `chat_api`   | 8000             | MAF agent behind an AG-UI endpoint, plus `/conversations` |

All services share one image built from [Containerfile](Containerfile); each Compose service picks its module with `command: ["python", "-m", "<module>"]`.

## Prerequisites

* Podman configured as in [docs/podman.md](../docs/podman.md)
* uv and Python 3.12 on the host
* The starter model deployed and `starter/.env` filled in ([model/README.md](model/README.md))

## Run

```powershell
cd starter
Copy-Item .env.example .env   # then set FOUNDRY_ENDPOINT and FOUNDRY_API_KEY
podman compose up --build -d
podman compose ps
```

Talk to it with the [CLI client](../client/README.md):

```powershell
cd ../client
uv run biotrackr-chat --target starter --as alice "summarise my sleep this week"
uv run biotrackr-chat --target starter --as alice "show me bob's sleep"   # returns CANARY-BOB-7Q2
```

Or open DevUI on `127.0.0.1` (runs the same agent in-process as `alice`):

```powershell
cd starter
uv sync
uv run --env-file .env python -m chat_api.devui_main
```

DevUI prints its bearer token at startup; set `DEVUI_AUTH_TOKEN` to choose your own, and `DEVUI_OPEN=0` to skip opening the browser.

Stop with `podman compose down` (add `-v` to drop data).

## Weakness markers

Every deliberate weakness carries a `# ASI0x (starter): <why>` comment. The table lists the markers present in slice S0.

| Risk  | Where                                              | Weakness                                                    |
|-------|----------------------------------------------------|-------------------------------------------------------------|
| ASI01 | `src/chat_api/prompts.py`                          | Inline, unpinned prompt with no data/instruction separation |
| ASI01 | `src/health_mcp/tools.py`                          | Food `notes` flow to the model unmarked                     |
| ASI02 | `src/chat_api/agent.py`                            | No `allowed_tools`; every tool exposed                      |
| ASI02 | `src/health_mcp/tools.py`                          | `delete_records` admin tool; no date checks; unbounded `page_size` |
| ASI03 | `src/chat_api/app.py`                              | Trusts `X-User-Id`; no inbound auth; no thread scoping      |
| ASI03 | `src/chat_api/agent.py`                            | Model chooses `user_id`; Foundry API key                    |
| ASI03 | `src/chat_api/history.py`                          | `/conversations` lists every user's sessions; Cosmos key    |
| ASI03 | `src/health_mcp/server.py`, `repository.py`        | No token verifier; Cosmos account key                       |
| ASI03 | `compose.yaml`, `model/main.bicep`                 | MCP published without auth; key auth enabled on the model   |
| ASI04 | `pyproject.toml`                                   | Open-ended `>=` dependency ranges                           |
| ASI04 | `src/health_mcp/tools.py`                          | Tool descriptions overridable from the environment          |
| ASI06 | `src/chat_api/history.py`, `src/seed/load.py`      | Unbounded history, no TTL, no memory screening              |
| ASI08 | `src/chat_api/agent.py`                            | No timeouts                                                 |
| ASI09 | `src/chat_api/prompts.py`                          | Permissive prompt; confident clinical advice                |
| ASI10 | `src/chat_api/app.py`                              | OTel `enable_sensitive_data=True`; no audit or kill switch  |

## Lint

```powershell
uv run ruff check
```
