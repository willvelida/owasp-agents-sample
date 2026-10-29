# Agent guide

Biotrackr is a fictional health-tracking agent shipped twice to teach the OWASP Top 10 for Agentic Applications: `starter/` is insecure on purpose, and `solution/` shows a tested control for each risk. This guide gives coding agents the rules unique to this repository and the one command that proves a change is done.

## Project map

| Path | What it is | Checked by |
|------|------------|------------|
| `starter/` | Deliberately insecure chat agent, health MCP server, report agent, and seed loader | `python-starter` |
| `solution/` | Hardened mirror of the starter, plus Agent ID scripts, azd infrastructure, and tests | `python-solution` |
| `solution/ui/` | Text-only Vue browser client for the solution | `ui` |
| `solution/infra/`, `solution/azure.yaml` | Azure infrastructure deployed by azd | `infra-guard`, `python-solution` |
| `client/` | `biotrackr-chat` CLI client for every target | `python-client`, `python-redteam` |
| `redteam/` | Shared PyRIT red-team harness | `python-redteam` |
| `ruff.toml` | Lint settings shared by every Python project | all four Python sensors |
| `harness`, `harness.cmd`, `.harness/` | The `./harness` CLI, its sensors, and its tests | `harness` |
| `data/seed/`, `docs/` | Synthetic seed data, architecture, ADRs, runbook, scorecards | none |

## Must never

* Never fix, harden, or tidy a `# ASI0x (starter):` weakness in `starter/`, and never remove its targeted `noqa`. The starter is insecure on purpose.
* In reviews, don't report code under `starter/` marked `# ASI0x (starter):` as a bug. Report a `# ASI0x (starter):` marker anywhere else as a problem.
* Mirror every non-security change in both `starter/` and `solution/`, or say in the pull request why it can't be mirrored.
* Never read, print, or commit `.env` files, `.secrets/`, `.azure/`, keys, tokens, or tenant or subscription IDs.
* Use synthetic data only.
* Never deploy the starter. Don't start the stacks, run the red team, or run `azd` to verify a change.

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

* `podman compose up`, or anything else that starts the starter or solution stacks.
* The red team (`uv run python -m redteam.run`) or `mcp-scan`.
* `azd up`, `azd provision`, `azd deploy`, or any other command that changes Azure.
* `npm install`. Run `npm ci --ignore-scripts` only when `./harness doctor` asks for it.

## Where to look next

* [CONTRIBUTING.md](CONTRIBUTING.md): the fork workflow, repository rules, per-project checks, the docs table, and commit rules.
* Component guides: [starter](starter/README.md), [solution](solution/README.md), [browser client](solution/ui/README.md), [CLI client](client/README.md), and [red team](redteam/README.md).
* [docs/architecture.md](docs/architecture.md): services, ports, and flows.
* [docs/adr/README.md](docs/adr/README.md): why the sample is built the way it is.
* [.harness/README.md](.harness/README.md): how the harness works and how to add a sensor or a command.
