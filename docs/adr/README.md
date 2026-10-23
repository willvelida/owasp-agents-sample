---
title: Architecture decision records
description: Index of architecture decision records for the OWASP Agentic Top 10 sample
ms.date: 2026-10-23
ms.topic: reference
---

## Overview

Each record captures one decision made while planning the sample, why it was made, and what it costs. See [architecture](../architecture.md) for how the decisions fit together.

Records describe the decision when it was made. Later records amend earlier ones, and the amended record names its replacement in its Status section. Where current behaviour differs from a record's expected consequences, the component guides describe what the code does now.

## Start here

| If you want to understand | Read |
|---------------------------|------|
| Why there are two stacks and how they relate | [0003](0003-mirrored-starter-and-solution.md), [0004](0004-naive-but-plausible-starter.md), [0005](0005-starter-local-only-solution-on-azure.md) |
| Identity and per-user access (ASI03) | [0010](0010-model-access-key-vs-entra.md), [0013](0013-entra-agent-id-obo.md), [0014](0014-agent-id-sidecar.md), [0015](0015-scripted-agent-id-provisioning.md), [0018](0018-offline-identity-simulator.md) |
| How controls behave when something fails | [0019](0019-fail-closed-control-contract.md), [0020](0020-indirect-injection-containment.md) |
| Reports and clinical advice (ASI05, ASI09) | [0016](0016-isolated-chart-runner.md), [0021](0021-output-policy-for-clinical-advice.md) |
| How the talk and the red team were planned | [0006](0006-shared-pyrit-red-team-harness.md), [0008](0008-live-demo-risk-selection.md), [0017](0017-live-azure-segment.md), [0023](0023-vertical-slices-with-tagged-checkpoints.md) |
| The clients | [0012](0012-demo-clients.md), [0025](0025-browser-chat-client.md) |

> [!NOTE]
> [ADR-0018](0018-offline-identity-simulator.md) expects the offline simulator to let the demo survive a network outage. The simulator replaces Entra sign-in only: the agent still calls the solution's Foundry model, so chat needs the network. See [solution/README.md](../../solution/README.md#run-locally-offline-mode).

## Records

| ADR                                                            | Title                                                                          | Status   |
|----------------------------------------------------------------|--------------------------------------------------------------------------------|----------|
| [0001](0001-record-architecture-decisions.md)                  | Record architecture decisions                                                  | Accepted |
| [0002](0002-agent-framework-foundry-and-governance-toolkit.md) | Use Microsoft Agent Framework, Microsoft Foundry, and Agent Governance Toolkit | Accepted |
| [0003](0003-mirrored-starter-and-solution.md)                  | Mirror the starter and solution layouts                                        | Accepted |
| [0004](0004-naive-but-plausible-starter.md)                    | Make the starter naive but plausible                                           | Accepted |
| [0005](0005-starter-local-only-solution-on-azure.md)           | Run the starter locally only and deploy the solution to Azure                  | Accepted |
| [0006](0006-shared-pyrit-red-team-harness.md)                  | Share one PyRIT red-team harness across both stacks                            | Accepted |
| [0007](0007-all-ten-controls-with-cut-lines.md)                | Deliver all ten controls before the talk with cut lines                        | Accepted |
| [0008](0008-live-demo-risk-selection.md)                       | Demonstrate five risks live on stage                                           | Accepted |
| [0009](0009-cosmos-db-emulator.md)                             | Use the Cosmos DB vNext emulator for local development                         | Accepted |
| [0010](0010-model-access-key-vs-entra.md)                      | Use an API key in the starter and Entra ID in the solution for model access    | Accepted |
| [0011](0011-uv-python-312-dev-container.md)                    | Standardise on uv and Python 3.12 with containerised services                  | Accepted |
| [0012](0012-demo-clients.md)                                   | Drive demos through an AG-UI CLI client, DevUI, and PyRIT                      | Accepted |
| [0013](0013-entra-agent-id-obo.md)                             | Use Entra Agent ID on-behalf-of flow for user-scoped tool access               | Accepted |
| [0014](0014-agent-id-sidecar.md)                               | Acquire agent tokens through the Entra SDK for AgentID sidecar                 | Accepted |
| [0015](0015-scripted-agent-id-provisioning.md)                 | Provision Agent ID objects and test users with an idempotent script            | Accepted |
| [0016](0016-isolated-chart-runner.md)                          | Execute generated chart code in an isolated runner                             | Accepted |
| [0017](0017-live-azure-segment.md)                             | Include a live Azure segment in the talk                                       | Accepted |
| [0018](0018-offline-identity-simulator.md)                     | Provide an offline identity simulator as a stage fallback                      | Accepted |
| [0019](0019-fail-closed-control-contract.md)                   | Enforce a fail-closed contract for every solution control                      | Accepted |
| [0020](0020-indirect-injection-containment.md)                 | Contain indirect prompt injection from tool results                            | Accepted |
| [0021](0021-output-policy-for-clinical-advice.md)              | Screen agent replies for clinical advice                                       | Accepted |
| [0022](0022-local-azure-credential-in-compose.md)              | Provide Azure credentials to solution containers in Compose                    | Accepted |
| [0023](0023-vertical-slices-with-tagged-checkpoints.md)        | Deliver in vertical slices with tagged checkpoints                             | Accepted |
| [0024](0024-podman-container-engine.md)                        | Use Podman as the container engine                                             | Accepted |
| [0025](0025-browser-chat-client.md)                            | Add a Vue browser AG-UI client with its own Entra SPA registration             | Accepted |
