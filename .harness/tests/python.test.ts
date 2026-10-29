import assert from 'node:assert/strict';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { after, test } from 'node:test';
import type { ExecOptions, ExecResult, SensorContext, SensorDefinition } from '../core/contracts.ts';
import { pythonSensor } from '../core/python.ts';
import { runSensor } from '../core/run.ts';
import pythonClient from '../sensors/python-client.ts';
import pythonRedteam from '../sensors/python-redteam.ts';
import pythonSolution from '../sensors/python-solution.ts';
import pythonStarter from '../sensors/python-starter.ts';

const dirs: string[] = [];
after(async () => {
  for (const dir of dirs) await rm(dir, { recursive: true, force: true });
});

const OK: ExecResult = { exitCode: 0, timedOut: false, spawnError: null, output: '', truncated: false, durationMs: 1 };
const LOCK = 'lock --check';
const SYNC = 'sync --locked';
const RUFF = 'run --locked ruff check --output-format concise';
const FORMAT = 'run --locked ruff format --check';
const PYTEST = 'run --locked pytest -q';

interface Call { readonly key: string; readonly options: ExecOptions }

async function repo(withTests: boolean): Promise<string> {
  const root = await mkdtemp(join(tmpdir(), 'harness-python-'));
  dirs.push(root);
  if (withTests) {
    await mkdir(join(root, 'client', 'tests', 'unit'), { recursive: true });
    await writeFile(join(root, 'client', 'tests', 'unit', 'test_x.py'), 'def test_x():\n    pass\n');
  }
  return root;
}

function fake(repoRoot: string, script: Record<string, Partial<ExecResult>> = {}) {
  const calls: Call[] = [];
  const exec = async (argv: readonly [string, ...string[]], options: ExecOptions): Promise<ExecResult> => {
    assert.equal(argv[0], 'uv');
    const key = argv.slice(1).join(' ');
    calls.push({ key, options });
    return { ...OK, ...script[key] };
  };
  const ctx: SensorContext = { repoRoot, changedFiles: null, exec, which: async (tool) => `/bin/${tool}` };
  return { ctx, calls, env: { repoRoot, changedFiles: null, exec, which: ctx.which } };
}

const sensor = pythonSensor({ project: 'client', paths: ['client/'] });

test('the four sensors declare the contract paths and excludes', () => {
  const table: [SensorDefinition, string[], string[] | undefined][] = [
    [pythonStarter, ['starter/', 'ruff.toml'], undefined],
    [pythonSolution, ['solution/', 'ruff.toml'], ['solution/ui/']],
    [pythonClient, ['client/', 'ruff.toml'], undefined],
    [pythonRedteam, ['redteam/', 'client/', 'ruff.toml'], undefined],
  ];
  for (const [definition, paths, exclude] of table) {
    assert.deepEqual(definition.paths, paths);
    assert.deepEqual(definition.exclude, exclude);
    assert.deepEqual(definition.requires, ['uv']);
    assert.deepEqual(definition.rules.map((rule) => rule.id), ['lock-current', 'env-synced', 'ruff-clean', 'ruff-formatted', 'tests-pass']);
  }
});

test('without tests/ it runs four steps in order in the project folder and notes the skipped pytest', async () => {
  const { ctx, calls } = fake(await repo(false));
  const result = await sensor.run(ctx);
  assert.deepEqual(calls.map((call) => call.key), [LOCK, SYNC, RUFF, FORMAT]);
  assert.ok(calls.every((call) => call.options.cwd === 'client'));
  assert.deepEqual(result, { checked: 4, findings: [], problems: [], notes: ['pytest: not run (no tests/)'] });
});

test('with tests/ it runs pytest last, without RUN_INTEGRATION', async () => {
  const { ctx, calls } = fake(await repo(true));
  const result = await sensor.run(ctx);
  assert.deepEqual(calls.map((call) => call.key), [LOCK, SYNC, RUFF, FORMAT, PYTEST]);
  const pytest = calls.at(-1)?.options;
  assert.ok(pytest?.env && 'RUN_INTEGRATION' in pytest.env && pytest.env.RUN_INTEGRATION === undefined);
  assert.equal(result.checked, 5);
  assert.deepEqual(result.notes, []);
});

