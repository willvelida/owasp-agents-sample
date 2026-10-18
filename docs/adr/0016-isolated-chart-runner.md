---
title: "ADR-0016: Execute generated chart code in an isolated runner"
description: Run model-generated chart code outside the report agent process in a sandbox with no network, no secrets, and a read-only file system
ms.date: 2026-10-18
ms.topic: reference
---

## Status

Accepted on 2026-10-18.

## Context

The report agent generates matplotlib code from model output. Static checks on generated code are bypassable and cannot be a hard boundary. A Compose service with `network_mode: none` cannot be called over HTTP, and exposing the Podman or Docker socket to spawn containers is worse than the original bug.

## Decision

* Run an AST allowlist check first, as defence-in-depth only.
* Use the AGT sandbox if the Phase 0 spike proves it enforces no network, a read-only file system, and timeouts.
* Otherwise, run a prestarted `chart-runner` container locally with no network, a read-only root, a non-root user, all capabilities dropped, `no-new-privileges`, resource limits, and an empty environment. Reach it over a Unix domain socket on a shared volume.
* On Azure, use an Azure Container Apps Dynamic Sessions custom-container pool with egress disabled.
* Never mount the Podman or Docker socket into any service. Under rootless Podman, the report agent and runner share the socket volume with a fixed UID (10001).

## Consequences

### Positive

* Like-for-like comparison with the starter's `exec()`
* A static-check bypass still cannot reach secrets or the network

### Negative

* Two runner implementations, local and Azure
* Dynamic Sessions feasibility must be confirmed in Phase 0

## Alternatives considered

| Alternative                           | Reason not chosen                                                  |
|---------------------------------------|--------------------------------------------------------------------|
| Chart-spec DSL rendered by fixed code | Strongest boundary but not like-for-like; retained as the fallback |
| AST check only                        | Bypassable                                                         |

## References

* [Architecture](../architecture.md)
* [Research](../research.md)
