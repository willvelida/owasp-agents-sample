# Agent guide

Biotrackr is a fictional health-tracking agent shipped twice to teach the OWASP Top 10 for Agentic Applications: `starter/` is insecure on purpose, and `solution/` shows a tested control for each risk. This guide gives coding agents the rules unique to this repository and the one command that proves a change is done.

## Scope and inheritance

This file applies throughout the repository. Before editing, read the nested `AGENTS.md` guides for every area your change affects, including related areas outside your working directory. Nested guides add project-specific detail; they do not relax these safeguards or session and developer restrictions. If instructions conflict, stop and surface the conflict rather than follow the more permissive rule.

The project map links the guides for explicit reading when your agent does not discover nested files automatically. Human README commands describe how operators run the sample; they are not permission to execute prohibited operations. A separate worktree does not isolate Azure resources, credentials, or the container engine.

## Project map

| Path | What it is | Agent guide | Checked by |
|------|------------|-------------|------------|
| `starter/` | Deliberately insecure chat agent, health MCP server, report agent, and seed loader | [starter](starter/AGENTS.md) | `python-starter` |
| `solution/` | Hardened mirror of the starter, plus Agent ID scripts, azd infrastructure, and tests | [solution](solution/AGENTS.md) | `python-solution` |
| `solution/ui/` | Text-only Vue browser client for the solution | [browser client](solution/ui/AGENTS.md) | `ui` |
| `solution/infra/`, `solution/azure.yaml` | Azure infrastructure deployed by azd | [infrastructure](solution/infra/AGENTS.md) | `infra-guard`, `python-solution` |
| `solution/scripts/` | Agent ID provisioning, hooks, and seed scripts | [scripts](solution/scripts/AGENTS.md) | `python-solution` |
| `client/` | `biotrackr-chat` CLI client for every target | [CLI client](client/AGENTS.md) | `python-client`, `python-redteam` |
| `redteam/` | Shared PyRIT red-team harness | [red team](redteam/AGENTS.md) | `python-redteam` |
| `ruff.toml` | Lint settings shared by every Python project | this guide | all four Python sensors |
| `harness`, `harness.cmd`, `.harness/` | The `./harness` CLI, its sensors, and its tests | [verification harness](.harness/AGENTS.md) | `harness` |
| `data/seed/`, `docs/` | Synthetic seed data, architecture, ADRs, runbook, scorecards | this guide | none |

## Must never

* Never fix, harden, or tidy a `# ASI0x (starter):` weakness in `starter/`, and never remove its targeted `noqa`. The starter is insecure on purpose.
* In reviews, don't report code under `starter/` marked `# ASI0x (starter):` as a bug. Report a `# ASI0x (starter):` marker anywhere else as a problem.
* Mirror every non-security change in both `starter/` and `solution/`, or say in the pull request why it can't be mirrored.
* Never read, print, or commit `.env` files, `.secrets/`, `.azure/`, keys, tokens, or tenant or subscription IDs.
* Use synthetic data only.
* Never deploy the insecure starter application to Azure or any shared environment. Operational work is limited to the named issues and authorization gates below; routine verification does not authorize it.

## Scoped operational work

These are repository-level eligibility rules, not authorization to act. This documentation change, an issue assignment, a nested guide, or a worktree does not approve an operation or override session, developer, or tool restrictions.

