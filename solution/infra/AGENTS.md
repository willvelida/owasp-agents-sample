# Infrastructure agent guide

Applies to `solution/infra/`. Also read this guide for `solution/azure.yaml`, as routed by the [solution guide](../AGENTS.md). The [root safeguards](../../AGENTS.md) remain in force.

## Changes

* Preserve the documented managed-identity, federated-credential, and service-access boundaries. Review role assignments and their scopes in source; a static check does not prove a deployed role changed.
* Keep the stage-only identity simulator and developer UI out of Azure infrastructure and the deployment manifest.
* Keep images pinned and configuration consistent with the solution's identity mode. Use placeholders in documentation and synthetic fixtures, never actual environment values.
* Review related [provisioning scripts](../scripts/AGENTS.md) when a resource change affects hooks, seeding, or identity configuration.
* Source editing is not deployment authorization. Solution azd, required hooks, resource or role changes, and deployed probes are eligible only under the [root operational gates](../../AGENTS.md#scoped-operational-work). Obtain explicit user/operator approval and shared-environment coordination first; a preview that invokes hooks is an operation too. No permission extends to deploying the starter application.

## Verification

Run root harness verification; `infra-guard` covers this directory and the deployment manifest. The guard scans Markdown too: describe excluded stage-only components without copying the identifiers its patterns reject. Do not weaken the guard or exempt documentation.

The [CI workflow](../../.github/workflows/ci.yml) and [infra sensor](../../.harness/sensors/infra-guard.ts) are the check definitions. Keep separately authorized live evidence distinct from source verification. Never read or share protected files or identifiers, including through helpers; hand protected-state steps to the operator for sanitized evidence. Current session, developer, and tool restrictions still apply.

## References

* [Solution README](../README.md): current identity, deployment, and supply-chain contracts.
* [Scripts README](../scripts/README.md): hook side effects and operator prerequisites, not execution permission.
