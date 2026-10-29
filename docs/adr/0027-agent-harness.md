---
title: "ADR-0027: Verify changes with an extensible TypeScript harness"
description: Give agents and contributors AGENTS.md, a thin copilot-instructions.md, and a zero-dependency ./harness CLI whose one-file sensors mirror CI
ms.date: 2026-10-29
ms.topic: reference
---

## Status

Accepted on 2026-10-29.

## Context

Coding agents now work in this repository, and its traps are unusual: `starter/` is insecure on purpose, non-security changes must be mirrored in both stacks, and secrets must never be read. Before this decision, an agent had no entry point and had to find and run five projects' checks by hand from [CONTRIBUTING.md](../../CONTRIBUTING.md). CI was the only place every check ran together.

## Decision

* Agents start at a root `AGENTS.md` with a project map, the must-never rules, the verify steps, and the definition of done. A thin `.github/copilot-instructions.md` repeats the must-never rules word for word for Copilot surfaces that read only that file.
* One command, `./harness` (`.\harness` in cmd), reports whether a change is done. It is TypeScript that Node 24.12 or later runs directly through type stripping: erasable syntax only, no build step, and no runtime dependencies. `typescript` and `@types/node` are exact-pinned dev dependencies, used only for `tsc --noEmit`.
* A small core discovers one-file sensors and commands, runs each check as a bounded subprocess, assigns pass, fail, error, or skipped, and exits 0, 1, or 2 with short `key: value` output. The first commands are `home`, `verify`, `sensors`, and `doctor`. The first sensors mirror CI's Python job for each project, the UI's lint, typecheck, and tests, and the infra-guard checks, plus a `harness` sensor that checks the harness itself.
* `./harness verify` runs only the sensors whose paths the change touches, against the merge-base with `upstream/main`, `origin/main`, or `main`. `--all` runs every sensor.
* CI stays unchanged, and `.github/workflows/ci.yml` remains the source of truth.

## Consequences

### Positive

* Every Copilot surface gets the starter and secrets rules, and agents get one definitive pass, fail, or error with a repair for each finding.
* A new check, such as a marker or mirror sensor, a Copilot skill, or a completion hook, is one new file.
* The harness has no runtime dependencies, an exact-pinned lockfile, and Dependabot coverage, which fits the repository's ASI04 posture.

### Negative

* Node.js 24.12 or later becomes a prerequisite for harness checks, including Python-only work. The dev container has no Node, so the per-project commands remain the fallback there.
* The CI-mirroring sensors can drift from `ci.yml` until CI calls the harness. Only `./harness verify` runs the `harness` sensor, so CI doesn't check the harness's own code.
* The harness doesn't run the UI build, e2e, header, SBOM, or offline-stack checks; CI does.

## Alternatives considered

| Alternative | Reason not chosen |
|-------------|-------------------|
| A stdlib Python harness run through uv | Viable and recommended by the research for toolchain fit: no new toolchain, four of five projects already use uv, and it starts as fast as Node. The maintainer chose TypeScript because it stays closest to the reference harness's design and Node 24.22 is already pinned for `solution/ui` |
| A Rust binary | Starts about six times faster, but harness start-up is about 0.1% of a full verify. It would add a toolchain to CI, the dev container, and contributor setup, need a recompile for each sensor, and can't load plugins at runtime |
| The reference harness as-is, with tsx, zod, commander, and TOON | Four or more runtime dependencies and a larger supply-chain surface, which Node 24 type stripping and hand-written validation make unnecessary |
| A single `scripts/check.py` | Not extensible by adding a file; it would grow into one script that every new check edits |

## References

* [CONTRIBUTING.md](../../CONTRIBUTING.md#run-the-checks)
* [.harness/README.md](../../.harness/README.md)
* [ADR-0011](0011-uv-python-312-dev-container.md)
