# CLI client agent guide

Applies to `client/`. Read the [root guide](../AGENTS.md) first; local context does not relax its safeguards.

## Changes

* This client supplies target configuration and authentication to both the CLI and the red team. Read the [red-team guide](../redteam/AGENTS.md) when changing their shared behavior.
* Preserve per-user identity checks and thread isolation. Do not inspect token caches or load real environment values. Authentication and live chat for a named operational task require the [root operational gates](../AGENTS.md#scoped-operational-work); if the client requires protected files or would expose identifiers, hand the step to the operator instead.
* Keep AG-UI run/resume payloads, streamed events, errors, and approval decisions aligned with the [browser client](../solution/ui/AGENTS.md). A report resume sends a decision, not edited tool arguments.
* Keep target paths relative to their configuration file, not the caller's shell directory. Use synthetic targets and mocked transport responses for development checks.
* All real targets need a running stack and reach a cloud model. Invoking a target is not a harmless local check, including the offline-identity target.

## Verification

Run root harness verification; client changes select `python-client` and `python-redteam` because the red team shares this client. Python checks do not authorize real chat, authentication, or attack runs. Only the named operations in the root policy are eligible after separate approval and coordination, subject to all protected-state and current session restrictions.

## References

* [CLI README](README.md): target, identity, stream, and approval contracts.
* [Contributor checks](../CONTRIBUTING.md#run-the-checks): canonical development checks.
