// Shared factory for the four Python project sensors. It mirrors the python job in .github/workflows/ci.yml.
import { readdir } from 'node:fs/promises';
import { join } from 'node:path';
import { defineSensor } from './contracts.ts';
import type { ExecResult, Finding, Problem, SensorContext, SensorDefinition } from './contracts.ts';

export interface PythonProject {
  readonly project: string;
  readonly paths: readonly string[];
  readonly exclude?: readonly string[];
}

const MAX_FINDINGS = 20;

export async function hasTests(repoRoot: string, project: string): Promise<boolean> {
  const entries = await readdir(join(repoRoot, project, 'tests'), { recursive: true }).catch(() => [] as string[]);
  return entries.some((entry) => entry.endsWith('.py'));
}

// One finding per tool line that names a file; falls back to a single finding carrying the whole output.
function findingsFrom(rule: string, project: string, result: ExecResult, pattern: RegExp, fallback: string): Finding[] {
  const findings: Finding[] = [];
  for (const line of result.output.split(/\r?\n/)) {
    const match = pattern.exec(line.trim());
    if (match === null) continue;
    const location = `${project}/${(match[1] ?? '').replaceAll('\\', '/')}${match[2] ? `:${match[2]}` : ''}`;
    findings.push({ rule, location, message: match[3] || fallback });
  }
  if (findings.length === 0) return [{ rule, message: fallback, detail: result.output }];
  if (findings.length <= MAX_FINDINGS) return findings;
  const more = { rule, message: `${findings.length - MAX_FINDINGS} more; run the step by hand to see them all` };
  return [...findings.slice(0, MAX_FINDINGS), more];
}

export function pythonSensor({ project, paths, exclude }: PythonProject): SensorDefinition {
  const where = `in ${project}/,`;
  const rules = [
    { id: 'lock-current', expectation: 'uv.lock matches pyproject.toml (`uv lock --check`)', repair: `${where} run \`uv lock\` and commit uv.lock` },
    { id: 'env-synced', expectation: 'the environment installs exactly what uv.lock pins (`uv sync --locked`)', repair: `${where} run \`uv sync --locked\` and read its error` },
    { id: 'ruff-clean', expectation: '`uv run --locked ruff check` reports no violations', repair: `${where} run \`uv run --locked ruff check --fix\`, then fix what remains` },
    { id: 'ruff-formatted', expectation: '`uv run --locked ruff format --check` reports no changes', repair: `${where} run \`uv run --locked ruff format\`` },
    { id: 'tests-pass', expectation: '`uv run --locked pytest -q` passes when tests/ exists', repair: `${where} run \`uv run --locked pytest -q\` and fix the failing tests` },
  ];
  const repair = (id: string): string => rules.find((rule) => rule.id === id)?.repair ?? '';

  return defineSensor({
    description: `CI python job for ${project}/: lock, sync, ruff check, ruff format, and pytest when tests/ exists.`,
    paths,
    ...(exclude ? { exclude } : {}),
    requires: ['uv'],
    rules,
    async run(ctx: SensorContext) {
      const findings: Finding[] = [];
      const problems: Problem[] = [];
      const notes: string[] = [];
      let checked = 0;
      const step = async (argv: [string, ...string[]], timeoutMs: number, env?: Record<string, undefined>): Promise<ExecResult> => {
        checked++;
        return ctx.exec(argv, { cwd: project, timeoutMs, ...(env ? { env } : {}) });
      };
      const unexpected = (id: string, result: ExecResult, command: string): void => {
        if (result.timedOut || result.spawnError !== null) return; // the runner already records these as problems
        problems.push({ message: `\`${command}\` in ${project}/ exited with ${result.exitCode}`, repair: repair(id), detail: result.output });
      };
      const done = () => ({ checked, findings, problems, notes });

      const lock = await step(['uv', 'lock', '--check'], 120_000);
      if (lock.exitCode !== 0) {
        if (!lock.timedOut && lock.spawnError === null) findings.push({ rule: 'lock-current', location: `${project}/uv.lock`, message: 'uv.lock is out of date with pyproject.toml', detail: lock.output });
        return done();
      }
      const sync = await step(['uv', 'sync', '--locked'], 600_000);
      if (sync.exitCode !== 0) {
        unexpected('env-synced', sync, 'uv sync --locked');
        return done();
      }

      const ruff = await step(['uv', 'run', '--locked', 'ruff', 'check', '--output-format', 'concise'], 180_000);
      if (ruff.exitCode === 1) findings.push(...findingsFrom('ruff-clean', project, ruff, /^(.+?):(\d+):\d+: (.+)$/, 'ruff check reported violations'));
      else if (ruff.exitCode !== 0) unexpected('ruff-clean', ruff, 'uv run --locked ruff check');

      const format = await step(['uv', 'run', '--locked', 'ruff', 'format', '--check'], 180_000);
      if (format.exitCode === 1) findings.push(...findingsFrom('ruff-formatted', project, format, /^Would reformat: (.+?)()()$/, 'ruff format would reformat files'));
      else if (format.exitCode !== 0) unexpected('ruff-formatted', format, 'uv run --locked ruff format --check');

      if (!(await hasTests(ctx.repoRoot, project))) {
        notes.push('pytest: not run (no tests/)');
        return done();
      }
      // RUN_INTEGRATION would point pytest at a running stack; verify never needs one.
      const tests = await step(['uv', 'run', '--locked', 'pytest', '-q'], 900_000, { RUN_INTEGRATION: undefined });
      if (tests.exitCode === 1) findings.push({ rule: 'tests-pass', location: `${project}/tests/`, message: 'pytest reported failing tests', detail: tests.output });
      else if (tests.exitCode === 5) problems.push({ message: `pytest collected no tests in ${project}/`, repair: repair('tests-pass'), detail: tests.output });
      else if (tests.exitCode !== 0) unexpected('tests-pass', tests, 'uv run --locked pytest -q');
      return done();
    },
  });
}