| Planned work | Eligible operations after separate authorization |
|---|---|
| [#25](https://github.com/willvelida/owasp-agents-sample/issues/25): probe baselines | Start the starter or solution stack on the local machine only, run the required forged-history and Unicode-smuggling probes, and perform the necessary synthetic-data reset and cleanup. The starter remains local-only. |
| [#30](https://github.com/willvelida/owasp-agents-sample/issues/30): solution identities and Cosmos scopes | Run solution azd provisioning/deployment and its required hooks, explicitly remove the obsolete role assignment, inspect deployed role scopes, and run the required solution-Azure probes and chat smoke test. |
| [#35](https://github.com/willvelida/owasp-agents-sample/issues/35): supply-chain evidence | Run the planned scans, solution azd/ACR build or deployment and opt-in deployed-digest probes. Registry publishing, signing, and provenance require separate authorization for the selected registry and CI job; deployment does not authorize them. |

Before any eligible operation:

1. Obtain explicit user/operator authorization naming the issue, target environment, exact operations, and expected effects. Confirm cost, destructive data or role changes, hooks, fault steps, and reset/cleanup boundaries; approval for one action is not approval for others.
2. Coordinate with owners of shared container engines, ports, Azure environments, registries, and concurrent sessions before changing them. Agree on timing, resource ownership, recovery, and who performs cleanup. A worktree does not provide operational isolation.
3. Keep synthetic data only and all protected-data rules above. Do not read, print, share, or commit secret files, credentials, or protected identifiers, and do not invoke helpers that read protected files on the agent's behalf. An operational approval cannot waive this boundary. If a command requires protected state or would expose it in output, stop and hand that step to the operator; obtain only sanitized results.
4. Confirm the current session, developer, and tool rules permit the action. If any gate is missing or conflicting, do not execute; report the blocked step and request operator handoff. Save only genuine, sanitized evidence, never fabricated baselines or success claims.

All other operational work remains outside this scoped permission. Keep these operations separate from the routine harness checks below.

## Verify

Run the harness from the repository root. Use `./harness verify` in sh, bash, Git Bash, and PowerShell, and `.\harness verify` in cmd.

* `./harness verify` runs only the sensors whose paths your change touches. It compares against the merge-base with `upstream/main`, `origin/main`, or `main`, and it includes staged, unstaged, deleted, and untracked files.
* `./harness verify --all` runs every sensor. `--base <ref>` picks another base, and `--full` prints the whole captured tool output.
* `./harness doctor` explains why `verify` reports an error: a missing tool, Node outside the supported range, or missing `node_modules`.
* `./harness sensors <name>` lists a sensor's rules with the repair for each.
* `./harness` on its own shows the base, the changed files, and which sensors apply.

Exit code 0 means pass. Exit code 1 means fail: fix each finding using its `repair`. Exit code 2 means error: no trustworthy result exists, so fix the problem it names and run `verify` again. The last line of every command starts with `next:`.

The harness needs Node.js 24.12 or later. If `./harness` reports Node missing or too old, as in the dev container, run the per-project commands in [CONTRIBUTING.md](CONTRIBUTING.md#run-the-checks) for each project you changed, and state in your result that `./harness verify` couldn't run and why. That isn't a pass of `verify`.

CI ([.github/workflows/ci.yml](.github/workflows/ci.yml)) is the source of truth. It also runs the SBOMs, the UI production build and its e2e stub check, Playwright, the security-header check, and the offline stack with `mcp-scan` and the model-free red-team run. The harness runs none of those.

## Definition of done

* `./harness verify` exits 0.
* The docs are updated as the table in [CONTRIBUTING.md](CONTRIBUTING.md#update-the-docs) requires.
* Non-security changes are mirrored in `starter/` and `solution/`.
* A changed `# ASI0x` comment updates its marker table in [starter/README.md](starter/README.md#weakness-markers) or [solution/README.md](solution/README.md#control-markers).
* Every edited doc whose frontmatter has `ms.date` carries the date of the change.
* The pull request title is a Conventional Commit, such as `fix(solution): time out the report agent call`.
* Every commit is signed off with `git commit -s`.

## Don't run

* Stack starts, the red team, azd, or Azure-changing commands as routine verification. Only the exact operations listed under [scoped operational work](#scoped-operational-work) are eligible after all its gates pass.
* `mcp-scan`; it is not included in the scoped operational permission.
* `npm install`. Run `npm ci --ignore-scripts` only when `./harness doctor` asks for it.

## Where to look next

* [CONTRIBUTING.md](CONTRIBUTING.md): the fork workflow, repository rules, per-project checks, the docs table, and commit rules.
* Component guides: [starter](starter/README.md), [solution](solution/README.md), [browser client](solution/ui/README.md), [CLI client](client/README.md), and [red team](redteam/README.md).
* [docs/architecture.md](docs/architecture.md): services, ports, and flows.
* [docs/adr/README.md](docs/adr/README.md): why the sample is built the way it is.
* [.harness/README.md](.harness/README.md): how the harness works and how to add a sensor or a command.
