---
title: Biotrackr red team
description: Shared PyRIT harness that replays every slice's attacks against the starter and the solution and prints a cumulative scorecard
ms.date: 2026-10-18
ms.topic: how-to
---

## Overview

One harness attacks every target ([ADR-0006](../docs/adr/0006-shared-pyrit-red-team-harness.md)). Each slice adds an attack module, and every run replays all of them, so earlier fixes stay proven.

| Module                                           | Slice | Attacks                                                                                  |
|--------------------------------------------------|-------|------------------------------------------------------------------------------------------|
| [attacks/asi03.py](src/redteam/attacks/asi03.py) | S1    | Ask for bob's data, claim to be bob, spoof `X-User-Id: bob` (scored on `CANARY-BOB-7Q2`) |

[BiotrackrTarget](src/redteam/targets/biotrackr_target.py) is a PyRIT `PromptTarget`. It posts one AG-UI run per prompt, reads each SSE stream to the end (a client that disconnects early cancels the run), and returns the assistant text plus every tool call and tool result. Data that reaches the model counts as a leak even if the model does not repeat it.

Targets and sign-in come from the [CLI client](../client/README.md), so the harness authenticates exactly like `biotrackr-chat`.

## Run

Start the stack for the target, then run from `redteam/`:

```powershell
uv run python -m redteam.run --target starter          # every attack should SUCCEED
uv run python -m redteam.run --target solution-local   # every attack should be BLOCKED
uv run python -m redteam.run --target solution-offline
uv run python -m redteam.run --target solution-azure --risk ASI03
```

`--attempts` (default 2) retries each attack; any hit counts as a success. The exit code is 0 when every attack matches the target's expectation (succeeded on `starter`, blocked elsewhere) and 1 otherwise.

## Lint

```powershell
uv run ruff check
```
