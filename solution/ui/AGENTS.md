# Browser client agent guide

Applies to `solution/ui/`, in addition to the [solution guide](../AGENTS.md) and [root safeguards](../../AGENTS.md).

## Changes

* Render data as text through Vue interpolation, never HTML or executable markup. Preserve the existing XSS lint rules and browser security headers.
* Tokens must not enter reactive state, URLs, logs, or the DOM. Keep the existing MSAL `sessionStorage` contract; do not introduce `localStorage`.
* Approval dialogs show the full tool arguments and send only the accepted/rejected decision. Keep AG-UI transport and approval behavior aligned with the [CLI client](../../client/AGENTS.md).
* Preserve the four-key runtime configuration contract and per-account thread isolation. Use synthetic configuration and stubbed responses in tests; do not load real environment values or sign in.
* Keep the e2e authentication stub out of production builds. Stubbed browser tests are not evidence of real Entra or model connectivity.
* The [root operational policy](../../AGENTS.md#scoped-operational-work) makes stack/probe and solution deployment work eligible after separate approval and coordination; it does not authorize unrelated browser sign-in or live testing. Protected-state and current session restrictions still apply.

## Verification

Run root harness verification; the `ui` sensor runs lint, type checks, and unit/component tests. The [UI test guide](README.md#test) distinguishes these from production-build, e2e, and container-header checks in CI.

Use the Node 24.x range and npm settings in [the prerequisites](README.md#prerequisites): at least 24.22.0, exact dependency pins, and the release-age guard. Follow the [root installation restrictions](../../AGENTS.md#dont-run); only apply the prescribed dependency repair when harness doctor requests it.

## References

* [UI README](README.md): transport, configuration, sign-in, rendering, and header contracts.
* [Contributor checks](../../CONTRIBUTING.md#browser-client): canonical check commands, not authorization to start the application stack.
