# Red-team development agent guide

Applies to `redteam/`. Read the [root guide](../AGENTS.md) first; developing probes does not authorize running them.

## Changes

* Keep one shared catalogue for starter and solution targets, with ASI10 last because its fault steps clear state. Preserve existing attacks when extending the target or converter contracts.
* Use synthetic canaries and explicit success evidence. Preserve positive controls and oracles; missing prerequisites must not become fabricated success or block evidence.
* Keep score meanings honest: `SUCCEEDED` and `BLOCKED` describe evidence from an actual run, `SKIPPED` is excluded from counts, and `INVALID` counts as a failure. The [README's scoring limits](README.md#what-the-results-mean) still apply; a failed request is not proof of a security control.
* Target authentication and transport come from the [shared client](../client/AGENTS.md). Use synthetic fixtures for source checks, not real configuration or credentials.
* Attack runs can delete seed data, stop services, flip kill switches, recreate containers, and spend model budget. Only the required #25 local probes and #30 solution-Azure probes listed in the [root operational policy](../AGENTS.md#scoped-operational-work) are eligible after explicit approval and shared-environment coordination. Model-free does not mean authorization-free. Fault helpers require approval for their exact effects; do not run the whole catalogue when only selected probes were approved.
* Never read protected files or identifiers, including through target/authentication helpers. Hand those steps to the operator for sanitized evidence; approval does not waive protected-state or session restrictions.
* Saved scorecards record real runs. Record genuine, sanitized results only; leave blocked baseline or rerun evidence pending for the operator rather than invent results.

## Verification

Run root harness verification; `python-redteam` checks this project's lock, lint, formatting, and any tests. It is not the PyRIT attack runner. Keep separately authorized operational runs and evidence distinct from these routine checks.

## References

* [Red-team README](README.md): attack catalogue, side effects, scoring, and operator-facing run instructions.
* [Contributor checks](../CONTRIBUTING.md#run-the-checks): canonical development checks.
