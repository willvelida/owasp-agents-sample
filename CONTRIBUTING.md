---
title: Contributing
description: How to propose, build, and submit a change to the OWASP agents sample, from an issue to a merged pull request
ms.date: 2026-10-29
---

Thanks for helping improve this sample. Biotrackr exists to teach the OWASP Top 10 for Agentic Applications, so every change has to keep the two stacks honest: `starter/` stays plausibly insecure, and `solution/` shows a working, tested control for each risk. This guide explains how to get a change from an idea to a merged pull request.

## Before you start

Every pull request starts from an issue. Open one with an [issue form](https://github.com/willvelida/owasp-agents-sample/issues/new/choose) so the maintainer and other contributors can see what you want to change and why. Then choose how to continue:

* **Discuss first.** For larger changes, or when you aren't sure the idea fits the sample, wait for feedback on the issue before you write code. This saves you from building something that can't be merged.
* **Show a working idea.** If it's easier to explain with code, open a pull request from your fork straight away and link it to the issue. The maintainer may still ask for changes or decide the idea doesn't fit.

A pull request without a linked issue may be closed and pointed back to the issue forms. The one exception is a trivial fix: a typo or a broken link. You can open a pull request for those without an issue.

Two other policies apply:

* Follow the [Code of Conduct](CODE_OF_CONDUCT.md) in issues, pull requests, and reviews.
* Don't report security problems in public. [SECURITY.md](SECURITY.md) explains what to report privately and what is an intentional starter weakness that you can discuss openly.

## Ways to contribute

| You want to                                                     | Use                                                                                                   |
|-----------------------------------------------------------------|-------------------------------------------------------------------------------------------------------|
| Report something broken in a stack, the client, or the red team | Bug report form                                                                                       |
| Suggest a new control, attack, or feature                       | Feature request form                                                                                  |
| Fix or improve a README, an ADR, the runbook, or other docs     | Documentation form                                                                                    |
| Ask how something works or why it was built that way            | Question form                                                                                         |
| Report a vulnerability or an exposed secret                     | [Private vulnerability reporting](https://github.com/willvelida/owasp-agents-sample/security/advisories/new), not an issue |

Choose a form from the [new issue page](https://github.com/willvelida/owasp-agents-sample/issues/new/choose).

## Fork-based workflow

Contributors work from a fork. You don't need write access to this repository.

1. Fork [willvelida/owasp-agents-sample](https://github.com/willvelida/owasp-agents-sample) to your account.
2. Clone your fork and add this repository as `upstream`:

   ```bash
   git clone https://github.com/<you>/owasp-agents-sample.git
   cd owasp-agents-sample
   git remote add upstream https://github.com/willvelida/owasp-agents-sample.git
   ```

3. Create a branch from an up-to-date `main`:

   ```bash
   git fetch upstream
   git switch -c <type>/<short-description> upstream/main
   ```

4. Keep the branch current while you work with `git fetch upstream` and `git rebase upstream/main`.
5. Push the branch to your fork with `git push -u origin <branch>`.
6. Open a pull request from your branch to `willvelida/owasp-agents-sample:main`, and fill in the pull request template.

CI runs on your pull request with a read-only token and no secrets, so it needs no Azure access. If this is your first contribution, the workflow runs may wait until the maintainer approves them.

## Repository rules

These rules keep the starter and solution comparison meaningful. A pull request that breaks one of them will be asked to change.

* **The starter is insecure on purpose.** Don't fix weaknesses in `starter/`. They are the teaching material. Each one carries a `# ASI0x (starter): <why>` comment and is listed in the [starter's weakness markers](starter/README.md#weakness-markers). Never deploy the starter to Azure or any shared environment ([ADR-0005](docs/adr/0005-starter-local-only-solution-on-azure.md)).
* **Mirror non-security changes in both stacks.** `starter/` and `solution/` keep the same services and file names so that `git diff --no-index starter solution` shows only security controls ([ADR-0003](docs/adr/0003-mirrored-starter-and-solution.md)). A bug fix, refactor, or dependency change that isn't a control belongs in both trees. If it can't go in both, say why in the pull request.
* **Mark weaknesses and controls.** A new or changed weakness gets a `# ASI0x (starter):` comment, and a new or changed control gets a `# ASI0x:` comment. Update the matching table in [starter/README.md](starter/README.md#weakness-markers) or [solution/README.md](solution/README.md#control-markers).
* **Record design decisions.** A change to how the sample is built, rather than a fix within the current design, needs an architecture decision record in [docs/adr/](docs/adr/README.md) ([ADR-0001](docs/adr/0001-record-architecture-decisions.md)).
* **Keep secrets out.** Never commit `.env` files, model keys, tenant or subscription IDs, or tokens. `starter/.env` holds a live model key.
* **Use synthetic data only.** All health data in this repository is fictional. Don't add real health data, in code, fixtures, issues, or screenshots.

## Agent guidance

Start with [AGENTS.md](AGENTS.md). Its project map links nested guides for the starter, solution, browser UI, infrastructure, provisioning scripts, CLI client, red team, and verification harness. Read the root guide and each affected area's guide before editing, even if your agent does not discover nested files automatically. For a cross-project change, read every affected guide; sibling-directory guidance does not load through inheritance alone.

Nested guides add project-specific context, not permission to override root safeguards or session and developer restrictions. For example, `solution/azure.yaml` sits outside `solution/infra/`, but its work still needs the infrastructure guide. If instructions conflict, stop and surface the conflict rather than choose the more permissive text. A separate worktree isolates source changes, not credentials, containers, or Azure resources.

Human README deployment, sign-in, stack, and red-team recipes are operator documentation, not agent execution permission. The [root operational policy](AGENTS.md#scoped-operational-work) defines eligibility for local stack/probe work, solution azd/Azure deployment and probes, and solution supply-chain validation without tying permissions to individual issues. Each operation still needs explicit user/operator authorization for its target, effects, and cleanup, shared-environment coordination, and compatible session, developer, and tool permissions. Registry publishing/signing needs its own approval. Editing these instructions is not authorization.

Keep operational work separate from routine harness verification. Never deploy the insecure starter application to Azure or any shared environment; use synthetic data only. Never read or share protected files, credentials, or identifiers, including through helpers. If a command needs protected state or would expose it, hand that step to the operator for sanitized evidence instead. Report pending live evidence without fabricating results. Root `AGENTS.md` requires signed-off commits but does not itself prohibit commits; a session-specific no-commit or no-push instruction still applies.

The starter and solution top-level guides mirror shared maintenance guidance. The UI, infrastructure, and provisioning guides are solution-only because the starter has no corresponding components.

## Run the checks

Run the checks for every project you changed before you open a pull request. CI runs the same commands.

### Run them all with the harness

`./harness verify` runs the checks below for every project your change touches and reports one result. Run it from the repository root. `./harness` works in sh, Git Bash, and PowerShell, and cmd needs `.\harness`.

```bash
./harness verify          # the sensors for the projects you changed
./harness verify --all    # every sensor
./harness doctor          # what's missing when verify reports an error
./harness sensors         # what each sensor checks; add a sensor name to see its rules
```

It exits 0 when every check passes, 1 when a check finds a problem in your change, and 2 when it can't produce a trustworthy result, for example because a tool is missing. The per-project commands below stay the reference that CI mirrors, and the harness doesn't run the build, the e2e tests, or the checks in [What else CI checks](#what-else-ci-checks). The harness checks its own code too: run `npm ci --ignore-scripts` once in `.harness/`, then `./harness verify` from the repository root. [.harness/README.md](.harness/README.md) explains how to add a sensor or a command.

### Prerequisites

* [uv](https://docs.astral.sh/uv/) with Python 3.12.
* Node.js 24.12 or later to run `./harness`.
* Node.js 24.22.0 for `solution/ui/`. CI uses this version, and `npm` refuses any version below 24.22.0 or at 25 and above.
* Podman with a Compose provider, only if you run the stacks. See [docs/podman.md](docs/podman.md).

The [dev container](.devcontainer/devcontainer.json) includes uv and Python 3.12, but not Node.js, so `./harness` can't run there. Use the per-project commands below instead.

### Python projects

In each of `starter/`, `solution/`, `client/`, and `redteam/` that you changed:

```bash
uv lock --check
uv sync --locked
uv run --locked ruff check
uv run --locked ruff format --check
uv run --locked pytest -q   # projects with a tests/ folder
```

### Browser client

In `solution/ui/`:

```bash
npm ci --ignore-scripts
npm run lint
npm run typecheck
npm test
npm run build
npx --no-install playwright install --with-deps chromium   # once per machine
npm run e2e
```

On Linux, `--with-deps` installs system packages and may need elevated rights. You can leave it out if Chromium's dependencies are already installed.

### What else CI checks

CI also runs checks that are slower or harder to run locally. Any of them can fail your pull request:

* An SPDX software bill of materials (SBOM) for each of the four Python projects and the browser UI, scanned with pinned Trivy. An unignored high or critical vulnerability fails the job.
* A build and vulnerability scan of the solution runtime, chart runner and browser UI images. The deliberately insecure starter image, local dev runtime and local-only sidecar image are excluded. Scan jobs have read-only permissions and do not push images.
* A guard that keeps the stage-only identity simulator and DevUI out of `solution/infra/` and `solution/azure.yaml`.
* A check that the end-to-end test sign-in stub is absent from the production build of `solution/ui/`.
* A container build of `solution/ui/` that checks its security headers.
* The offline solution stack with `mcp-scan` and the model-free ASI07 red-team run.

The dependency and image gates use the root [.trivyignore.yaml](.trivyignore.yaml)
explicitly. Scanner installation, database and scan errors fail closed; only the
database download gets one retry. A green scan is not a signature or provenance
check. See [ADR-0028](docs/adr/0028-vulnerability-scan-gates.md) for the trust
boundary and remaining work on signing and deployed-image scanning.

Prefer a dependency or pinned base-image fix to an exception. To propose an ignore
entry, include the individual CVE, exact affected package versions in `purls`, a
`statement` naming the affected component and reason, a concrete review trigger,
and an `expired_at` date. Include baseline scan evidence; do not use blanket
severity or package wildcards. The maintainer owns ignore-list review and triage:
when a new finding turns unrelated PRs red, the maintainer either lands a fix or
reviews a reasoned, time-bounded entry with a review trigger. An expired exception
no longer suppresses its finding. An exception does not mean that a package is safe.

## Update the docs

A change isn't done until the docs describe it. Update each document that applies:

| If your change                                        | Update                                                                                                              |
|-------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------|
| Changes how a component runs or behaves               | That component's README                                                                                             |
| Adds or changes a `# ASI0x` weakness or control       | The marker table in [starter/README.md](starter/README.md#weakness-markers) or [solution/README.md](solution/README.md#control-markers) |
| Adds or changes a service, port, or flow              | [docs/architecture.md](docs/architecture.md) and the component README's service table                               |
| Makes a design decision                               | A new `docs/adr/NNNN-short-title.md` and a row in [docs/adr/README.md](docs/adr/README.md)                          |
| Changes a demo step                                   | [docs/demo-runbook.md](docs/demo-runbook.md)                                                                        |
| Changes the layout, quick start, or checkpoints       | [README.md](README.md)                                                                                              |
| Changes red-team results                              | Say so in the pull request. Saved scorecards in [docs/scorecards/](docs/scorecards/) record specific runs           |

When you edit a document with frontmatter, set its `ms.date` to the date of your change.

## Pull request process

1. Link the issue with `Closes #<number>` in the pull request description, or tick the trivial-fix box for a typo or broken link.
2. Work on a branch in your fork, as described in [Fork-based workflow](#fork-based-workflow).
3. Follow the [repository rules](#repository-rules).
4. [Run the checks](#run-the-checks) for every project you touched.
5. [Update the docs](#update-the-docs) that your change affects.
6. Fill in the pull request template, including its checklists.
7. Make sure every commit is [signed off](#sign-off-your-commits).
8. The maintainer reviews the pull request and squash-merges it when it's ready.

## Commit and pull request titles

This repository uses [Conventional Commits](https://www.conventionalcommits.org/). Pull requests are squash-merged, so the pull request title becomes the commit message on `main`. Write it as `<type>(<optional scope>): <description>`, for example `fix(solution): time out the report agent call` or `docs: clarify the offline quick start`.

Common types are `feat`, `fix`, `docs`, `refactor`, `test`, `build`, `ci`, and `chore`. Commits on your branch don't need to follow the format.

### Sign off your commits

Every commit must be signed off under the [Developer Certificate of Origin](https://developercertificate.org/) (DCO). Signing off certifies that you wrote the change or have the right to submit it under this repository's license. A DCO check runs on every pull request and fails if any commit is missing a sign-off.

Add the sign-off with `-s` when you commit:

```bash
git commit -s -m "fix(solution): time out the report agent call"
```

This adds a `Signed-off-by: Your Name <your.email@example.com>` line that must match your Git `user.name` and `user.email`. To sign off commits you've already made on your branch, run `git rebase --signoff upstream/main` and then `git push --force-with-lease`.

## Getting help

* Ask questions with the question form on the [new issue page](https://github.com/willvelida/owasp-agents-sample/issues/new/choose).
* Report security problems as [SECURITY.md](SECURITY.md) describes.
* Report conduct problems as the [Code of Conduct](CODE_OF_CONDUCT.md) describes.
