---
title: "ADR-0003: Mirror the starter and solution layouts"
description: Ship an insecure starter and a secure solution with identical component and file names
ms.date: 2026-10-18
ms.topic: reference
---

## Status

Accepted on 2026-10-18.

## Context

The talk contrasts an agent with unaddressed OWASP Agentic risks against the same agent with controls applied. The audience needs to see exactly what changed, and nothing else.

## Decision

Create `starter/` and `solution/` with the same services and file names. Build the starter first, then copy it into `solution/` without overwriting existing files and apply controls in place. Mark weaknesses with `# ASI0x (starter):` and controls with `# ASI0x:` comments. `git diff --no-index starter solution` becomes a talk artefact.

## Consequences

### Positive

* The diff shows only security deltas
* Grep on the markers produces the control map for the READMEs and slides

### Negative

* Non-security fixes must be applied to both trees
* Code is duplicated across the two stacks

## Alternatives considered

| Alternative                               | Reason not chosen                                                    |
|-------------------------------------------|----------------------------------------------------------------------|
| Single codebase with a `SECURE_MODE` flag | Hides the insecure path behind conditionals and loses the diff story |
| Minimal one-file starter                  | Cannot show ASI05 and ASI07 weaknesses in separate services          |

## References

* [Architecture](../architecture.md)
* [Research](../research.md)
