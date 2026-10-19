---
title: Solution scripts
description: Entra Agent ID provisioning, azd hooks, and Azure seeding for the Biotrackr solution
ms.date: 2026-10-18
ms.topic: how-to
---

## Overview

| Script                                       | Runs as                      | Purpose                                                                 |
|----------------------------------------------|------------------------------|-------------------------------------------------------------------------|
| [provision_agent_id.ps1](provision_agent_id.ps1) | You, or the azd hooks        | Creates or reuses the Entra Agent ID objects, grants, and test users    |
| [hooks/preprovision.ps1](hooks/preprovision.ps1) | azd `preup`, `preprovision`  | Runs the provisioning script and writes the typed IDs into the azd env  |
| [hooks/postprovision.ps1](hooks/postprovision.ps1) | azd `postprovision`          | Adds the Blueprint federated credential, then runs `seed.ps1`           |
| [seed.ps1](seed.ps1)                         | `postprovision` hook         | Seeds Azure Cosmos DB by alice and bob's object ids with your Entra login |

## Prerequisites

* PowerShell 7 with `Microsoft.Graph.Authentication` (`Install-Module Microsoft.Graph.Authentication -Scope CurrentUser`)
* Agent ID Developer or Agent ID Administrator, plus User Administrator, in the tenant
* One-time tenant-wide admin consent for Microsoft Graph Command Line Tools, granted by a Global Administrator or Privileged Role Administrator, covering:
  `AgentIdentityBlueprint.Create`, `AgentIdentityBlueprint.ReadWrite.All`, `AgentIdentityBlueprintPrincipal.Create`, `AgentIdentity.Create.All`, `Application.ReadWrite.All`, `DelegatedPermissionGrant.ReadWrite.All`, `AppRoleAssignment.ReadWrite.All`, `User.ReadWrite.All`

The script checks the token's scopes first and exits with the missing list. It also refuses a token that carries `Directory.AccessAsUser.All`, because Agent ID APIs reject it. Azure CLI tokens carry that scope, which is why the script uses the Microsoft Graph Command Line Tools client instead of `az`.

## Provision Agent ID

```powershell
cd solution
./scripts/provision_agent_id.ps1 -TenantId <tenant-id> -UseDeviceCode -WriteDotEnv
```

The script is idempotent, so a second run creates nothing. It creates:

| Object                          | Kind                           | Notes                                                          |
|---------------------------------|--------------------------------|----------------------------------------------------------------|
| `biotrackr-blueprint`           | Agent Identity Blueprint + principal | `api://{appId}`, scope `access_as_user`, v2 tokens, `idtyp` claim |
| `biotrackr-owasp-chat-agent`    | Agent identity                 | Delegated `Health.Read` on the MCP API; `Report.Generate` role |
| `biotrackr-report-agent`        | Agent identity                 | No grants until S3                                             |
| `biotrackr-health-mcp`          | App registration               | Delegated scope `Health.Read`, v2 tokens                       |
| `biotrackr-report-api`          | App registration               | App role `Report.Generate` (used from S3)                      |
| `biotrackr-demo-cli`            | Public client                  | Pre-authorized on the Blueprint's `access_as_user`             |
| `biotrackr-alice`, `biotrackr-bob` | Test users                  | Passwords in `.secrets/test-users.txt` only                    |

Agent identities are matched by their parent Blueprint, never by display name alone, so identities from other Blueprints in the tenant are never reused or modified.

Outputs:

* Stdout and, with `-WriteDotEnv`, `solution/.env` receive the non-secret typed IDs: `TENANT_ID`, `BLUEPRINT_APP_ID`, `CHAT_AGENT_APP_ID`, `CHAT_AGENT_SP_OBJECT_ID`, `REPORT_AGENT_APP_ID`, `REPORT_AGENT_SP_OBJECT_ID`, `HEALTH_MCP_APP_ID`, `REPORT_API_APP_ID`, `CLI_APP_ID`, `ALICE_OID`, `BOB_OID`, `ALICE_UPN`, `BOB_UPN`. With `-AzdEnvSet` they also go into the azd environment.
* `solution/.secrets/` (gitignored, owner-only ACL) receives the Blueprint dev secret for the local sidecar (`sidecar.env`), the test user passwords (`test-users.txt`), and the Graph refresh token (`graph-token.json`) that keeps the azd hooks from prompting again.

Sidecar calls use `*_APP_ID` values; Graph grants use `*_SP_OBJECT_ID` values. For agent identities the two are the same GUID.

> [!NOTE]
> `-UseDeviceCode` runs the device code flow over plain OAuth and hands the token to `Connect-MgGraph -AccessToken`. Interactive browser sign-in needs a console window handle, and the Graph SDK's device code credential can fail with a null reference after sign-in.

## Federated credential

The Azure sidecar authenticates as the Blueprint with `SignedAssertionFromManagedIdentity`, so the Blueprint trusts the user-assigned managed identity through a federated credential named `aca-<principal-id>`:

```powershell
./scripts/provision_agent_id.ps1 -TenantId <tenant-id> -ManagedIdentityPrincipalId <oid> -FederatedCredentialOnly -UseDeviceCode
./scripts/provision_agent_id.ps1 -TenantId <tenant-id> -ManagedIdentityPrincipalId <oid> -RemoveFederatedCredential -UseDeviceCode
```

The azd `postprovision` hook runs the first command. Run the second after `azd down` of a verification environment so the shared Blueprint does not keep trusting a deleted identity.

## Seed Azure Cosmos DB

The `postprovision` hook runs [seed.ps1](seed.ps1) after the federated credential step (azd 1.34 skips the project `postdeploy` hook during `azd up`). It reads `COSMOS_ENDPOINT`, `ALICE_OID`, and `BOB_OID` from the azd environment and runs `python -m seed` with your Entra login. The account has local auth disabled, and Bicep assigns you the Cosmos DB Built-in Data Contributor role.
