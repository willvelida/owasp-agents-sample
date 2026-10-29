# Starter agent guide

Applies to `starter/`. Read the [root guide](../AGENTS.md) first; this guide adds local context without relaxing its safeguards.

## Changes

* The starter is deliberately insecure. Preserve every `# ASI0x (starter):` weakness and its targeted `noqa`; do not harden it while fixing something else.
* Keep service and file names aligned with `solution/`. Mirror non-security fixes, refactors, and dependency changes, or explain why they cannot be mirrored.
* A changed weakness comment requires the matching [weakness-marker table](README.md#weakness-markers) to change too. Use synthetic fixtures only.
* The application is local-only and must never be deployed to Azure or any shared environment. Its separately hosted model does not make the application safe to deploy. Local stack starts and selected probes or smoke tests are eligible under the [root operational gates](../AGENTS.md#scoped-operational-work); README commands are not authorization.

## Verification

Run root harness verification as described in the [root guide](../AGENTS.md#verify); `python-starter` covers this project. The [contributor checks](../CONTRIBUTING.md#run-the-checks) remain the fallback reference. Routine checks do not start services. Separately authorized local operations must satisfy every root gate; never read environment or secret files, including through helpers. Hand protected-state steps to the operator.

## References

* [Starter README](README.md): services, intended weaknesses, and operator-facing demo steps.
* [Mirrored layouts](../docs/adr/0003-mirrored-starter-and-solution.md) and [local-only starter](../docs/adr/0005-starter-local-only-solution-on-azure.md): the comparison and deployment boundaries.
