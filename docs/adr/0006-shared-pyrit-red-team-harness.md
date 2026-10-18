---
title: "ADR-0006: Share one PyRIT red-team harness across both stacks"
description: Use a single top-level PyRIT harness that targets the starter, local solution, or Azure solution by URL
ms.date: 2026-10-18
ms.topic: reference
---

## Status

Accepted on 2026-10-18.

## Context

The talk needs evidence that each control holds under attack, not only a code walkthrough. PyRIT 1.1.0 supports custom `PromptTarget` subclasses, multi-turn attacks, converters, and deterministic scorers.

## Decision

Create `redteam/` at the repository root with a PyRIT target that speaks AG-UI. `run.py --target starter|solution-local|solution-azure` runs the same attacks against each stack and prints a scorecard. Scoring prefers deterministic canaries (`SubStringScorer`, `RegexScorer`) and uses LLM judges only where needed.

## Consequences

### Positive

* The same command shows attacks succeeding on the starter and failing on the solution
* Deterministic scorers can run in CI

### Negative

* The harness must handle authentication for every target

## Alternatives considered

| Alternative                     | Reason not chosen                                         |
|---------------------------------|-----------------------------------------------------------|
| Harness inside `solution/` only | Cannot demonstrate attacks succeeding against the starter |
| Foundry AI Red Teaming Agent    | Single-turn only                                          |

## References

* [Architecture](../architecture.md)
* [Research](../research.md)
* [Research: PyRIT](../research.md#pyrit)
