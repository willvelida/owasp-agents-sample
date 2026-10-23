---
title: "ADR-0023: Deliver in vertical slices with tagged checkpoints"
description: Build the sample as vertical slices that each end in a tagged checkpoint runnable locally and on Azure, with a cumulative red-team scorecard
ms.date: 2026-10-23
ms.topic: reference
---

## Status

Accepted on 2026-10-18. Amends the schedule in [ADR-0007](0007-all-ten-controls-with-cut-lines.md).

Amended by [ADR-0026](0026-genai-telemetry-export.md), which adds S8 observability.

## Context

The first plan was layered: all scaffolding, then the whole starter, then identity, then every solution control, then Azure. The solution was runnable only at the end of one large phase, and Azure appeared late. You want a runnable version after each phase that you can test on your machine, and on Azure where it applies.

## Decision

Deliver the sample as seven vertical slices. Each slice extends the starter and the solution together for a group of risks.

| Slice | Content                                                           | Local                          | Azure               | Tag               |
|-------|-------------------------------------------------------------------|--------------------------------|---------------------|-------------------|
| S0    | Podman setup, seed data, CLI, starter chat API and MCP            | Starter                        | No                  | `s0-foundation`   |
| S1    | Solution created; Entra Agent ID OBO; simulator; PyRIT ASI03      | Starter, solution (both modes) | Skeleton (`azd up`) | `s1-identity`     |
| S2    | ASI01, ASI02, ASI04 runtime controls                              | Starter, solution              | `azd deploy`        | `s2-tools`        |
| S3    | Report agent, runner, output guard (ASI05, ASI09, ASI07 baseline) | Starter, solution              | `azd up`            | `s3-reports`      |
| S4    | ASI06, ASI08, ASI10                                               | Starter, solution              | `azd up`            | `s4-operations`   |
| S5    | Signed A2A (ASI07), CI and supply chain (ASI04)                   | Starter, solution              | `azd up`            | `s5-supply-chain` |
| S6    | Runbook, full validation, rehearsal                               | All                            | All                 | `s6-talk-ready`   |

Every slice ends with the same checkpoint:

1. Lint and tests pass.
2. The starter runs with `podman compose`, and from S1 the solution runs in Entra and offline modes.
3. The PyRIT scorecard re-runs every attack added so far. Attacks succeed on the starter and are blocked on the solution.
4. From S1, the slice is deployed to the single azd environment `owasp-agents`, and the same scorecard runs against Azure.
5. An annotated git tag marks the checkpoint. Tags are never moved.

Open-question spikes move into the slice that first needs them. The starter stays local only ([ADR-0005](0005-starter-local-only-solution-on-azure.md)).

## Consequences

### Positive

* `git checkout <tag>` gives a known-good, runnable version for testing, review, or a stage fallback
* Azure problems surface from S1 instead of at the end
* Each slice's checkpoint re-runs every earlier attack, so a regression in an earlier control shows up immediately

### Negative

* Some files are touched in several slices (for example, `agent.py` and `main.bicep`)
* One Azure environment means only the latest slice is live; earlier tags need a redeploy to run on Azure
* Checkpoints add overhead to each slice

## Alternatives considered

| Alternative                           | Reason not chosen                                             |
|---------------------------------------|---------------------------------------------------------------|
| Layered phases with added checkpoints | The solution is still not runnable until most controls exist  |
| Long-lived branch per slice           | Merge overhead with no extra benefit over tags                |
| Snapshot folders per slice            | A third copy of the code                                      |
| Separate azd environment per slice    | Higher cost and more Agent ID federated credentials to manage |

## References

* [Architecture](../architecture.md)
* [Research](../research.md)
