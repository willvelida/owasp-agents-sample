---
title: "ADR-0015: Provision Agent ID objects and test users with an idempotent script"
description: Create the Blueprint, agent identities, APIs, grants, credentials, and test users with an idempotent PowerShell script run as an azd hook
ms.date: 2026-10-18
ms.topic: reference
---

## Status

Accepted on 2026-10-18.

## Context

Bicep cannot create Agent Identity Blueprints, and Agent ID APIs reject Azure CLI tokens. Creation calls in quick succession can fail on replication delays. Several required Graph scopes need tenant-wide admin consent.

## Decision

* `solution/scripts/provision_agent_id.ps1` uses `Connect-MgGraph` with explicit delegated scopes and check-then-create logic with backoff.
* It creates the Blueprint and principal, the chat and report agent identities, the MCP and report API registrations, a public CLI client, delegated and app-role grants, Blueprint credentials, and the alice and bob test users.
* A preflight verifies admin consent and lists missing scopes. A Global Administrator or Privileged Role Administrator grants consent once.
* Output names distinguish app IDs (used by the sidecar) from service principal object IDs (used by Graph grants).
* Secrets and test-user passwords go only to the gitignored `solution/.secrets/` folder, never to stdout or azd logs.
* In azd, the script runs twice. The `preprovision` hook creates the Entra objects and stores the non-secret IDs with `azd env set` so Bicep can consume them. The `postprovision` hook (`-FederatedCredentialOnly`) adds the managed identity's federated credential after the identity exists.

## Consequences

### Positive

* Repeatable setup for any tenant
* Runs automatically during `azd up`

### Negative

* The operator needs Agent ID Developer or Administrator plus User Administrator
* Deleted identities leave agent users and test users that need manual cleanup

## Alternatives considered

| Alternative            | Reason not chosen                                           |
|------------------------|-------------------------------------------------------------|
| Manual portal steps    | Error-prone and the admin center does not manage Blueprints |
| Pre-created test users | Recommended in review, but the user chose scripted creation |

## References

* [Architecture](../architecture.md)
* [Research](../research.md)
