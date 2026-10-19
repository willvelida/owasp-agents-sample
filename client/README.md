---
title: Biotrackr CLI client
description: Command-line AG-UI client for the starter and solution chat APIs, showing streamed text, tool calls, and tool results
ms.date: 2026-10-18
ms.topic: how-to
---

## Overview

`biotrackr-chat` sends a message to a chat API over AG-UI and renders the stream: text deltas, every tool call with its arguments, a preview of each tool result, and run errors. Targets live in [targets.toml](targets.toml).

| Target             | Slice | Auth                                                                       |
|--------------------|-------|----------------------------------------------------------------------------|
| `starter`          | S0    | `X-User-Id` header from `--as` (no token)                                  |
| `solution-local`   | S1    | Entra device code sign-in as the demo CLI, for `api://BLUEPRINT_APP_ID/access_as_user` |
| `solution-offline` | S1    | Token from the stage-only identity simulator on `127.0.0.1:8100`           |
| `solution-azure`   | S1    | Entra, against the URL in the azd environment (`CHAT_API_URL`)              |

The solution targets read `TENANT_ID`, `CLI_APP_ID`, `BLUEPRINT_APP_ID`, and each user's `<USER>_OID` and `<USER>_UPN` from `solution/.env`, which [provision_agent_id.ps1](../solution/scripts/provision_agent_id.ps1) writes with `-WriteDotEnv`.

## Sign-in

For `entra` targets the CLI signs in with MSAL device code flow on first use, as the `--as` user (`biotrackr-alice@<tenant>` or `biotrackr-bob@<tenant>`, with the passwords in `solution/.secrets/test-users.txt`). Tokens are cached per user in `~/.biotrackr/` (override with `BIOTRACKR_CACHE_DIR`), so later runs are silent.

Before sending anything, the CLI checks that the token's `oid` matches `<USER>_OID` for `--as`. Signing in as bob while running `--as alice` stops with an error instead of sending bob's token.

## Usage

Run from `client/` with the matching stack up:

```powershell
uv run biotrackr-chat --target starter --as alice "summarise my sleep this week"
uv run biotrackr-chat --target solution-local --as alice "summarise my sleep this week"
uv run biotrackr-chat --target solution-offline --as bob "how did I sleep last night?"
uv run biotrackr-chat --target solution-azure --as alice     # interactive; type exit to quit
uv run biotrackr-chat --as alice --thread <id> "and my activity?"   # continue a thread
```

Tool calls render as `> tool name({...args})` and results as `< {...}`. Unauthenticated solution requests print `HTTP 401`.

## Lint

```powershell
uv run ruff check
```
