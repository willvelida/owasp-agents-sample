# Copilot instructions

Follow [AGENTS.md](../AGENTS.md) at the repository root. It holds the project map, the verify steps, and the definition of done.

## Must never

* Never fix, harden, or tidy a `# ASI0x (starter):` weakness in `starter/`, and never remove its targeted `noqa`. The starter is insecure on purpose.
* In reviews, don't report code under `starter/` marked `# ASI0x (starter):` as a bug. Report a `# ASI0x (starter):` marker anywhere else as a problem.
* Mirror every non-security change in both `starter/` and `solution/`, or say in the pull request why it can't be mirrored.
* Never read, print, or commit `.env` files, `.secrets/`, `.azure/`, keys, tokens, or tenant or subscription IDs.
* Use synthetic data only.
* Never deploy the starter. Don't start the stacks, run the red team, or run `azd` to verify a change.

## Before you finish

Run `./harness verify` from the repository root (`.\harness verify` in cmd) and fix every finding until it exits 0.
