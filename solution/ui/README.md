---
title: Browser chat UI (solution)
description: Text-only Vue 3 client for the Biotrackr solution chat API, with MSAL sign-in, AG-UI over SSE, and strict browser headers
ms.date: 2026-10-23
ms.topic: how-to
---

## Overview

`solution/ui` is a small browser client for the solution's chat API. It signs alice or bob in with MSAL.js through the `biotrackr-demo-spa` Entra app. It sends AG-UI runs in the same request shape as the CLI in `client/`, and it renders every event as plain text. Every ASI03 control stays on the server: chat-api validates the bearer, and the CORS allowlist only lets this origin read responses.

The browser client is optional; the [CLI](../../client/README.md) reaches every solution target without it. There are three ways to get a browser in front of the solution, and they are easy to confuse:

| Option | What it is | Sign-in | Where it is documented |
|--------|------------|---------|------------------------|
| This client, local | A Vite dev server on `http://localhost:5173/` that you start with `npm run dev`; it is not a Compose service | Real Entra sign-in as `biotrackr-alice` or `biotrackr-bob` | [Run locally](#run-locally) |
| This client, deployed | The `chat-ui` Container App that `azd up` deploys from [Containerfile](Containerfile) | Real Entra sign-in | [Container image](#container-image) |
| DevUI | The Agent Framework developer UI on `127.0.0.1:8090`, running the agent in-process | Simulated: each run signs in `DEVUI_USER` (default alice) at the stage-only simulator, so the solution allows it only in offline mode | [solution/README.md](../README.md#run-locally-offline-mode) |

This client does not work with the simulated-identity (offline) route, because it signs in with Entra only. It needs the Entra objects from [provision_agent_id.ps1](../scripts/README.md), and the SPA's redirect URIs, chat-api's `CORS_ALLOWED_ORIGINS`, and chat-api's `ALLOWED_CLIENT_APP_IDS` must all agree ([SPA redirect URIs](../scripts/README.md#spa-redirect-uris)).

| Part | File | Notes |
|------|------|-------|
| Transport | [src/agui.ts](src/agui.ts) | Run and resume bodies, SSE parser, 180 s idle timeout. Framework-free. |
| Reducer | [src/events.ts](src/events.ts) | Pure `(state, event) => state`, with parity to the CLI renderer. Framework-free. |
| Components | [src/components/](src/components/) | Text-only rendering, plus the approval dialog (Approve or Reject only). |
| Sign-in | [src/auth.ts](src/auth.ts) | `AuthProvider` seam with an MSAL redirect implementation and a `sessionStorage` cache. |
| Runtime config | [src/config.ts](src/config.ts) | Loads `/config.json` and rejects anything outside the four-key contract. |
| Thread pinning | [src/threads.ts](src/threads.ts) | A thread belongs to the account that started it. |

## Security rules

* Data reaches the DOM only through Vue `{{ }}` interpolation. ESLint fails the build on `v-html`, on `innerHTML`, `outerHTML`, or `srcdoc` bindings, and on object or dynamic `v-bind`. It also fails on `innerHTML`, `insertAdjacentHTML`, `document.write`, `eval`, string timers, and `localStorage` in scripts. Vue's runtime writes `innerHTML` through its own Trusted Types policy, so these lint rules, not the CSP, are the binding XSS control.
* Tokens never enter Vue reactive state, a URL, a log, or the DOM. MSAL keeps them in `sessionStorage`, and nothing uses `localStorage`.
* The approval dialog shows the full tool arguments and sends only `{"accepted": true|false}`. chat-api rejects any other payload with 400.

## Prerequisites

* Node 24.22.0 or a later 24.x (`engines.node` is `>=24.22.0 <25`, and `.npmrc` sets `engine-strict=true`) with its bundled npm.
* `.npmrc` also sets `min-release-age=7`, so npm refuses package versions published less than 7 days ago, and `save-exact=true`.
* Install with `npm ci --ignore-scripts` only.

## Run locally

1. Start the solution in entra mode (see [../README.md](../README.md), "Run locally (entra mode)"). Compose sets `CORS_ALLOWED_ORIGINS=http://localhost:5173` and accepts tokens from the CLI and SPA apps.
2. Write `public/config.json` (gitignored) with the ids from `solution/.env`:

   ```json
   {
     "tenantId": "<TENANT_ID>",
     "spaAppId": "<SPA_APP_ID>",
     "blueprintAppId": "<BLUEPRINT_APP_ID>",
     "chatApiUrl": "http://127.0.0.1:8000"
   }
   ```

   Only these four keys are accepted. `chatApiUrl` must be an origin with no path: https, or http on loopback only.
3. Install and start the dev server:

   ```powershell
   npm ci --ignore-scripts
   npm run dev
   ```

4. Open `http://localhost:5173/` (the port is fixed to match the SPA redirect URI) and sign in. The tenant may ask for MFA, and the first sign-in may show a one-time consent for the basic OIDC scopes.

## Test

```powershell
npm run lint
npm run typecheck
npm test
npm run build
```

`npm test` runs Vitest with jsdom. It covers the transport, the reducer, config validation, thread pinning, and component rendering, including HTML and markdown payloads rendered as text.

### Browser smoke tests (Playwright)

```powershell
npx playwright install chromium   # once per machine
npm run e2e
```

[playwright.config.ts](playwright.config.ts) builds a test-mode bundle (`npm run build:e2e`, Vite mode `e2e`, output `dist-e2e/`) and serves it with `vite preview`. In that mode, [src/auth-stub.ts](src/auth-stub.ts) replaces MSAL with a stub `AuthProvider` that returns a fake token, so the suite never touches Entra or a password. `/config.json` and every chat-api call are routed to the committed fixtures in [e2e/fixtures/](e2e/fixtures/), so these tests check the client's rendering and requests, not a real chat with the model. The specs cover:

* a normal answer, and a tool call with its raw result
* an approval interrupt and its decision-only resume (the request body is asserted)
* `RUN_ERROR`, a kill-switch refusal, and a 401
* the poisoned note: no `img` or `a` elements, and no request to `attacker.example`
* the bearer going only to chat-api, with nothing in `localStorage`

A production build never contains the stub: `import.meta.env.MODE` is replaced at build time and the import is dropped. To check, search `dist/` after `npm run build` for the marker `biotrackr-e2e-stub-auth-provider`; it should return no matches.

## Container image

[Containerfile](Containerfile) builds the client in a digest-pinned `node:24.22.0-alpine` stage. It then serves `dist/` from digest-pinned `nginx-unprivileged` as uid 101 on port 8080.

```powershell
podman build -f Containerfile -t localhost/biotrackr-chat-ui:dev .
podman run --rm -p 127.0.0.1:8080:8080 `
  -e TENANT_ID=<guid> -e SPA_APP_ID=<guid> -e BLUEPRINT_APP_ID=<guid> `
  -e CHAT_API_URL=https://<chat-api-host> localhost/biotrackr-chat-ui:dev
```

At start, [nginx/15-biotrackr-config.sh](nginx/15-biotrackr-config.sh) validates the four variables (three GUIDs and an https origin) and writes `/config.json`. The container stops if any value is missing or malformed. The image's envsubst step then renders [nginx/default.conf.template](nginx/default.conf.template), which puts `CHAT_API_URL` into the CSP. On Azure, Bicep sets these four variables on the `chat-ui` Container App, and there are no secrets.

Every response carries these headers, and `/config.json` also gets `Cache-Control: no-store`:

```text
Content-Security-Policy: default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self' https://login.microsoftonline.com <CHAT_API_URL>; base-uri 'none'; form-action 'none'; frame-ancestors 'none'; require-trusted-types-for 'script'
X-Frame-Options: DENY
Referrer-Policy: no-referrer
X-Content-Type-Options: nosniff
```
