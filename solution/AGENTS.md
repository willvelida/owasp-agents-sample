# Solution agent guide

Applies to `solution/`. Read the [root guide](../AGENTS.md) first; this guide adds local context without relaxing its safeguards.

## Changes

* Keep controls fail-closed on denial, errors, and timeouts. Preserve caller-scoped identity, data access, conversation state, and decision-only report approvals.
* Keep service and file names aligned with `starter/`. Mirror non-security fixes, refactors, and dependency changes, or explain why they cannot be mirrored. Security controls intentionally differ; never harden the starter to match.
* A changed control comment requires the matching [control-marker table](README.md#control-markers) to change too. Use synthetic fixtures only.
* Reviewed prompt or tool-descriptor changes must keep their pins consistent with the [governance contract](README.md#tool-governance-asi01-asi02-asi04). Do not bypass a pin mismatch to make a check pass.
* Local offline mode replaces sign-in, not the cloud model. The [root operational policy](../AGENTS.md#scoped-operational-work) makes local stack/probe work for #25 and the named solution azd/Azure/probe work for #30/#35 eligible only after separate authorization and coordination. Neither offline mode nor README commands supply that authorization.

## Specialized guidance

* Read the [UI guide](ui/AGENTS.md) for browser work and the [scripts guide](scripts/AGENTS.md) for provisioning, hooks, and seed code.
* Read the [infrastructure guide](infra/AGENTS.md) for both `infra/` and `azure.yaml`; the manifest is outside that guide's directory.
* Transport or approval changes also need the [CLI guide](../client/AGENTS.md) when they affect the shared request contract.
* UI, infrastructure, and provisioning guidance is solution-specific because those areas have no corresponding starter components.

## Verification

Run root harness verification as described in the [root guide](../AGENTS.md#verify); `python-solution` covers this project, with separate UI and infrastructure sensors. The [contributor checks](../CONTRIBUTING.md#run-the-checks) remain the fallback reference. Routine checks do not start services or access Azure. Keep separately authorized operational evidence distinct from these checks; never read environment or secret files, including through helpers. Hand protected-state steps to the operator.

## References

* [Solution README](README.md): control contracts, policy pins, identity modes, and tests.
* [Mirrored layouts](../docs/adr/0003-mirrored-starter-and-solution.md) and [fail-closed controls](../docs/adr/0019-fail-closed-control-contract.md): the comparison and failure behavior.
