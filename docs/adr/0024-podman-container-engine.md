---
title: "ADR-0024: Use Podman as the container engine"
description: Run all local services with rootless Podman and podman compose, build Azure images remotely in ACR, and use Podman in CI
ms.date: 2026-10-18
ms.topic: reference
---

## Status

Accepted on 2026-10-18. Amends [ADR-0011](0011-uv-python-312-dev-container.md) and revises the proposed default in [ADR-0022](0022-local-azure-credential-in-compose.md).

## Context

The plan originally assumed Docker Desktop and a dev container running Docker-in-Docker. The development machine runs Podman 5.8.3 on a WSL machine. The machine was rootful, and `podman compose` was delegating to Docker Desktop's `docker-compose` binary.

The local stack runs the Cosmos DB emulator, chat API, health MCP server, report agent, chart runner, identity sidecar, and identity simulator. The chart runner relies on container hardening options and a Unix socket shared with the report agent.

## Decision

* Podman is the only local container engine. Docker Desktop is not required and is stopped during demos.
* The Podman machine runs rootless (switched on 2026-10-18). On WSL, CPU and memory come from `.wslconfig`, not `podman machine set`; the current defaults give 31 GiB and 12 CPUs, and the sample needs at least 8 GiB.
* `podman compose` is pinned in `containers.conf` to a standalone docker-compose v2 provider, for full Compose spec support (profiles, internal networks, `cap_drop`, `security_opt`, health checks).
* Compose files are named `compose.yaml` and build files are named `Containerfile`.
* uv and Python run on the host. A dev container is optional and configured for Podman with no nested engine.
* azd builds images in Azure Container Registry (`docker.remoteBuild: true`), so Azure deployments need no local engine.
* GitHub Actions CI runs the solution with Podman on `ubuntu-latest`.
* Services that share the chart-runner socket run as a fixed UID (10001). No Podman or Docker socket is mounted into any service, and published ports are 8000 or above.
* Containers get Azure CLI credentials from a one-time `az login` into a named volume, not from the Windows token cache, which is DPAPI-encrypted.

A spike in slice S0 (OQ-13) checks rootless socket sharing, the hardening options through the compose provider, and the Cosmos emulator's health. If socket sharing fails under rootless Podman, the fallback is a rootful machine, and this record is updated.

## Consequences

### Positive

* Rootless, daemonless containers strengthen the talk's least-privilege story
* No dependency on Docker Desktop licensing or its background daemon
* The same engine runs locally and in CI
* Azure deployments don't depend on the local engine

### Negative

* Rootless volume and socket permissions need fixed UIDs
* The standalone compose provider is an extra install
* Some Docker-specific guidance (for example `host.docker.internal`) needs Podman equivalents (`host.containers.internal`)

## Alternatives considered

| Alternative                           | Reason not chosen                                                     |
|---------------------------------------|-----------------------------------------------------------------------|
| Docker Desktop                        | Replaced at the user's request                                        |
| `podman-compose` (Python) as provider | More Compose spec gaps for the hardening options the sample relies on |
| Rootful Podman machine                | Weaker isolation story; kept only as the OQ-13 fallback               |
| Dev container with nested Podman      | Fragile on Windows; host uv is simpler                                |
| Local Podman builds for azd           | Adds a local engine dependency to deployments                         |

## References

* [Architecture](../architecture.md)
* [Research](../research.md)
* [azd remote builds](https://learn.microsoft.com/azure/developer/azure-developer-cli/remote-builds)
