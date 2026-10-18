---
title: "ADR-0011: Standardise on uv and Python 3.12 with containerised services"
description: Use uv for dependency management, target Python 3.12, run tooling on the host, and run every service in a Linux container
ms.date: 2026-10-18
ms.topic: reference
---

## Status

Accepted on 2026-10-18.

## Context

MAF, AGT, and PyRIT resolve together on Python 3.12. The AGT ACS engine ships only a Linux x86_64 wheel, and some AGT packages fail to build on Windows.

## Decision

Each project (`starter`, `solution`, `client`, `redteam`) is a uv project with a committed `uv.lock`. Amended on 2026-10-18 by [ADR-0024](0024-podman-container-engine.md): uv, Python, Azure CLI, azd, and PowerShell run on the host, and every service runs as a Linux container under Podman. A dev container remains available for Codespaces and Linux users, configured for Podman with no nested container engine.

## Consequences

### Positive

* Reproducible environments on stage
* Hash-pinned lock files support ASI04

### Negative

* Windows hosts need a Podman machine (WSL) for the services

## Alternatives considered

| Alternative                   | Reason not chosen                       |
|-------------------------------|-----------------------------------------|
| pip and venv with Python 3.13 | Weaker locking and no hashes by default |

## References

* [Architecture](../architecture.md)
* [Research](../research.md)
