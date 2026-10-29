# Verification harness agent guide

Applies to `.harness/`. Also read this guide for the root `harness` and `harness.cmd` launchers, as routed by the [root guide](../AGENTS.md). Its safeguards remain in force.

## Changes

* Use erasable TypeScript supported by Node's type stripping: no build step or runtime dependencies. Keep the exact-pinned development-tooling contract.
* Add sensors and commands through the existing `defineSensor` and `defineCommand` contracts. Use bounded `ctx.exec` argument arrays rather than a shell or direct subprocess calls.
* Preserve process-tree cleanup, output limits, and secret redaction. Sensor paths and exclusions must not cause protected state to be read.
* Preserve the documented file-size limits and one-file extension pattern in the [harness README](README.md).
* Keep pass, fail, error, and skipped distinct. Missing tools, failed startup, timeouts, or zero checked items are not a pass. Every command ends with `next:`.
* CI remains the source of truth for sensor behavior. Do not add stacks, red-team execution, or Azure operations to local verification.
* The [root operational gates](../AGENTS.md#scoped-operational-work) are separate from this harness. Named issue work may be eligible after explicit approval and coordination, but a harness pass never authorizes it or waives protected-state or session restrictions.

## Verification

Run root harness verification; the `harness` sensor type-checks and tests the harness when this directory or a launcher changes. Follow the [root installation restrictions](../AGENTS.md#dont-run) if doctor requests missing development tooling.

## References

* [Harness README](README.md): extension contracts, exit codes, cleanup limits, and size bounds.
* [Contributor checks](../CONTRIBUTING.md#run-the-checks) and [CI](../.github/workflows/ci.yml): canonical checks and the CI-only validation boundary.
