<!--
Thanks for contributing. Read CONTRIBUTING.md first:
https://github.com/willvelida/owasp-agents-sample/blob/main/CONTRIBUTING.md

The PR title becomes the commit message on main (squash merge), so write it as a
Conventional Commit, for example: fix(solution): time out the report agent call
-->

## Linked issue

<!-- Replace <number> with the issue this pull request addresses, or tick the trivial-fix box. -->

Closes #<number>

- [ ] This pull request links an issue opened with an issue form.
- [ ] Or: this is a trivial fix (typo or broken link), so no issue is needed.

## Summary

<!-- What changed and why. Mention anything a reviewer should look at closely. -->

## Type of change

- [ ] `feat`: new control, attack, or feature
- [ ] `fix`: bug fix
- [ ] `docs`: documentation only
- [ ] `refactor`, `test`, `build`, `ci`, or `chore`

## Projects touched

- [ ] `starter/`
- [ ] `solution/`
- [ ] `solution/ui/`
- [ ] `client/`
- [ ] `redteam/`
- [ ] `docs/` or other Markdown
- [ ] CI or `.github/`

## Checks run

<!--
Tick the checks you ran for each project you touched:
https://github.com/willvelida/owasp-agents-sample/blob/main/CONTRIBUTING.md#run-the-checks
-->

- [ ] Python: `uv lock --check`, `uv sync --locked`, `ruff check`, `ruff format --check`, and `pytest` where tests exist.
- [ ] Browser client: `npm ci --ignore-scripts`, `lint`, `typecheck`, `test`, `build`, and `e2e`.
- [ ] Not applicable (docs only).

## Docs updated

<!--
Tick each one that applies, or explain below why none do:
https://github.com/willvelida/owasp-agents-sample/blob/main/CONTRIBUTING.md#update-the-docs
-->

- [ ] Component README for each changed component.
- [ ] Marker table in `starter/README.md` or `solution/README.md` for added or changed `# ASI0x` comments.
- [ ] `docs/architecture.md` for service, port, or flow changes.
- [ ] New ADR in `docs/adr/` and a row in `docs/adr/README.md` for a design decision.
- [ ] `docs/demo-runbook.md` for demo step changes.
- [ ] `README.md` for layout, quick start, or checkpoint changes.
- [ ] `ms.date` set on every edited doc that has frontmatter.
- [ ] Red-team result changes described in the summary above.
- [ ] No docs needed, because:

## Repository rules

<!-- https://github.com/willvelida/owasp-agents-sample/blob/main/CONTRIBUTING.md#repository-rules -->

- [ ] This pull request comes from a branch in my fork.
- [ ] Non-security changes are mirrored in both `starter/` and `solution/`, or I explained above why not.
- [ ] I didn't fix an intentional starter weakness.
- [ ] No secrets, `.env` files, tenant or subscription IDs, or real health data are included.
- [ ] The pull request title is a Conventional Commit.
- [ ] Every commit is signed off (`git commit -s`) for the DCO check.
