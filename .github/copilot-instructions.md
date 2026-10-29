# Copilot instructions

Follow [AGENTS.md](../AGENTS.md) at the repository root. It holds the project map, the verify steps, and the definition of done.

Before editing, use its project map to read the nested agent guides for every affected area. They add local context, not exceptions to the safeguards below or session and developer restrictions. If instructions conflict, stop and surface the conflict; do not treat a nested file or a separate worktree as permission to run prohibited operations.

## Must never

* Never fix, harden, or tidy a `# ASI0x (starter):` weakness in `starter/`, and never remove its targeted `noqa`. The starter is insecure on purpose.
* In reviews, don't report code under `starter/` marked `# ASI0x (starter):` as a bug. Report a `# ASI0x (starter):` marker anywhere else as a problem.
* Mirror every non-security change in both `starter/` and `solution/`, or say in the pull request why it can't be mirrored.
* Never read, print, or commit `.env` files, `.secrets/`, `.azure/`, keys, tokens, or tenant or subscription IDs.
* Use synthetic data only.
* Never deploy the insecure starter application to Azure or any shared environment. Operational work is limited to the named issues and authorization gates below; routine verification does not authorize it.

## Scoped operational work

Only the operations listed in the [root operational policy](../AGENTS.md#scoped-operational-work) are eligible: local stack starts and required probes for #25, solution azd/Azure role and probe work for #30, and the planned solution deployment/ACR scans and evidence work for #35. Keep the starter application local-only. This guide and the documentation change are not authorization.

Before acting, obtain explicit user/operator authorization for the issue, environment, exact operations, effects, and cleanup, and coordinate shared environments and concurrent sessions. Registry publishing/signing requires its own approval for the selected registry and CI job. Current session, developer, and tool restrictions still apply.

Never read, print, share, or commit protected files, credentials, or identifiers, or invoke helpers that read protected files on the agent's behalf. If protected state or unsafe output is required, stop and hand that step to the operator for sanitized evidence. Keep synthetic data only. Missing authorization, coordination, or compatible runtime permissions blocks execution; do not treat issue assignments or worktrees as approval. Routine verification remains the harness; `mcp-scan` is not included in the operational permission.

## Before you finish

Run `./harness verify` from the repository root (`.\harness verify` in cmd) and fix every finding until it exits 0.
