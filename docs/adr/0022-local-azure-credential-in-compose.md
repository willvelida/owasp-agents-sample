---
title: "ADR-0022: Provide Azure credentials to solution containers in Compose"
description: Choose how solution containers obtain a developer identity for DefaultAzureCredential during local development
ms.date: 2026-10-18
ms.topic: reference
---

## Status

Accepted on 2026-10-18 (proposed earlier the same day). The clean-container token test passed in slice S1: `DefaultAzureCredential` inside `chat-api` obtained a `https://cognitiveservices.azure.com/.default` token from the `azcli-cache` volume, and `/home/app/.azure` is owned by UID 10001.

## Context

Mounting the Azure CLI cache alone does not make `DefaultAzureCredential` work, because `AzureCliCredential` must run an `az` binary inside the container. The solution must never fall back to the starter's API key.

## Decision

Decision (originally proposed, revised for Podman on a Windows host, see [ADR-0024](0024-podman-container-engine.md)):

* A `dev` Containerfile stage installs Azure CLI, creates `/home/app/.azure` owned by UID 10001, and runs as UID 10001.
* A one-shot `az-login` Compose service, built from the same `dev` stage, runs `az login --use-device-code` once and writes the token cache to a named volume, `azcli-cache`, which inherits UID 10001 ownership.
* The volume is mounted read-write at `/home/app/.azure` in `chat-api` and `report-agent`, because `az` refreshes its token cache on each request. This applies to the local dev profile only.
* The host's `%USERPROFILE%\.azure` is not mounted, because the Windows token cache is DPAPI-encrypted and unreadable in Linux.

The fallback, kept for reference, is a dev-only service principal with Foundry and Cosmos data-plane RBAC, consumed through `EnvironmentCredential`, with its secret in `solution/.secrets/`. Azure images use the production stage with managed identity only.

## Consequences

### Positive

* No new secrets with the default option
* Production images stay free of the Azure CLI

### Negative

* Larger dev images
* Token cache permissions must match the container user

## Alternatives considered

| Alternative              | Reason not chosen             |
|--------------------------|-------------------------------|
| Mount the cache only     | Fails without the `az` binary |
| Fall back to the API key | Defeats ADR-0010              |

## References

* [Architecture](../architecture.md)
* [Research](../research.md)
