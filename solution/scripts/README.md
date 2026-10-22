---
title: Solution scripts
description: Entra Agent ID provisioning, azd hooks, and Azure seeding for the Biotrackr solution
ms.date: 2026-10-22
ms.topic: how-to
---

## Overview

| Script                                       | Runs as                      | Purpose                                                                 |
|----------------------------------------------|------------------------------|-------------------------------------------------------------------------|
| [provision_agent_id.ps1](provision_agent_id.ps1) | You, or the azd hooks        | Creates or reuses the Entra Agent ID objects, grants, and test users    |
| [hooks/preprovision.ps1](hooks/preprovision.ps1) | azd `preup`, `preprovision`  | Provisions Agent ID, stores typed IDs and the signing key pair, builds the chart runner when ACR exists |
| [hooks/postprovision.ps1](hooks/postprovision.ps1) | azd `postprovision`          | Adds the federated credential, seeds Cosmos, configures the chart runner, creates a missing kill-switch key, and sets the SPA redirect URIs |
| [hooks/predown.ps1](hooks/predown.ps1)       | azd `predown`                | Removes the federated credential for this environment's managed identity before `azd down` deletes it |
| [seed.ps1](seed.ps1)                         | `postprovision` hook         | Seeds Azure Cosmos DB by alice and bob's object ids with your Entra login |

## Prerequisites

Obtain operator approval before running provisioning hooks, including a preview
that may invoke them. They can change Entra objects, build images in ACR, seed
data, and update Azure configuration. See the [demo runbook](../../docs/demo-runbook.md)
for read-only pre-show checks instead.

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
| `biotrackr-demo-spa`            | Single-page app (browser UI)   | Tagged `biotrackr-blueprint`; SPA redirect URIs only, no secrets; pre-authorized next to the CLI |
| `biotrackr-alice`, `biotrackr-bob` | Test users                  | Passwords in `.secrets/test-users.txt` only                    |

Agent identities are matched by their parent Blueprint, never by display name alone, so identities from other Blueprints in the tenant are never reused or modified.

The browser client `biotrackr-demo-spa` is found only by its stored `SPA_APP_ID` (azd environment first, then `solution/.env`), or, when no id is stored, by display name if the single match carries the `biotrackr-blueprint` tag. A same-named application without the tag, more than one match, or a stored id that resolves to nothing or to an untagged app stops the run. Nothing else in the tenant is ever matched by display name for the SPA. The Blueprint's `preAuthorizedApplications` lists the CLI and the SPA, sent together in one PATCH.

The SPA's redirect URIs are `http://localhost:5173/` (Vite dev server) plus the deployed `chat-ui` URL. Every run sends the whole list. When `CHAT_UI_URL` is not stored, the run keeps any `https://` entry already on the app, so it never drops the Azure URI.

Every Graph create and update prints a `==>` line with the object's display name and object id, so a run's transcript lists every object it wrote.

Outputs:

* Stdout and, with `-WriteDotEnv`, `solution/.env` receive the non-secret typed IDs: `TENANT_ID`, `BLUEPRINT_APP_ID`, `CHAT_AGENT_APP_ID`, `CHAT_AGENT_SP_OBJECT_ID`, `REPORT_AGENT_APP_ID`, `REPORT_AGENT_SP_OBJECT_ID`, `HEALTH_MCP_APP_ID`, `REPORT_API_APP_ID`, `CLI_APP_ID`, `SPA_APP_ID`, `ALICE_OID`, `BOB_OID`, `ALICE_UPN`, `BOB_UPN`. With `-AzdEnvSet` they also go into the azd environment.
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

The azd `postprovision` hook runs the first command, and the `predown` hook runs the second before `azd down` deletes the identity, so the shared Blueprint never keeps trusting a deleted identity. Run the second yourself only if an environment was removed without `azd down`, for example by deleting its resource group.

## SPA redirect URIs

The `chat-ui` hostname exists only after Bicep runs, so the `postprovision` hook sets the Azure redirect URI as its last step:

```powershell
./scripts/provision_agent_id.ps1 -TenantId <tenant-id> -SpaRedirectUri -UseDeviceCode
```

`-SpaRedirectUri` reads `SPA_APP_ID` and `CHAT_UI_URL` from the azd environment, resolves the app by `appId` only, requires the `biotrackr-blueprint` tag, and replaces only its `spa.redirectUris` with `http://localhost:5173/` and `<CHAT_UI_URL>/`. It changes no other object. When either value is not set, or is not a GUID or an `https://` origin, it warns and exits without signing in. A Graph failure fails the hook.

## Revoke or remove the browser client

* Revoke now: disable the SPA's service principal (`accountEnabled: false`). Entra then stops issuing tokens to the browser client, and the CLI keeps working. This is an Entra write, so get approval first.
* Do not rely on editing `ALLOWED_CLIENT_APP_IDS` on the `chat-api` container app: Bicep sets it, so the next `azd up` restores it.
* Remove fully: remove the `spaAppId` parameter and the SPA entry in `ALLOWED_CLIENT_APP_IDS` from Bicep (and `SPA_APP_ID` from `compose.yaml`), clear `SPA_APP_ID` from the azd environment and `solution/.env`, and delete the `biotrackr-demo-spa` app. The next provisioning run then pre-authorizes only the CLI. Until the code change lands, a provisioning run with no stored id finds no tagged app and creates a new one.

## Seed Azure Cosmos DB

The `postprovision` hook runs [seed.ps1](seed.ps1) after the federated credential step (azd 1.34 skips the project `postdeploy` hook during `azd up`). It reads `COSMOS_ENDPOINT`, `ALICE_OID`, and `BOB_OID` from the azd environment and runs `python -m seed` with your Entra login. The account has local auth disabled, and Bicep assigns you the Cosmos DB Built-in Data Contributor role.
