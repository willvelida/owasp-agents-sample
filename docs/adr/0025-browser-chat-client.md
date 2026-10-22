---
title: "ADR-0025: Add a Vue browser AG-UI client with its own Entra SPA registration"
description: Add a text-only Vue 3 browser client for the solution, signed in through a dedicated Entra SPA app, served by a third Container App, and allowed by an exact-origin CORS policy on chat-api
ms.date: 2026-10-22
ms.topic: reference
---

## Status

Accepted on 2026-10-22 (slice S7). Amends [ADR-0012](0012-demo-clients.md).

## Context

[ADR-0012](0012-demo-clients.md) made the AG-UI CLI the demo client and rejected a custom web chat as too much work before the talk. The CLI shows per-user identity and approvals, but the audience sees a terminal, one user at a time, and an approval prompt as a `y/N` question.

A browser makes two things visible on stage: alice and bob side by side in two windows, and the ASI09 approval as a dialog that shows the full tool arguments. The constraint is that every ASI03 control must stay on the server and unchanged. chat-api validates the bearer (audience, scope, and allowed client), binds sessions to the caller's oid, and rejects edited approvals. A browser client can add surface, but it must not weaken those checks.

## Decision

* **Client.** A Vue 3 app built with Vite in `solution/ui`. There is no chat framework, router, store, or component library. The AG-UI transport (`src/agui.ts`) and the event reducer (`src/events.ts`) are framework-free TypeScript that mirror the CLI's request body and renderer. `@ag-ui/core` is used for types only. The direct runtime dependencies are `@azure/msal-browser` and `vue`.
* **Rendering.** Text only. Data reaches the DOM through Vue `{{ }}` interpolation. ESLint fails on `v-html`, on `innerHTML`, `outerHTML`, or `srcdoc` bindings, on object or dynamic `v-bind`, and on HTML sinks, `eval`, string timers, and `localStorage` in scripts. There is no markdown rendering, and no attribute is bound to event data.
* **Approvals.** The dialog shows the tool name and the complete arguments and sends one resume with `{"accepted": true|false}` per interrupt. chat-api already rejects any other payload with 400.
* **Identity.** A new Entra app, `biotrackr-demo-spa`, with SPA redirect URIs only (the local Vite origin and the deployed `chat-ui` URL) and no credentials. It is tagged `biotrackr-blueprint` and pre-authorised on the Blueprint's `access_as_user` next to `biotrackr-demo-cli`. chat-api's `ALLOWED_CLIENT_APP_IDS` lists both clients, so the browser has its own `azp` and can be revoked on its own. The provisioning script finds the app by its stored id, or by name only when the single match carries the tag.
* **Sign-in.** MSAL.js redirect flow with `sessionStorage`. Tokens never enter Vue reactive state, a URL, or the DOM. Each conversation is pinned to the account that started it, the browser form of the CLI's per-user oid check.
* **CORS.** chat-api adds Starlette `CORSMiddleware` from `CORS_ALLOWED_ORIGINS`: exact origins, `POST` only, `authorization` and `content-type` headers, no credentials, and `max_age` 600. A wildcard or a path-bearing origin stops startup, and the middleware is absent when the variable is unset. Preflight is answered before routing, so it never reaches `RequireUser` or the agent ([ADR-0019](0019-fail-closed-control-contract.md)).
* **Hosting.** A third Container App, `chat-ui`, runs a digest-pinned `nginx-unprivileged` image as a non-root user on port 8080. It has one always-on replica and its own user-assigned identity with AcrPull only. nginx sets a strict CSP (`default-src 'none'`, `connect-src` limited to itself, Entra, and chat-api, `frame-ancestors 'none'`, and `require-trusted-types-for 'script'`) and the frame, referrer, and content-type headers. At start, the container validates its four non-secret settings and renders `/config.json`.
* **Demo.** The browser is the solution segment's surface at the talk. The CLI stays for the starter segment, for the red team, and as the verbatim recovery path. DevUI stays local-only.
* **Delivery.** S7 is an extra slice under [ADR-0023](0023-vertical-slices-with-tagged-checkpoints.md), with the same checkpoint and an annotated `s7-browser-ui` tag, and a cut line that falls back to `s6-talk-ready`.

## Consequences

### Positive

* Every ASI03 control is unchanged. The browser is one more client of the same endpoint, with its own revocable `azp`.
* The approval dialog and two concurrent users are visible to the audience.
* The transport and reducer are small, framework-free, and unit-tested. A Playwright suite with a stub sign-in and recorded streams runs in CI, and CI also checks the real image's headers.

### Negative

* Vue's runtime registers a pass-through Trusted Types policy named `vue` and writes `innerHTML` for `v-html` and `innerHTML` bindings. The CSP therefore does not stop an HTML sink reached through Vue, and the lint rules are the binding XSS control.
* The production npm tree is 26 packages (`vue` declares its compiler and SSR packages as dependencies). Only the runtime packages reach the browser bundle, but the SBOM and Dependabot cover all of them.
* One more Entra object, one more Container App with its identity, and one more `OPTIONS` answer on chat-api. `chat-ui` costs about $8 a month at one idle replica.
* The tenant may ask for MFA at browser sign-in, and MSAL keeps tokens per tab, so the pre-show sign-ins are done in windows that stay open.

## Alternatives considered

| Alternative                                          | Reason not chosen                                                                                                                   |
|------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------|
| Plain TypeScript client (no framework)               | The research recommendation; replaced by Vue by user decision on 2026-10-22. The transport and reducer stay framework-free           |
| React with Vite                                      | Viable, but not chosen by user decision on 2026-10-22; JSX escaping would be the same kind of control as Vue interpolation           |
| `@ag-ui/client` 1.0.3                                | Resends the full client-side history on every run, adds rxjs, zod, and protobuf, and still needs a custom decision-only resume       |
| CopilotKit                                           | Runtime-centric, renders markdown with raw HTML, sends browser telemetry, and its schema-driven approvals do not fit a yes/no resume |
| assistant-ui AG-UI adapter                           | Pinned to a pre-1.0 client without interrupts                                                                                       |
| SPA redirect on `biotrackr-demo-cli`                 | Mixes device-code and browser clients under one `azp`, so neither can be revoked alone                                              |
| MSAL `memoryStorage` with popups                     | Popups are unreliable on stage, and every reload signs in again                                                                     |
| Static Web Apps                                      | Not available in australiaeast, and adds a second deployment path                                                                   |
| Static files served by chat-api                      | Grows the identity-bearing service's surface and couples UI and API deploys                                                         |
| Container Apps `ingress.corsPolicy`                  | Cannot be tested locally, and its layering with the app is undocumented                                                             |

## References

* [ADR-0012: Drive demos through an AG-UI CLI client, DevUI, and PyRIT](0012-demo-clients.md)
* [ADR-0019: Enforce a fail-closed contract for every solution control](0019-fail-closed-control-contract.md)
* [ADR-0023: Deliver in vertical slices with tagged checkpoints](0023-vertical-slices-with-tagged-checkpoints.md)
* [Architecture](../architecture.md)
* [Browser chat UI](../../solution/ui/README.md)
