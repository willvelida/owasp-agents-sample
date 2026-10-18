---
title: Podman setup
description: Configure rootless Podman and a standalone docker-compose provider on Windows for the starter and solution stacks
ms.date: 2026-10-18
ms.topic: how-to
---

## Overview

Every service in this sample runs in a Linux container under rootless Podman ([ADR-0024](adr/0024-podman-container-engine.md)). uv and Python 3.12 run on the host for the CLI client, linting, and tests.

## Requirements

* Podman 5.x with a WSL machine
* A standalone docker-compose v2 binary (not Docker Desktop's)
* At least 8 GiB of memory available to the Podman machine

## Make the machine rootless

```powershell
podman machine stop
podman machine set --rootful=false
podman machine start
podman info --format '{{.Host.Security.Rootless}}'   # true
```

## Check memory and CPUs

On WSL machines, Podman cannot change CPUs or memory (`podman machine set --memory` fails with `changing CPUs not supported for WSL machines`). WSL controls them through `%USERPROFILE%\.wslconfig`. Without a `memory=` setting, WSL gives the machine half the host memory and every CPU.

```powershell
podman machine ssh "free -g; nproc"
```

If `total` memory is below 8, raise `memory=` under `[wsl2]` in `.wslconfig` and run `wsl --shutdown`. The file applies to every WSL distro.

> [!NOTE]
> `podman machine list` reports the machine's configured memory (for example 2 GiB), not what WSL provides. Trust `free -g` inside the machine.

## Pin a standalone compose provider

`podman compose` delegates to the first `docker-compose` it finds, which on many machines is Docker Desktop's. Install a standalone binary and pin it:

```powershell
winget install --id Docker.DockerCompose -e
$exe = (Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Docker.DockerCompose_*" -Recurse -Filter docker-compose.exe | Select-Object -First 1).FullName
New-Item -ItemType Directory -Force "$env:APPDATA\containers" | Out-Null
@"
[engine]
compose_providers = ["$($exe -replace '\\','\\')"]
compose_warning_logs = false
"@ | Set-Content -Encoding utf8 "$env:APPDATA\containers\containers.conf"
podman compose version
```

`podman compose version` must print the version without the `Executing external compose provider "...Docker Desktop..."` banner.

## Verified behaviour (OQ-13)

Checked on 2026-10-18 with Podman 5.8.3 and docker-compose v5.6.0, rootless:

| Behaviour                                                         | Result                                    |
|-------------------------------------------------------------------|-------------------------------------------|
| `user: "10001:10001"`                                             | Process runs as UID 10001                 |
| `network_mode: none`                                              | Outbound connect fails, network unreachable |
| `read_only: true`                                                 | Root filesystem write fails               |
| `cap_drop: [ALL]`, `no-new-privileges`, `pids_limit`              | Applied (`podman inspect`)                |
| Named volume with `driver_opts: { o: "uid=10001,gid=10001" }`     | Two UID 10001 containers share a Unix socket |
| Cosmos DB vNext emulator health check on `:8080/ready`            | Healthy alongside other services          |

> [!IMPORTANT]
> For read-only containers Podman still mounts writable tmpfs on `/tmp`, `/var/tmp`, and `/run` (`read_only_tmpfs` defaults to true). Treat those paths as writable when you reason about isolation.

## Everyday commands

```powershell
cd starter
podman compose up --build -d
podman compose ps
podman compose logs -f chat-api
podman compose down        # keep data
podman compose down -v     # drop the emulator data
```
