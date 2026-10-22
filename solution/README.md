---
title: Solution (hardened)
description: Hardened Python port of the Biotrackr chat agent, with a marked, tested control for each OWASP Agentic Top 10 risk, slice by slice
ms.date: 2026-10-23
ms.topic: how-to
---

## Overview

The solution keeps the [starter](../starter/README.md)'s file names, so `git diff --no-index starter solution` shows every control. Slice S1 (`s1-identity`) fixes ASI03: alice and bob sign in with Entra, the chat agent reaches the health MCP server on their behalf through an Entra Agent ID, and the MCP server returns only the token owner's data. Slice S2 (`s2-tools`) adds tool governance for ASI01, ASI02, and the runtime half of ASI04 (see [Tool governance](#tool-governance-asi01-asi02-asi04)). Slice S3 (`s3-reports`) adds the report agent with an isolated chart runner, an approval gate, a fail-closed reviewer, and an output guard for ASI05, ASI09, and the ASI07 baseline (see [Reports](#reports-asi05-asi07-asi09)). Slice S4 (`s4-operations`) bounds and screens conversation memory, adds timeouts, circuit breakers, and graceful degradation, and gives operators a hash-chained audit trail, per-user rogue detection, and a kill switch for ASI06, ASI08, and ASI10 (see [Operations](#operations-asi06-asi08-asi10)). Slice S5 (`s5-supply-chain`) signs every A2A request with a single-use, short-lived Ed25519 signature over the exact body (ASI07), and adds CI supply-chain evidence: Dependabot, CodeQL, SBOMs, lock checks, digest-pinned images, and AGT `mcp-scan` (ASI04; see [Supply chain](#supply-chain-asi04)). Slice S7 (`s7-browser-ui`) adds a text-only browser client in [ui/](ui/README.md) with its own Entra SPA app, and an exact-origin CORS policy on chat-api that leaves every ASI03 check unchanged ([ADR-0025](../docs/adr/0025-browser-chat-client.md)). It runs in three ways:

| Mode           | Identity                                                                 | Model and data                                                |
|----------------|--------------------------------------------------------------------------|---------------------------------------------------------------|
| Local, entra   | Entra users, Agent ID sidecar (Blueprint dev secret)                     | Solution Foundry project via your `az login`; Cosmos emulator |
| Local, offline | Simulated identity: a stage-only token simulator with the same claims replaces Entra sign-in ([ADR-0018](../docs/adr/0018-offline-identity-simulator.md)) | Still the solution Foundry project via your `az login`; Cosmos emulator. Chat needs the network and the cloud model |
| Azure          | Entra users, Agent ID sidecar (managed identity federated credential)    | Foundry and Cosmos DB through the managed identity            |

Every mode needs the solution's Foundry project, which `azd provision` creates in your subscription along with the Entra objects (see [Prerequisites](#prerequisites) and [Deploy to Azure](#deploy-to-azure)). The [root README](../README.md#choose-a-route) compares these modes with the starter.

Start here:

* To run it: [Prerequisites](#prerequisites), then [entra mode](#run-locally-entra-mode), [offline mode](#run-locally-offline-mode), the [browser UI](#run-the-browser-ui-locally-entra-mode), or [Deploy to Azure](#deploy-to-azure)
* To see the controls: [Control markers](#control-markers), then the sections by risk: [Identity flow](#identity-flow-asi03), [Tool governance](#tool-governance-asi01-asi02-asi04), [Reports](#reports-asi05-asi07-asi09), [Operations](#operations-asi06-asi08-asi10), [Supply chain](#supply-chain-asi04)
* To check them: [Test](#test) and the [red team](../redteam/README.md)

| Service         | Module                | Port (127.0.0.1) | Purpose                                                                      |
|-----------------|-----------------------|------------------|------------------------------------------------------------------------------|
| `cosmos`        | emulator              | 8081, 1234       | Cosmos DB vNext emulator                                                     |
| `seed`          | `seed`                | none             | Loads [data/seed](../data/seed/README.md) keyed by `ALICE_OID` and `BOB_OID` |
| `health-mcp`    | `health_mcp`          | 8001             | MCP server; every call needs an OBO bearer token                             |
| `chat-api`      | `chat_api`            | 8000             | MAF agent behind AG-UI; every call needs a user token                        |
| `report-agent`  | `report_agent`        | none             | A2A report agent; every call needs the chat agent's `Report.Generate` token  |
| `chart-runner`  | `chart_runner`        | none             | Isolated chart runner: no network, read-only, UID 10001, Unix socket only    |
| `entra-sidecar` | Entra SDK for AgentID | none             | OBO and app-only tokens, inside chat-api's network namespace on 127.0.0.1    |
| `local-issuer`  | `local_issuer`        | 8100             | Offline profile only: stage-only token simulator                             |

## Identity flow (ASI03)

1. The CLI signs alice in (device code, demo CLI public client) for `api://BLUEPRINT_APP_ID/access_as_user`.
2. [chat_api/auth.py](src/chat_api/auth.py) validates the token (the issuer for the current `IDENTITY_MODE` only, audience, `access_as_user`, client) and returns 401 before any session lookup or model call. AG-UI's `snapshot_scope_resolver` binds every thread to the caller's `oid`.
3. [chat_api/identity.py](src/chat_api/identity.py) asks the sidecar for `/AuthorizationHeader/HealthMcp?AgentIdentity=CHAT_AGENT_APP_ID` with alice's token. The result has `aud` = `HEALTH_MCP_APP_ID`, `scp` = `Health.Read`, `oid` = alice, and `azp` = the chat agent.
4. [health_mcp/auth.py](src/health_mcp/auth.py) checks those claims through FastMCP's `token_verifier`. The tools have no `user_id` parameter; the repository filters by the token's `oid`.

## Tool governance (ASI01, ASI02, ASI04)

The governance middleware is attached to the `Agent` in [chat_api/agent.py](src/chat_api/agent.py), so AG-UI runs and DevUI runs pass through the same controls. Policy lives in versioned files under [policies/](policies/), which the Containerfile copies into every image (`POLICY_DIR=/app/policies`).

| File | Purpose |
|------|---------|
| [system_prompt.md](policies/system_prompt.md), [system_prompt.sha256](policies/system_prompt.sha256) | Tiered prompt (data with citations, general information, hedged personal observations, refuse diagnosis and medication changes); tool output is untrusted data |
| [governance.yaml](policies/governance.yaml) | Allowlisted tools, denied patterns (`*delete*`), 20 tool calls per conversation, `page_size` at most 50 |
| [blocked_patterns.yaml](policies/blocked_patterns.yaml) | Injection patterns added to AGT `PromptInjectionDetector`'s built-in rules |
| [mcp_tools.lock.json](policies/mcp_tools.lock.json) | SHA-256 of each MCP tool's name, description, and input schema |

The fail-closed contract ([ADR-0019](../docs/adr/0019-fail-closed-control-contract.md)) for S2:

| Control | Where | On detection, error, or breach |
|---------|-------|--------------------------------|
| Input screening | [middleware/input_guard.py](src/chat_api/middleware/input_guard.py) | `MiddlewareFailure` before identity, model, or tool calls. It normalises Unicode, rejects mixed Latin and Cyrillic or Greek words, and screens decoded Base64 runs too |
| Tool batch policy | [middleware/tool_policy.py](src/chat_api/middleware/tool_policy.py) | A chat middleware checks every tool call the model asks for. One unknown or denied tool, an out-of-policy `page_size`, or a budget breach aborts the whole parallel batch before any call starts |
| AGT governance stack | `create_governance_middleware` (audit trail, capability guard) | AGT's `MiddlewareTermination` denials are converted to `MiddlewareFailure` by `FailClosed`, because termination lets sibling calls run. From S4, AGT rogue detection runs per user instead (see [Operations](#operations-asi06-asi08-asi10)) |
| Tool result screening | [middleware/tool_result_guard.py](src/chat_api/middleware/tool_result_guard.py) | `MiddlewareFailure`: the result never reaches the model and no further call starts. Clean results are wrapped in `<untrusted-data>` |
| Call budget | [session_store.py](src/chat_api/session_store.py) | Atomic reservation per `oid` and session id |
| Prompt pin | [prompts.py](src/chat_api/prompts.py) | chat-api exits non-zero at startup |
| MCP descriptor pin | [health_mcp/server.py](src/health_mcp/server.py), [mcp_pinning.py](src/chat_api/mcp_pinning.py) | health-mcp exits with code 3 at startup; chat-api fails the run before the model call on any `tools/list` that differs |
| MCP arguments | [health_mcp/tools.py](src/health_mcp/tools.py) | `{"error": ...}` without a Cosmos DB query for bad dates, reversed ranges, or ranges over 31 days; `page_size` clamped to 1..50 |
| Notes withheld | [health_mcp/tools.py](src/health_mcp/tools.py) | Free-text `notes` never leave the MCP server; results carry `has_note: true` ([ADR-0020](../docs/adr/0020-indirect-injection-containment.md)) |

`delete_records` is gone, and tool descriptions are static. The starter's `rugpull.env` has no effect here: Compose loads it for health-mcp, but the descriptors still match the lock.

> [!NOTE]
> AGT 5.0's `create_governance_middleware(policy=GovernancePolicy(...))` path needs the ACS engine, which ships for Linux x86_64 only. The solution uses the adapter's allow-list path and `PromptInjectionDetector`, which run on arm64 and Windows too.

The AG-UI endpoint never sends exception text to clients. A blocked run ends with `RUN_ERROR` code `MiddlewareFailure`; the reason is in the chat-api log.

After a reviewed change to a tool or to the prompt, regenerate the pins:

```powershell
uv run python -m governance.descriptors --write
(Get-FileHash policies/system_prompt.md -Algorithm SHA256).Hash.ToLower() + "  system_prompt.md" | Set-Content -NoNewline policies/system_prompt.sha256
```

[.gitattributes](../.gitattributes) checks the policy files out with LF on every platform, so the prompt hash is the same everywhere.

## Reports (ASI05, ASI07, ASI09)

`generate_report` sends a chart request to the [report agent](src/report_agent/app.py) over A2A (a2a-sdk 1.2.3, JSON-RPC). The report agent generates matplotlib code with the starter's own generator prompt, so the controls below do the work, not the model's restraint.

| Control | Where | On detection, error, or breach |
|---------|-------|--------------------------------|
| Approval | `approval_required` in [governance.yaml](policies/governance.yaml), [tools_report.py](src/chat_api/tools_report.py) | The run ends with an AG-UI interrupt; nothing runs until the user approves. A rejection, a forged interrupt id, or another user's resume never runs the tool |
| Decision-only resumes | [approvals.py](src/chat_api/approvals.py) | A resume that carries edited arguments (`editedArgs` or extra payload keys) gets HTTP 400 before the agent runs |
| Report cap | `tool_limits` in [governance.yaml](policies/governance.yaml), [session_store.py](src/chat_api/session_store.py) | A third `generate_report` in a conversation aborts the batch (`MiddlewareFailure`) |
| Caller identity | [identity.py](src/chat_api/identity.py), [report_agent/app.py](src/report_agent/app.py) | Every A2A call carries an app-only token from the sidecar's autonomous route (`aud` = `REPORT_API_APP_ID`, role `Report.Generate`, `azp` = chat agent). Anything else gets 401 before any work |
| Signed requests (S5) | [a2a_security.py](src/report_agent/a2a_security.py) | After the token check, every request needs an `X-A2A-Signature` from the chat agent's Ed25519 key over the method, path, a SHA-256 of the exact body, a fresh nonce, the time it was signed, and the schema version. Missing, malformed, unknown key, bad signature, body changed, older than 60 s, more than 5 s in the future, a nonce seen before, or a full replay cache: 401 (503 for the full cache) with the reason, before any A2A handler runs. chat-api signs each send (so each retried poll gets a fresh nonce); without a signing key it sends nothing and the tool answers `unavailable` |
| Typed payloads | [report_agent/schemas.py](src/report_agent/schemas.py) | `schema_version` must be `biotrackr.report/v1` (S5). Unknown fields, more than 62 points, odd labels, non-finite values, or a long request: `denied` (`rejected_by: validation`) |
| Static check | [static_check.py](src/report_agent/static_check.py) | Imports outside `matplotlib`, `numpy`, `math`, `datetime`; `eval`, `exec`, `open`, `getattr`, `__import__`, dunder names and strings; `os`, `sys`, `subprocess`, `socket`; parse failure: `denied` (`rejected_by: static_check`) |
| Isolated runner | [chart_runner/runner.py](src/chart_runner/runner.py), [chart_runner.Containerfile](chart_runner.Containerfile) | Locally a no-network, read-only, non-root container on a Unix socket; on Azure a Dynamic Sessions pool with egress disabled. Fresh worker per job, empty environment, rlimits, 10 s; PNG under 1 MB only. Failure: `denied` (`rejected_by: runner`) |
| Reviewer | [reviewer.py](src/report_agent/reviewer.py) | Fresh agent per review; error, 10 s timeout, or a verdict other than `{"approved": <bool>}`: `denied` (`rejected_by: reviewer`), no chart |
| Output guard | [middleware/output_guard.py](src/chat_api/middleware/output_guard.py) | Every reply with text is held back and classified by a separate, tool-less model call. Unsafe, indeterminate, an error, or 5 s: the fixed refusal and disclaimer replace the reply, in the stream and in the history |

`REPORT_AGENT_CANARY=CANARY-ENV-R5X` is set in report-agent only (a Container Apps secret on Azure), as in the starter. `GET /diagnostics/report-agent` on chat-api (signed-in users only) reports whether report-agent is up and whether its canary is set, as booleans; the red team uses it as the ASI05 oracle. The CLI asks before approving a report (`--approve yes|no` for scripts) and shows a spinner while the report is generated and reviewed.

The token says who is calling; the signature covers what the token cannot: a changed body and a replayed request. Signing keys (ASI07):

* Locally, the one-shot `a2a-keys` service writes the key pair once into two volumes: the private key (mode 0400) into `a2a-signing`, mounted read-only by chat-api only, and the public key into `a2a-verify`, mounted read-only by report-agent only. Rotate with `podman compose down`, `podman volume rm biotrackr-solution_a2a-signing biotrackr-solution_a2a-verify`, and `up`.
* On Azure, the `preprovision` hook generates the pair once per azd environment (`A2A_SIGNING_KEY`, `A2A_VERIFY_KEY`). The private key reaches Azure only as a Container Apps secret on chat-api; report-agent gets the public key. Rotate by clearing both values (`azd env set A2A_SIGNING_KEY ""`) and running `azd provision`.
* report-agent accepts several public keys (`A2A_VERIFY_KEYS`, comma separated) for overlap during a rotation, and exits at startup if none loads.
* The replay cache is in-process, like the A2A task store, so report-agent runs one replica: a second replica would not see the first one's replay cache or tasks. A restart clears it, which is safe because nothing older than 60 s is accepted anyway.

The signature format follows AGT `agentmesh` conventions (base64 raw Ed25519 keys, `key-<sha256[:16]>` key ids), but the signing and verification are this sample's own: `agentmesh` 5.0 has no way to load a persistent key, no request envelope, and no replay protection.

## Operations (ASI06, ASI08, ASI10)

Slice S4 (`s4-operations`) bounds the agent's memory, keeps it answering when a dependency fails, and gives operators an audit trail, per-user rogue detection, and a kill switch. Limits live in [governance.yaml](policies/governance.yaml).

| Control | Where | On detection, error, or breach |
|---------|-------|--------------------------------|
| Bounded memory | [history.py](src/chat_api/history.py), [middleware/memory_guard.py](src/chat_api/middleware/memory_guard.py) | A run sees at most the last 50 messages (cut at a user turn); a conversation keeps its last 100; every text field is capped at 10,000 characters |
| Partitioned, expiring history | `chat_history` container ([seed](src/seed/load.py), [core.bicep](infra/modules/core.bicep)) | Partition `/userId`: every read and write names the caller's `oid`, so another user's conversation is not there. Default TTL 90 days after the last write |
| Memory screening | AGT `MemoryGuard` in [memory_guard.py](src/chat_api/middleware/memory_guard.py) | A turn with any high or critical alert (injection phrasing, code, hidden-instruction markup carrying a standing rule, bidirectional characters) is not written at all. Each stored message carries AGT's SHA-256; a turn that fails it, or that is flagged later, is left out when the history is loaded |
| Timeouts and retries | [middleware/resilience.py](src/chat_api/middleware/resilience.py), [identity.py](src/chat_api/identity.py), [tools_report.py](src/chat_api/tools_report.py) | Connect 5 s and read 30 s on every HTTP dependency, the MCP client's HTTP client and session, and the model client. At most 2 retries with full jitter, only when a dependency cannot be reached (never after a timeout, never for report submissions) |
| Circuit breakers | `CircuitBreaker` for health-mcp and the report agent | After 3 consecutive failures, calls fail fast for 30 s; one trial call then closes or reopens it. Opening and closing are audited |
| Per-user MCP sessions | [mcp_pool.py](src/chat_api/mcp_pool.py) | A bulkhead: each signed-in user has their own health MCP session (at most 256, least recently used closed first), so one user's burst or stalled call cannot hold another user's tool calls. A refreshed token for the same user reuses the session; another user's principal is refused. The breaker stays shared |
| Graceful degradation | `GracefulDegradation` | A run that failed because a dependency is down gets a short "try again" reply, which still passes the output guard. Control failures (`MiddlewareFailure`, identity, descriptor pins) are never degraded |
| Token budget | `max_tokens_per_conversation`, `max_output_tokens` | 400,000 model tokens per conversation (counted from the model's usage after each call) and 2,000 per reply; then a fixed reply before any model call. The tool loop has at most 8 model round trips and 120 s |
| Audit trail | [middleware/audit.py](src/chat_api/middleware/audit.py) | AGT `AuditTrailMiddleware`, the capability guard, rogue detection, and the solution's own controls write AGT `AuditEntry` records chained by SHA-256 to the Cosmos DB `audit` container. `data` keeps scalar allowlisted fields only, so tool results (AGT's `result_preview`) and exception text never reach it. Refused runs are recorded |
| Rogue detection | [middleware/rogue_guard.py](src/chat_api/middleware/rogue_guard.py) | One AGT `RogueAgentDetector` per signed-in user (quarantine at `critical`) plus a ceiling of 50 executed tool calls in 120 s across that user's conversations, above the 20-call conversation budget. Either quarantines that user's agent for 300 s: tool calls abort their batch and new runs get a fixed reply. On release the user starts with a fresh detector and call window. Other users are not affected |
| Kill switch | [middleware/kill_switch.py](src/chat_api/middleware/kill_switch.py) | Checked before every run and every tool call. Locally `AGENT_KILL_SWITCH`; on Azure the `agent-kill-switch` key in App Configuration, read with the managed identity and cached for 10 s. A failed read is retried once (a cold managed identity token can time out on a new revision). An engaged switch, a store still unreadable after the retry, a missing key, or an unknown value refuses the run with a fixed reply before the model is called |
| Telemetry | [app.py](src/chat_api/app.py) | OpenTelemetry with `enable_sensitive_data=False`: no prompts, tool arguments, or health data in traces |

The kill switch, a quarantine, and an exhausted token budget answer with fixed text instead of an error, because AG-UI reduces every exception to a generic `RUN_ERROR`. Nothing else runs for those turns, and nothing is written to the history.

Flip the kill switch:

```powershell
# Local: chat-api reads AGENT_KILL_SWITCH at each run; recreate it (and the sidecar in its network namespace).
$env:AGENT_KILL_SWITCH = "on"
podman compose rm --stop --force entra-sidecar; podman compose up -d --no-deps chat-api; podman compose up -d --no-deps entra-sidecar
# Azure (takes effect within 10 s):
az appconfig kv set --endpoint (azd env get-value APP_CONFIG_ENDPOINT) --auth-mode login --key agent-kill-switch --value on --yes
```

Set it back to `off` the same way.

Verify the stored audit chains (edited entries, broken links, and gaps in the sequence are reported):

```powershell
uv run --env-file .env python -m chat_api.middleware.audit          # local emulator
podman compose exec chat-api python -m chat_api.middleware.audit    # inside the stack
```

The tool and token budgets, quarantines, and circuit breakers are in-process, so chat-api runs one replica on Azure.

## Supply chain (ASI04)

Slice S5 adds evidence that what runs is what was reviewed. The runtime half (exact pins, hashed lock, MCP descriptor pinning) arrived in S2.

| Control | Where | On detection, error, or breach |
|---------|-------|--------------------------------|
| Lock checks | [ci.yml](../.github/workflows/ci.yml) | `uv lock --check`, then `uv sync --locked`, for starter, solution, client, and redteam. A lock out of date with `pyproject.toml` fails the build |
| Lint and tests | [ci.yml](../.github/workflows/ci.yml) | `ruff check`, `ruff format --check`, and the solution's unit tests on every push and pull request |
| SBOM | [ci.yml](../.github/workflows/ci.yml) | SPDX JSON for each project, including `ui/` (`anchore/sbom-action`), kept as a workflow artefact |
| MCP scan | [ci_mcp_scan.py](scripts/ci_mcp_scan.py) | AGT `mcp-scan` against the live health-mcp server (offline mode, stage-only token). Any finding, inspection error, or a tool count different from the descriptor lock fails the build |
| ASI07 red team | [ci.yml](../.github/workflows/ci.yml) | The model-free ASI07 attacks against the offline stack; any accepted forged, replayed, or tampered request fails the build |
| No stage-only identity in Azure | [ci.yml](../.github/workflows/ci.yml) | Any `local_issuer` or DevUI reference in `infra/` or `azure.yaml` fails the build |
| Browser UI | [ci.yml](../.github/workflows/ci.yml) (`web`) | `npm ci --ignore-scripts`, lint (including the XSS bans), typecheck, unit and component tests, build, a check that the e2e stub sign-in is absent from `dist/`, the Playwright smoke suite, and the image's CSP and header set |
| CodeQL | [codeql.yml](../.github/workflows/codeql.yml) | `security-extended` queries for Python, the browser UI (JavaScript and TypeScript, including `.vue` files), and the workflows, on push, pull request, and weekly |
| Dependabot | [dependabot.yml](../.github/dependabot.yml) | Weekly pull requests for uv (all four projects), npm (`ui/`, with a 7-day cooldown), GitHub Actions, Containerfiles (including `ui/`), and Compose images, each one gated by CI |
| npm pins | [ui/package.json](ui/package.json), [ui/.npmrc](ui/.npmrc) | Exact versions, a committed v3 lockfile, `npm ci --ignore-scripts` only, `min-release-age=7` (npm refuses releases younger than 7 days), and `engine-strict=true` |
| Pinned actions | [.github/workflows](../.github/workflows) | Every action by full commit SHA with a version comment; the repository requires SHA pinning. Read-only `GITHUB_TOKEN`, no `pull_request_target`, no credentials persisted by checkout |
| Pinned images | [Containerfile](Containerfile), [chart_runner.Containerfile](chart_runner.Containerfile), [ui/Containerfile](ui/Containerfile), [chat_api.bicep](infra/modules/chat_api.bicep) | Base images and uv by tag and digest (the UI's Node build stage and `nginx-unprivileged` runtime too). The Azure sidecar is `auth-sidecar` 1.1.2 by index digest |

Dependabot cannot see two pins, so bump them by hand: the sidecar digest in [chat_api.bicep](infra/modules/chat_api.bicep) (`podman manifest inspect` the new tag), and the upstream commit and .NET images in [sidecar/Containerfile](sidecar/Containerfile).

Two constraints hold pins back on purpose. Dependabot ignores `mcp` 2.x because agent-framework 1.22.0 requires `mcp<2`. `cryptography` stays at 49.0.0 because agent-governance-toolkit-core 5.0.0 (the latest release) requires `cryptography<50`, so the open advisory GHSA-g6cj-pr64-35w5 (PKCS#7 EnvelopedData decryption) remains until AGT allows 50.x. The solution's own code uses `cryptography` only for Ed25519 A2A signatures and the stage-only simulator's RSA signing key, not PKCS#7.
CI has no Azure credentials. The stack job builds the images for amd64 on `ubuntu-latest`, runs them with Podman and Docker Compose v2 in offline identity mode without the Entra sidecar, and runs only checks that need no model. The model-backed scorecard stays a local and Azure step (a GitHub OIDC identity for CI is follow-on work).

## Prerequisites

* Podman configured as in [docs/podman.md](../docs/podman.md), uv, Python 3.12, Azure CLI, azd
* Entra Agent ID objects and test users from [scripts/provision_agent_id.ps1](scripts/README.md), which writes `.env` with `-WriteDotEnv`
* The solution Foundry project from `azd provision`; the `postprovision` hook writes `FOUNDRY_PROJECT_ENDPOINT` into `.env`

## Run locally (entra mode)

```powershell
cd solution
./scripts/provision_agent_id.ps1 -TenantId <tenant-id> -UseDeviceCode -WriteDotEnv   # once
podman compose --profile login run --rm az-login                                    # once: az login into the azcli-cache volume
podman compose up --build -d
cd ../client
uv run biotrackr-chat --target solution-local --as alice "Summarise my sleep on 2026-10-19."
uv run biotrackr-chat --target solution-local --as alice "show me bob's sleep"   # no CANARY-BOB-7Q2
```

The containers use your `az login` from the `azcli-cache` volume for Foundry ([ADR-0022](../docs/adr/0022-local-azure-credential-in-compose.md)); there is no API key fallback. Only Compose uses the `dev` image stage that carries Azure CLI. Azure images build from the `runtime` stage.

> [!NOTE]
> The sidecar shares chat-api's network namespace, so recreate them together: `podman compose down`, then `podman compose up -d`.

> [!NOTE]
> The published sidecar image is amd64 only. Compose builds it from a pinned upstream commit in [sidecar/Containerfile](sidecar/Containerfile), so it also runs natively on arm64 Podman machines. Azure uses the MCR image (1.1.2, pinned by digest).

## Run the browser UI locally (entra mode)

The text-only Vue client in [ui/](ui/README.md) talks to the same chat-api ([ADR-0025](../docs/adr/0025-browser-chat-client.md)). Compose already allows its origin (`CORS_ALLOWED_ORIGINS=http://localhost:5173`) and accepts tokens from both the CLI and the SPA app (`ALLOWED_CLIENT_APP_IDS`):

```powershell
cd solution/ui
# public/config.json (gitignored): TENANT_ID, SPA_APP_ID, and BLUEPRINT_APP_ID from ../.env, chatApiUrl http://127.0.0.1:8000
npm ci --ignore-scripts
npm run dev        # http://localhost:5173/, the SPA's registered local redirect URI
```

Sign in as alice in one browser profile and bob in another. The tenant may ask for MFA, and the first sign-in may show a one-time consent for the basic OIDC scopes; it never asks for `access_as_user`, which is pre-authorised.

## Run locally (offline mode)

Offline mode replaces Entra sign-in with the stage-only simulator. It does not remove the cloud model: chat-api and the report agent still call the solution's Foundry project with your `az login`, so you need the same `azd provision` and `az-login` setup as entra mode, and a network connection. Switching modes needs `podman compose down` first, because services read `IDENTITY_MODE` only when they start.

```powershell
cd solution
podman compose down
$env:IDENTITY_MODE = "local"
podman compose --profile offline up --build -d
cd ../client
uv run biotrackr-chat --target solution-offline --as alice "Summarise my sleep on 2026-10-19."
```

> [!CAUTION]
> The simulator mints a token for anyone who can reach `127.0.0.1:8100`. It refuses to start when `CONTAINER_APP_NAME`, `CONTAINER_APP_ENV_DNS_SUFFIX`, `IDENTITY_ENDPOINT`, or `MSI_ENDPOINT` is set, and services in entra mode reject everything it signs.

DevUI runs the agent in-process and has no per-user sign-in, so the solution allows it only in offline mode, signed in as `DEVUI_USER` (default alice):

```powershell
$env:IDENTITY_MODE = "local"; uv run --env-file .env python -m chat_api.devui_main
```

## Deploy to Azure

> [!IMPORTANT]
> `azd up` creates billed resources in your subscription (Container Apps, a container registry, Cosmos DB, Foundry, App Configuration, a Dynamic Sessions pool, and monitoring) and writes Entra objects and two test users into your tenant. It needs the Entra roles and admin consent in [scripts/README.md](scripts/README.md#prerequisites), and operator approval in a shared tenant or subscription.

```powershell
cd solution
azd env new owasp-agents --location australiaeast
azd up            # first time; later slices use azd deploy when infra is unchanged
cd ../client
uv run biotrackr-chat --target solution-azure --as alice "Summarise my sleep on 2026-10-19."
```

`azd up` runs the hooks in order:

1. `preup` and `preprovision` create or reuse the Agent ID objects and write their IDs into the azd environment, and generate the A2A signing key pair once (`A2A_SIGNING_KEY`, `A2A_VERIFY_KEY`). (azd checks Bicep inputs before `preprovision` runs, so a fresh `azd up` needs `preup`.) When the registry already exists, they also build the chart runner image, so Bicep gives the session pool the real image.
2. Bicep provisions `rg-<env>`: Container Apps (workload profiles), ACR, two managed identities (one for chat-api and health-mcp, one for the report agent only), the `chartrunner` Dynamic Sessions pool with egress disabled, Cosmos DB with local auth disabled, Foundry with key auth disabled, and monitoring.
3. `postprovision` adds the Blueprint federated credential for the managed identity, seeds Cosmos DB with your Entra login, and on a fresh environment builds the chart runner image in ACR (linux/amd64, tagged by a content hash) and points the session pool at it ([build_chart_runner.ps1](scripts/hooks/build_chart_runner.ps1)). Until then the pool holds a placeholder image with no warm sessions. It then creates the `agent-kill-switch` key in App Configuration with `off` if it is missing ([kill_switch.ps1](scripts/hooks/kill_switch.ps1)); it never resets an existing value. Last, it adds the deployed `chat-ui` URL to the `biotrackr-demo-spa` redirect URIs (`provision_agent_id.ps1 -SpaRedirectUri`).
4. azd builds the images in ACR and deploys them, including `chat-ui` from [ui/Containerfile](ui/Containerfile).

Bicep also creates the App Configuration store (Standard, access keys disabled; chat-api's identity is Data Reader and you are Data Owner) and the Cosmos DB `chat_history` and `audit` containers.

Images build in ACR from the `runtime` stage. chat-api and chat-ui have external ingress; health-mcp and report-agent are internal, and the sidecar listens on 127.0.0.1 inside the chat-api replica. chat-ui serves the static browser client from non-root nginx with a strict CSP, runs with its own AcrPull-only identity, and holds no secrets. chat-api's `CORS_ALLOWED_ORIGINS` is set to exactly the chat-ui origin (`https://chat-ui.<environment default domain>`), and `ALLOWED_CLIENT_APP_IDS` to the CLI and SPA app ids. Open the browser client at `azd env get-value CHAT_UI_URL`.

To save costs between talks, tear the environment down with `azd down --purge` and rebuild it with `azd up`. The `predown` hook ([predown.ps1](scripts/hooks/predown.ps1)) first removes the Blueprint federated credential for the environment's managed identity. Entra objects, test users, and the azd environment values (including the A2A key pair) are kept. To remove the Entra objects and test users too, see [scripts/README.md](scripts/README.md#remove-everything). See [Teardown and rebuild](../docs/demo-runbook.md#teardown-and-rebuild) for timing and the steps after a rebuild.

## Control markers

Controls carry a `# ASI0x: <control>` comment. Weaknesses that later slices fix keep their `# ASI0x (starter): <why>` marker.

| Risk  | Where                                             | Control                                                                             |
|-------|---------------------------------------------------|-------------------------------------------------------------------------------------|
| ASI01 | `policies/system_prompt.md`, `src/chat_api/prompts.py` | (S2) Tiered, hash-pinned prompt; tool output treated as untrusted data         |
| ASI01 | `src/chat_api/middleware/input_guard.py`, `screening.py` | (S2) AGT injection screening on input, fail closed                           |
| ASI01 | `src/chat_api/middleware/tool_result_guard.py`    | (S2) Every tool result screened; abort on detection; clean results wrapped          |
| ASI01 | `src/health_mcp/tools.py`                         | (S2) Notes withheld; `has_note` flag only                                           |
| ASI02 | `policies/governance.yaml`, `src/chat_api/middleware/tool_policy.py` | (S2) Allowlist, denied patterns, `page_size` policy, whole-batch abort |
| ASI02 | `src/chat_api/session_store.py`                   | (S2) Atomic 20-call budget per `oid` and session                                    |
| ASI02 | `src/health_mcp/tools.py`, `repository.py`        | (S2) Read tools only; date and range validation; `page_size` clamped                |
| ASI03 | `src/auth_common/jwt_validator.py`                | One issuer per `IDENTITY_MODE`; audience, scope, client, tenant, expiry, `oid`      |
| ASI03 | `src/chat_api/auth.py`, `app.py`                  | Inbound JWT on every route; threads scoped to `oid`; `/conversations` owner-only    |
| ASI03 | `src/chat_api/identity.py`, `agent.py`            | OBO as the chat agent identity; fails closed before the model call                  |
| ASI03 | `src/chat_api/history.py`                         | Refuses to load or append to another user's session; reads only the caller's partition (S4) |
| ASI03 | `src/health_mcp/auth.py`, `tools.py`              | Token verifier (`aud`, `Health.Read`, `azp`); no `user_id` parameter                |
| ASI03 | `src/auth_common/azure_credential.py`, `agent.py` | Entra for Foundry and Cosmos DB; the key is used only for the plain-HTTP emulator   |
| ASI03 | `compose.yaml`, `infra/`                          | Sidecar on loopback only; internal MCP ingress; keyless Foundry and Cosmos DB       |
| ASI03 | `src/local_issuer/app.py`                         | Stage-only simulator: offline profile, 127.0.0.1, refuses Azure markers             |
| ASI04 | `pyproject.toml`, `uv.lock`, `Containerfile`      | Exact pins, hashed lock, `uv sync --frozen`; (S5) base images by digest             |
| ASI04 | `policies/mcp_tools.lock.json`, `src/governance/descriptors.py`, `src/chat_api/mcp_pinning.py` | (S2) MCP descriptor pinning at server startup and on every `tools/list` |
| ASI04 | `.github/`, `scripts/ci_mcp_scan.py`, `infra/modules/chat_api.bicep` | (S5) Dependabot, CodeQL, SBOM, lock checks, SHA-pinned actions, `mcp-scan`, sidecar by digest |
| ASI05 | `src/report_agent/static_check.py`                | (S3) AST allowlist, defence in depth                                                |
| ASI05 | `src/report_agent/executor.py`, `src/chart_runner/`, `compose.yaml`, `infra/modules/sessions_pool.bicep` | (S3) Code runs only in the isolated runner; never in-process |
| ASI06 | `src/chat_api/history.py`, `src/chat_api/middleware/memory_guard.py` | (S4) 50 hydrated, 100 stored, 10,000 characters per field; AGT `MemoryGuard` drops flagged turns; integrity on read |
| ASI06 | `src/seed/load.py`, `infra/modules/core.bicep`    | (S4) `chat_history` partitioned by `/userId` with a 90 day default TTL               |
| ASI07 | `src/report_agent/app.py`, `schemas.py`, `src/chat_api/identity.py`, `tools_report.py` | (S3) App-only `Report.Generate` token with `azp` check; typed payloads; pinned local agent card |
| ASI07 | `src/report_agent/a2a_security.py`, `compose.yaml`, `infra/` | (S5) Ed25519 signature over body hash, nonce, time, and schema version; 60 s window; replay cache; versioned schema; keys split between chat-api and report-agent |
| ASI08 | `src/chat_api/middleware/resilience.py`, `mcp_pool.py`, `agent.py`, `identity.py`, `tools_report.py` | (S4) Timeouts, jittered retries, circuit breakers, per-user MCP sessions, graceful degradation through the output guard, token budget |
| ASI09 | `src/chat_api/tools_report.py`, `approvals.py`, `policies/governance.yaml` | (S3) Approval before every report; decision-only resumes; two reports per conversation |
| ASI09 | `src/report_agent/reviewer.py`                    | (S3) Fresh-context reviewer, fails closed                                           |
| ASI09 | `src/chat_api/middleware/output_guard.py`         | (S3) Fail-closed output classifier with fixed refusal and disclaimer; (S4) dose steps framed as general or hypothetical count as unsafe |
| ASI10 | `src/chat_api/middleware/audit.py`                | (S4) Hash-chained AGT audit entries in Cosmos DB, no health payloads; chain verifier |
| ASI10 | `src/chat_api/middleware/rogue_guard.py`, `policies/governance.yaml` | (S4) Per-user AGT rogue detection and burst ceiling; quarantine per user      |
| ASI10 | `src/chat_api/middleware/kill_switch.py`, `infra/modules/appconfig.bicep` | (S4) Kill switch per run and per tool call; App Configuration on Azure; fails closed |
| ASI10 | `src/chat_api/app.py`                             | (S4) OpenTelemetry `enable_sensitive_data=False`                                    |

## Test

```powershell
uv run ruff check
uv run pytest                                                 # unit tests, no network
$env:RUN_INTEGRATION = "1"; uv run pytest tests/integration    # against the running entra-mode stack
```

The browser client has its own checks in `ui/`: `npm run lint`, `npm run typecheck`, `npm test` (Vitest), and `npm run e2e` (Playwright, stub sign-in). See [ui/README.md](ui/README.md#test).

The unit tests cover the fail-closed contract. S1: 401 with zero agent runs, MCP 401 with zero Cosmos queries, alice's token never reading bob's records, and the simulator's negative cases. S2: input screening with zero model and tool calls; a poisoned tool result with no further model or tool call; denied, unknown, and out-of-policy calls and budget breaches aborting whole parallel batches (streaming and non-streaming); concurrent budget reservations; prompt and descriptor tampering exiting non-zero in a subprocess; and the governed agent against the real MCP server in process. S3: the static-check corpus; runner jobs with an empty environment, a wall clock, and PNG-only output; report-agent caller checks (401 with zero pipeline work); validation, generator, static-check, runner, and reviewer faults all `denied` with no chart; output classifier faults (unsafe, indeterminate, error, timeout) giving the fixed refusal, streamed and multi-turn; and approvals through the real AG-UI endpoint (single budget reservation, replay, rejection, forged ids, another user's resume, edited arguments, the report cap). S4: an engaged, unreadable, or unknown kill switch with zero model and tool calls (also through AG-UI, as text rather than `RUN_ERROR`), the App Configuration cache and its fail-closed expiry, and one retry of a failed read that still refuses unless it reads `off` (S6); a burst across conversations quarantining only that user, AGT's per-user detector, and one full conversation never tripping the ceiling; MemoryGuard dropping a planted rule that input screening lets through, field, store, and hydration caps, partitioned reads, tampered turns left out, and the configured TTL (the emulator does not expire items); breaker, retry, and degradation behaviour (including MAF's real error for a refused MCP connection) with control failures never degraded, per-user MCP sessions against the real server (a refreshed token makes no new handshake, a stalled user does not hold another), and the degraded reply going through the output guard; token accounting; and the audit chain (no health payloads, refused runs recorded, edits and gaps detected). S5: every malformed, unsigned, wrongly signed, tampered, expired, future, or replayed A2A request refused with zero pipeline work, the token check before the signature check, a full replay cache failing closed, oversized bodies, unversioned payloads, unique nonces on every send including retried polls, and no request at all (and no token fetched) without a signing key. S7: chat-api's CORS policy (`tests/test_chat_cors.py`) answers preflight for the allowed origin with zero `RequireUser` calls and zero agent runs, refuses other origins, adds the allowed origin to 401 and streaming responses without allowing credentials, adds nothing when `CORS_ALLOWED_ORIGINS` is unset, and refuses to start on a wildcard or path-bearing origin. The integration tests check that health-mcp cannot reach the sidecar, that `DefaultAzureCredential` gets a Foundry token inside chat-api, that the chart runner has no network, no canary, no engine socket, no writes outside `/tmp`, and kills runaway jobs, and that the live containers have the S4 partition keys and TTL and the stored audit chains verify, and that the live output classifier rates a hypothetical dose step unsafe and a step count safe.
