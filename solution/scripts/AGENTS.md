# Solution scripts agent guide

Applies to `solution/scripts/`, in addition to the [solution guide](../AGENTS.md) and [root safeguards](../../AGENTS.md).

## Changes

* Provisioning, hooks, and seeding can change Entra objects, credentials, Azure configuration, images, and data. A preview may invoke hooks too. Required #30/#35 operational steps are eligible only under the [root operational gates](../../AGENTS.md#scoped-operational-work), with explicit approval covering their side effects and shared-environment coordination; they are not routine source checks.
* Preserve idempotency and the documented object-matching boundaries. Do not broaden identity lookup to display-name-only matches.
* Keep application IDs and service-principal object IDs distinct in code. Use synthetic placeholders in tests and examples; do not retrieve actual IDs, signing keys, passwords, or cached credentials.
* Preserve the documented ownership and lifecycle of federated credentials, redirect URIs, and seed data. Read the [infrastructure guide](../infra/AGENTS.md) when changing their deployment contract.
* Do not read protected state or invoke a helper that loads it as a shortcut to discovering configuration. Human run recipes do not override the root restrictions.

## Verification

Run root harness verification; changes here select `python-solution`. Use isolated, synthetic checks for routine verification. Keep separately authorized operations outside these checks. If a script needs protected files or would expose credentials or identifiers, do not invoke it: hand that step to the operator for sanitized evidence. Operational approval does not waive protected-state or current session restrictions.

## References

* [Scripts README](README.md): typed IDs, matching rules, hook side effects, and operator prerequisites.
* [Contributor checks](../../CONTRIBUTING.md#run-the-checks): canonical development checks.
