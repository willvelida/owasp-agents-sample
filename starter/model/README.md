---
title: Starter model
description: Bicep for the starter's key-enabled Foundry resource and gpt-4.1 deployment, with creation and teardown commands
ms.date: 2026-10-18
ms.topic: how-to
---

## Overview

The starter needs a model before any solution infrastructure exists. [main.bicep](main.bicep) creates a Foundry (AI Services) account with key authentication enabled and a `gpt-4.1` (`2025-04-14`, GlobalStandard, 100K TPM) deployment in its own resource group.

> [!CAUTION]
> Only the model lives in Azure. The starter application is never deployed to Azure ([ADR-0005](../../docs/adr/0005-starter-local-only-solution-on-azure.md)). Key authentication is a deliberate ASI03 weakness; the solution uses a separate resource with key authentication disabled.

## Create

```powershell
az account set --subscription 77348e6c-0286-496f-8336-28e966b13648
az group create --name rg-owasp-agents-starter-model --location australiaeast
az deployment group create `
  --resource-group rg-owasp-agents-starter-model `
  --template-file starter/model/main.bicep
```

The deployment outputs `accountName` and `endpoint`. Write the endpoint and a key into `starter/.env` (gitignored):

```powershell
$name = az deployment group show -g rg-owasp-agents-starter-model -n main --query properties.outputs.accountName.value -o tsv
$endpoint = az deployment group show -g rg-owasp-agents-starter-model -n main --query properties.outputs.endpoint.value -o tsv
$key = az cognitiveservices account keys list -g rg-owasp-agents-starter-model -n $name --query key1 -o tsv
Copy-Item starter/.env.example starter/.env
(Get-Content starter/.env) -replace '^FOUNDRY_ENDPOINT=.*', "FOUNDRY_ENDPOINT=$endpoint" -replace '^FOUNDRY_API_KEY=.*', "FOUNDRY_API_KEY=$key" | Set-Content starter/.env
```

## Teardown

```powershell
az group delete --name rg-owasp-agents-starter-model --yes --no-wait
```

Foundry accounts are soft-deleted. Purge the account if you want to reuse the same name:

```powershell
az cognitiveservices account purge --location australiaeast --resource-group rg-owasp-agents-starter-model --name <accountName>
```
