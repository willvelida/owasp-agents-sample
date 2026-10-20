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

## Amendment (2026-10-19, slice S3)

The S3 spike (OQ-05) did not adopt the AGT sandbox. AGT 5.0's `agent_sandbox` is a provider abstraction: its Docker provider needs the container engine socket (ruled out above), Hyperlight needs a hypervisor the arm64 Podman machine lacks, nono is Landlock-only and unproven here, and its ACA provider targets the early-access "sandbox groups" SDK rather than Dynamic Sessions. The isolated runner is therefore:

* Locally, `chart-runner` built from its own `chart_runner.Containerfile` (only matplotlib, numpy, Starlette, and uvicorn, hash-locked), with `network_mode: none`, read-only root, UID 10001, `cap_drop: [ALL]`, `no-new-privileges`, `pids_limit: 64`, one CPU, 768 MB, and no `.env`. It is reached over a Unix socket on the `chart-socket` volume. Each job runs in a fresh worker process with an empty environment, CPU, address-space, file-size, and open-file rlimits, and a 10 second wall clock, and returns only a PNG under 1 MB.
* On Azure (OQ-10), a `Microsoft.App/sessionPools` custom-container pool (`chartrunner`) with `EgressDisabled`, a fresh session per job that is stopped afterwards, and the image pulled with the report agent's own managed identity (`lifecycle: None`, so no token inside a session). Only that identity holds Session Executor on the pool. The postprovision hook builds the linux/amd64 image in ACR, tagged by a content hash.

The generator prompt is deliberately the same as the starter's, so red-team results show the check and the runner doing the work. A blocked ASI05 attack only counts when the report says `rejected_by: static_check` or `runner` and the canary is confirmed present in the report agent. The chart-spec DSL fallback was not needed.