test('a stale lock is a finding and stops later steps', async () => {
  const { ctx, calls } = fake(await repo(true), { [LOCK]: { exitCode: 1, output: 'lock out of date' } });
  const result = await sensor.run(ctx);
  assert.deepEqual(calls.map((call) => call.key), [LOCK]);
  assert.equal(result.findings[0]?.rule, 'lock-current');
  assert.equal(result.findings[0]?.location, 'client/uv.lock');
});

test('a failed sync is a problem and stops later steps', async () => {
  const { ctx, calls, env } = fake(await repo(true), { [SYNC]: { exitCode: 2, output: 'network down' } });
  const result = await sensor.run(ctx);
  assert.deepEqual(calls.map((call) => call.key), [LOCK, SYNC]);
  assert.equal(result.problems.length, 1);
  assert.equal((await runSensor('python-client', sensor, env)).status, 'error');
});

test('ruff and format violations become one finding per file line, and both steps still run', async () => {
  const ruff = 'src\\biotrackr_client\\probe.py:3:8: F401 [*] `os` imported but unused\nFound 1 error.\n';
  const format = 'Would reformat: src\\biotrackr_client\\probe.py\n1 file would be reformatted\n';
  const { ctx, calls, env } = fake(await repo(false), { [RUFF]: { exitCode: 1, output: ruff }, [FORMAT]: { exitCode: 1, output: format } });
  const result = await sensor.run(ctx);
  assert.deepEqual(calls.map((call) => call.key), [LOCK, SYNC, RUFF, FORMAT]);
  assert.deepEqual(result.findings, [
    { rule: 'ruff-clean', location: 'client/src/biotrackr_client/probe.py:3', message: 'F401 [*] `os` imported but unused' },
    { rule: 'ruff-formatted', location: 'client/src/biotrackr_client/probe.py', message: 'ruff format would reformat files' },
  ]);
  assert.equal((await runSensor('python-client', sensor, env)).status, 'fail');
});

test('ruff exiting with anything other than 0 or 1 is a problem', async () => {
  const { ctx } = fake(await repo(false), { [RUFF]: { exitCode: 2, output: 'config error' } });
  const result = await sensor.run(ctx);
  assert.equal(result.findings.length, 0);
  assert.match(result.problems[0]?.message ?? '', /ruff check.*exited with 2/);
});

test('pytest exit 1 is a finding; exit 5 and other codes are problems', async () => {
  const root = await repo(true);
  const failing = await sensor.run(fake(root, { [PYTEST]: { exitCode: 1, output: '1 failed' } }).ctx);
  assert.equal(failing.findings[0]?.rule, 'tests-pass');
  assert.equal(failing.problems.length, 0);
  const none = await sensor.run(fake(root, { [PYTEST]: { exitCode: 5 } }).ctx);
  assert.match(none.problems[0]?.message ?? '', /collected no tests/);
  const crashed = await sensor.run(fake(root, { [PYTEST]: { exitCode: 3 } }).ctx);
  assert.equal(crashed.problems.length, 1);
  assert.equal(crashed.findings.length, 0);
});

test('a timed-out step leaves the problem to the runner', async () => {
  const { ctx, env } = fake(await repo(false), { [SYNC]: { exitCode: null, timedOut: true } });
  const result = await sensor.run(ctx);
  assert.deepEqual(result.problems, []);
  const run = await runSensor('python-client', sensor, env);
  assert.equal(run.status, 'error');
  assert.match(run.problems[0]?.message ?? '', /timed out/);
});

test('every Python step with a null exit code is an error, never a finding', async () => {
  const root = await repo(true);
  for (const key of [LOCK, SYNC, RUFF, FORMAT, PYTEST]) {
    const { env } = fake(root, { [key]: { exitCode: null, output: 'terminated' } });
    const result = await runSensor('python-client', sensor, env);
    assert.equal(result.status, 'error', key);
    assert.deepEqual(result.findings, [], key);
    assert.equal(result.problems.length, 1, key);
    assert.match(result.problems[0]?.message ?? '', /exited with null/);
    assert.match(result.problems[0]?.repair ?? '', /diagnose termination/);
  }
});
