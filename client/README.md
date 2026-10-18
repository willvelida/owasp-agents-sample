---
title: Biotrackr CLI client
description: Command-line AG-UI client for the starter and solution chat APIs, showing streamed text, tool calls, and tool results
ms.date: 2026-10-18
ms.topic: how-to
---

## Overview

`biotrackr-chat` sends a message to a chat API over AG-UI and renders the stream: text deltas, every tool call with its arguments, a preview of each tool result, and run errors. Targets live in [targets.toml](targets.toml).

| Target    | Slice | Auth                                         |
|-----------|-------|----------------------------------------------|
| `starter` | S0    | `X-User-Id` header from `--as` (no token)    |

S1 adds the `entra` (device-code sign-in) and `local` (offline simulator) targets for the solution.

## Usage

Run from `client/` with the starter stack up (`podman compose up -d` in `starter/`):

```powershell
uv run biotrackr-chat --target starter --as alice "summarise my sleep this week"
uv run biotrackr-chat --target starter --as alice     # interactive; type exit to quit
uv run biotrackr-chat --as alice --thread <id> "and my activity?"   # continue a thread
```

Tool calls render as `> tool name({...args})` and results as `< {...}`.

## Lint

```powershell
uv run ruff check
```
