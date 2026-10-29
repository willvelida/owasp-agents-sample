---
title: Agent harness
description: How the ./harness CLI discovers sensors and commands, what its statuses and exit codes mean, and how to add a sensor or a command
ms.date: 2026-10-29
ms.topic: how-to
---

## How it works

`./harness` (`.\harness` in cmd) checks for Node.js 24.12 or later, then runs [harness.mjs](harness.mjs), which loads the TypeScript CLI. Node strips the types at load time, so there is no build step and no runtime dependency. The code is erasable TypeScript only: no `enum`, `namespace`, parameter properties, or `import x = require()`.

On every run, the core discovers each `.ts` file directly under `commands/` and `sensors/`. The file name is the command or sensor name, and it must match `^[a-z][a-z0-9-]*$`. Each file has one default export built with `defineCommand` or `defineSensor` from [core/contracts.ts](core/contracts.ts). Validation is strict: an unknown key, a duplicate rule id, a path with `..` or a backslash, or a missing default export stops every command with `error: invalid sensor <file>: <reason>` and exit code 2.

`verify` compares the work tree with the merge-base of the first ref that resolves among `--base`, `upstream/main`, `origin/main`, and `main`. Untracked files are included, and the harness never fetches. A sensor runs when a changed path starts with one of its directory `paths` (ending in `/`) or equals one of its file paths, and matches no `exclude`. With no base, every sensor runs.

Sensors run one after another. Each subprocess runs from an argument array without a shell, with a time limit and process-tree cleanup, and keeps a 256 KiB tail of its output with colours stripped and secret-named environment values redacted. On Windows, `npm` alone goes through `cmd.exe` with constant, metacharacter-free arguments.

On POSIX, timeouts signal the process group with `SIGTERM`, then `SIGKILL` after 2 seconds, even if the leader has exited or its pipes have closed. Interruption also kills tracked groups after leader exit. On Windows, `taskkill /T /F` kills the tree only while its leader still exists; descendants orphaned before cleanup cannot be recovered by this mechanism. A clean leader exit cancels its timeout and kills its POSIX group. If inherited pipes remain open, capture ends after a 5-second drain without marking the successful leader timed out.

## Statuses and exit codes

The runner decides each sensor's status; the sensor only reports what it found.

| Situation | Status | Exit contribution |
|-----------|--------|-------------------|
| The sensor's `paths`, after `exclude`, match no changed file | `skipped` | 0 |
| `run()` returns no findings and no problems, and `checked > 0` | `pass` | 0 |
| `run()` returns one or more findings and no problems | `fail` | 1 |
| `run()` returns a problem, throws, or reports `checked === 0` | `error` | 2 |
| A tool in `requires` is not found | `error`; `run()` is not called | 2 |
| Any `exec` in the sensor timed out or failed to start | `error` | 2 |
| A Python, UI, or harness step terminates without an exit code | `error` | 2 |

The command exits 2 on any error, usage error, discovery error, or interruption, otherwise 1 on any fail, otherwise 0. A finding means the change broke a rule. A problem means there is no trustworthy result, so the harness never reports it as a pass.

The infra guard skips `.env`, `.env.*`, and `*.env` files. Python test steps remove `RUN_INTEGRATION` from the child environment, including differently cased spellings on Windows.

## Add a sensor

Create one file in `sensors/`. This illustrative sensor fails when `CHANGELOG.md` is empty:

```ts
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { defineSensor } from '../core/contracts.ts';

export default defineSensor({
  description: 'CHANGELOG.md is not empty.',
  paths: ['CHANGELOG.md'],
  requires: [],
  rules: [{ id: 'changelog-filled', expectation: 'CHANGELOG.md has content', repair: 'describe the change in CHANGELOG.md' }],
  async run(ctx) {
    const text = await readFile(join(ctx.repoRoot, 'CHANGELOG.md'), 'utf8');
    const findings = text.trim() ? [] : [{ rule: 'changelog-filled', location: 'CHANGELOG.md', message: 'the file is empty' }];
    return { checked: 1, findings, problems: [], notes: [] };
  },
});
```

Run tools with `ctx.exec(['tool', 'arg'], { cwd: 'project', timeoutMs: 60_000 })` rather than `node:child_process`, so the time limit, output cap, redaction, and Ctrl+C cleanup apply. List the tools the sensor needs (`git`, `uv`, or `npm`) in `requires`. Give every rule a `repair` an agent can act on without reading the sensor. `./harness sensors <name>` prints them.

## Add a command

Create one file in `commands/` that exports `defineCommand({ description, usage, run })`. `run(ctx)` writes lines with `ctx.write` and returns 0, 1, or 2. Keep the output contract: the first line is `<command>: <pass|fail|error>`, the last line starts with `next: `, and there are no colours or prompts. Parse flags with `parseFlags` from [commands/verify.ts](commands/verify.ts), which rejects unknown flags.

## Check the harness

The `harness` sensor runs when `.harness/`, `harness`, or `harness.cmd` changes. It runs `tsc --noEmit` and `node --test` and needs the dev tooling installed:

```bash
cd .harness && npm ci --ignore-scripts && cd ..
./harness verify
```

`npm run typecheck` and `npm test` in `.harness/` run the same steps directly. The core in `core/` stays under 500 non-blank lines, not counting the Python sensor factory, and each sensor or command file stays under 150. The only dev dependencies are exact pins of `typescript` and `@types/node`, and `tests/dependencies.test.ts` keeps it that way.

## Not built yet

Each of these would be one more file:

* Sensors for the `# ASI0x` marker tables and for starter and solution mirroring
* A Copilot skill and an `agentStop` hook that runs `./harness verify` before an agent finishes
* Saved results or fingerprints, so an unchanged project isn't checked twice
* Telemetry on check durations and outcomes
* CI calling `./harness verify --all`, which would end the drift between the sensors and `.github/workflows/ci.yml`
