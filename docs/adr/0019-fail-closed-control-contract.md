---
title: "ADR-0019: Enforce a fail-closed contract for every solution control"
description: Define the required failure behaviour and test for each control type so that no control fails open
ms.date: 2026-10-20
ms.topic: reference
---

## Status

Accepted on 2026-10-18.

## Context

In MAF, ordinary exceptions in function middleware fail open, and `MiddlewareTermination` may not stop sibling calls in a parallel tool batch. The C# reference documents a fail-open reviewer and a log-only allowlist.

## Decision

Every solution control follows this contract and has a test for it.

| Control type                             | Required behaviour                                |
|------------------------------------------|---------------------------------------------------|
| Inbound authentication                   | 401 or 403 before any session or model call       |
| Input screening                          | Terminate before any model or tool call           |
| Tool result screening                    | Abort the run before the result reaches the model |
| Unknown tool, denied tool, budget breach | Abort the whole tool batch                        |
| MCP argument validation                  | Return an error without querying the database     |
| Prompt or MCP descriptor hash mismatch   | Process exits and never becomes ready             |
| Reviewer error, timeout, or bad verdict  | Persist `denied` and return no artefact           |
| Output policy error or timeout           | Replace the reply with a fixed refusal            |
| Kill switch on                           | Refuse every run before the model call            |

The Phase 0 spikes confirm which MAF mechanism aborts a parallel tool batch. Session budgets are keyed by user and session and incremented atomically.

### Amendment (2026-10-19, slice S2): verified batch-abort mechanism

The S2 spike (OQ-12) against MAF 1.22.0 settled the mechanism with a scripted model that returns a two-call parallel batch:

| Mechanism                                          | Sibling call runs | Run outcome                   |
|----------------------------------------------------|-------------------|-------------------------------|
| Function middleware raises `MiddlewareTermination` | Yes               | Completes gracefully          |
| Function middleware raises `MiddlewareFailure`     | No (cancelled)    | Fails                         |
| Function middleware raises an ordinary exception   | Yes               | Fails open; the model runs again |
| Chat middleware result gate raises `MiddlewareFailure` | No (no call starts) | Fails                    |

Solution controls therefore raise `MiddlewareFailure`. Tool policy runs as a chat middleware that checks the whole batch before any call starts, with per-call function middleware as a second layer. Cancellation is cooperative, so the batch-level check is the guarantee. The AGT 5.0 MAF adapter denies with `MiddlewareTermination`, so its function middleware is wrapped to raise `MiddlewareFailure` instead.

## Consequences

### Positive

* Closes both documented C# gaps on stage
* Failures are safe by construction and proven by tests

### Negative

* Fail-closed controls can block legitimate requests during outages

## Alternatives considered

| Alternative       | Reason not chosen              |
|-------------------|--------------------------------|
| Log-only controls | This is the starter's weakness |

## References

* [Architecture](../architecture.md)
* [Research](../research.md)
* [Research: Microsoft Agent Framework](../research.md#microsoft-agent-framework-python)

## Amendment (2026-10-19, slice S3)

The S3 rows are implemented and each has a spy-based test:

* Output policy (ADR-0021): an unsafe or indeterminate verdict, a classifier error, or a 5 second timeout gives the fixed refusal and disclaimer, streamed and non-streamed, and the refusal is what the history stores (`tests/test_output_guard.py`). The guard replaces the reply rather than raising, because AG-UI reduces any exception to a generic `RUN_ERROR`.
* Reviewer: an error, a timeout, or anything other than `{"approved": <bool>}` persists `denied` with `rejected_by: reviewer` and no chart; each review uses a fresh agent (`tests/test_report_agent.py`). Validation, generator, static-check, and runner failures are denied the same way, and later stages never run.
* Approval (`approval_mode="always_require"` for `generate_report`): the call waits for an AG-UI interrupt; the batch guard reserves the budget once, at proposal; a replayed approval never runs the tool again; a forged interrupt id, another user's resume, and a third report in one conversation are refused. ag-ui 1.6.0 accepts edited tool arguments on resume, which would run input the batch guard never saw, so the endpoint rejects any resume carrying more than the yes/no decision with HTTP 400 before the agent runs (`chat_api/approvals.py`, `tests/test_report_tools.py`).
* `FunctionTool.max_invocations` counts across the tool instance's lifetime (every user on the shared agent), so the per-conversation cap is part of the atomic tool budget (`tool_limits` in `governance.yaml`).

## Amendment (2026-10-20, slice S4)

The S4 rows are implemented and each has a spy-based test:

* Kill switch on: every run is refused before input screening, context providers, or the model (the model client spy records zero calls, no tool runs, nothing is stored), streamed, non-streamed, and through the AG-UI endpoint; a switch flipped mid-run aborts the next tool call with `MiddlewareFailure` (`tests/test_kill_switch.py`). On Azure an unreadable App Configuration store, a missing key, or an unknown value counts as engaged once the 10 second cache expires.
* Rogue detection: a quarantined user's tool calls abort their batch with `MiddlewareFailure` and their new runs are refused before the model; AGT's per-user detector denies with `MiddlewareTermination`, which is converted (`tests/test_rogue_guard.py`).
* Memory: a turn that AGT MemoryGuard flags is never written; a stored turn that fails its integrity hash or is flagged later is not loaded (`tests/test_memory_guard.py`).
* Audit: refused runs are recorded, and verification reports edited entries, broken links, and missing sequence numbers (`tests/test_audit.py`).

Like the output guard, the kill switch, a quarantine, and an exhausted token budget answer with fixed text rather than raising, because AG-UI reduces any exception to a generic `RUN_ERROR`. Availability failures (a dependency down) are the one place the solution does not stop with an error: the run gets a short "try again" reply that still passes the output guard. Control failures are never turned into that reply (`tests/test_resilience.py`).

| Control type                                   | Required behaviour                                           |
|------------------------------------------------|--------------------------------------------------------------|
| Kill switch on, unreadable, or unknown         | Fixed reply before the model call; abort the next tool call  |
| User quarantined by rogue detection            | Abort the tool batch; fixed reply before the next model call |
| Memory write flagged by MemoryGuard            | Do not store the turn                                        |
| Stored message fails its integrity hash        | Do not load the turn                                         |
| Token budget exhausted                         | Fixed reply before the model call                            |
