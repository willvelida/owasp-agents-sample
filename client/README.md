---
title: Biotrackr CLI client
description: Command-line AG-UI client for the starter and solution chat APIs, showing streamed text, tool calls, and tool results
ms.date: 2026-10-23
ms.topic: how-to
---

## Overview

`biotrackr-chat` sends a message to a chat API over AG-UI and renders the stream: text deltas, every tool call with its arguments, a preview of each tool result, and run errors. Targets live in [targets.toml](targets.toml). Each target matches a route in the [root README](../README.md#choose-a-route), and every target needs its stack running; all of them reach a cloud model through that stack.

| Target             | Slice | Auth                                                                       |
|--------------------|-------|----------------------------------------------------------------------------|
| `starter`          | S0    | `X-User-Id` header from `--as` (no token)                                  |
| `solution-local`   | S1    | Entra device code sign-in as the demo CLI, for `api://BLUEPRINT_APP_ID/access_as_user` |
| `solution-offline` | S1    | Simulated identity: a token from the stage-only simulator on `127.0.0.1:8100`. The stack still uses the solution's cloud model |
| `solution-azure`   | S1    | Entra, against the URL in the azd environment (`CHAT_API_URL`)              |

The solution targets read `TENANT_ID`, `CLI_APP_ID`, `BLUEPRINT_APP_ID`, and each user's `<USER>_OID` and `<USER>_UPN` from `solution/.env`, which [provision_agent_id.ps1](../solution/scripts/provision_agent_id.ps1) writes with `-WriteDotEnv` (see [solution/scripts/README.md](../solution/scripts/README.md)). The `env_file` and `azd_cwd` paths in `targets.toml` are relative to that file, not to your shell's directory.

## Sign-in

For `entra` targets the CLI signs in with MSAL device code flow on first use, as the `--as` user (`biotrackr-alice@<tenant>` or `biotrackr-bob@<tenant>`, with the passwords in `solution/.secrets/test-users.txt`). Tokens are cached per user in `~/.biotrackr/` (override with `BIOTRACKR_CACHE_DIR`), so later runs are silent.

Before sending anything, the CLI checks that the token's `oid` matches `<USER>_OID` for `--as`. Signing in as bob while running `--as alice` stops with an error instead of sending bob's token.

## Usage

Run from `client/` with the matching stack up:

```powershell
uv run biotrackr-chat --target starter --as alice "Summarise my sleep on 2026-10-19."
uv run biotrackr-chat --target solution-local --as alice "Summarise my sleep on 2026-10-19."
uv run biotrackr-chat --target solution-offline --as bob "How did I sleep on 2026-10-19?"
uv run biotrackr-chat --target solution-azure --as alice     # interactive; type exit to quit
uv run biotrackr-chat --as alice --thread <id> "and my activity?"   # continue a thread
```

A successful first answer streams a sleep tool call for the signed-in user and then a short summary of that night. The seed data records 412 minutes asleep for alice and 352 for bob on 2026-10-19; the wording varies by model run. The seed data covers 2026-09-29 to 2026-10-28, so use dates in that range.

Tool calls render as `> tool name({...args})` and results as `< {...}`. Unauthenticated solution requests print `HTTP 401`.
When the solution asks for approval (`generate_report`), the CLI shows the tool and its arguments and asks `approve? [y/N]`, then resumes the same thread with your decision. `--approve yes` or `--approve no` answers for scripts; without a terminal the CLI rejects. A spinner shows while a report is generated and reviewed.

## Lint

```powershell
uv run ruff check
```
