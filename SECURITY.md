---
title: Security policy
description: How to report a vulnerability in the OWASP agents sample, what is in scope, and which weaknesses are intentional
---

This repository is an educational sample. The `starter/` stack is insecure on purpose, and the `solution/` stack demonstrates one control per risk from the [OWASP Top 10 for Agentic Applications](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/). Neither stack is a production or clinical system, there are no supported versions, and fixes are made on `main` on a best-effort basis.

## Report a vulnerability privately

Report security problems through [GitHub private vulnerability reporting](https://github.com/willvelida/owasp-agents-sample/security/advisories/new). Do not open a public issue, pull request, or discussion for them.

Report privately when you find:

* A weakness in `solution/`, including the browser client in `solution/ui/`, its infrastructure in `solution/infra/`, and its scripts in `solution/scripts/`. This includes a control that can be bypassed, such as an attack that the red team expects to be blocked but succeeds.
* A weakness in `client/` or `redteam/`.
* A weakness in the CI workflows, dependency pinning, container images, or anything else in the supply chain.
* Any exposed secret, key, token, or live cloud resource, in any part of the repository. This includes the starter's model key and its Azure resources.

## What to include

* The affected component and file, and the target if it applies (`starter`, `solution-local`, `solution-offline`, or `solution-azure`).
* Steps to reproduce, and what you expected to happen.
* The impact: what an attacker could read, change, or run.

Use the synthetic seed data only. Don't include real health data, and don't paste working secrets, keys, tenant IDs, or subscription IDs into the report. Describe where you found them instead.

## Not a vulnerability

* **Intentional starter weaknesses.** Every deliberate weakness in `starter/` carries a `# ASI0x (starter):` comment and is listed in the [starter's weakness markers](starter/README.md#weakness-markers). These are teaching examples. You can discuss them, or suggest a more realistic version, in a [public issue](https://github.com/willvelida/owasp-agents-sample/issues/new/choose).
* **The synthetic seed data.** The users, canaries, and attack artefacts in `data/seed/` are fictional and public by design.

If you aren't sure whether something is intentional, report it privately.

## What happens next

The maintainer reviews reports as time allows. There is no response-time commitment. When a report is confirmed, the fix lands on `main` and the advisory is published with credit, unless you ask not to be named.
