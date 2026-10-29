import assert from 'node:assert/strict';
import { test } from 'node:test';
import { defineSensor } from '../core/contracts.ts';
import type { ExecResult, SensorResult, Tool } from '../core/contracts.ts';
import { exitCodeFor, runSensor, runSensors, statusFor } from '../core/run.ts';
import type { RunEnv } from '../core/run.ts';

const OK: ExecResult = { exitCode: 0, timedOut: false, spawnError: null, output: '', truncated: false, durationMs: 1 };
const RESULT: SensorResult = { checked: 1, findings: [], problems: [], notes: [] };

function env(options: { files?: string[] | null; missing?: Tool[]; exec?: Partial<ExecResult> } = {}): RunEnv {
  return {
    repoRoot: '/repo',
    changedFiles: options.files === undefined ? null : options.files,
    exec: async () => ({ ...OK, ...options.exec }),
    which: async (tool) => (options.missing?.includes(tool) ? null : `/usr/bin/${tool}`),
  };
}

function sensor(run: () => Promise<SensorResult>, extra: { requires?: Tool[]; exclude?: string[] } = {}) {
  return defineSensor({
    description: 'test sensor',
    paths: ['project/', 'root.txt'],
    requires: extra.requires ?? [],
    ...(extra.exclude ? { exclude: extra.exclude } : {}),
    rules: [{ id: 'rule-a', expectation: 'holds', repair: 'fix it' }],
    run,
  });
}

test('paths that match no changed file give skipped without running', async () => {
  let ran = false;
  const run = await runSensor('s', sensor(async () => ((ran = true), RESULT)), env({ files: ['other/file.py'] }));
  assert.equal(run.status, 'skipped');
  assert.equal(ran, false);
});

test('exclude removes otherwise matching files', async () => {
  const run = await runSensor('s', sensor(async () => RESULT, { exclude: ['project/docs/'] }), env({ files: ['project/docs/a.md'] }));
  assert.equal(run.status, 'skipped');
});

test('no findings, no problems, and checked > 0 give pass', async () => {
  const run = await runSensor('s', sensor(async () => RESULT), env({ files: ['project/a.py'] }));
  assert.equal(run.status, 'pass');
});

test('findings without problems give fail', async () => {
  const result = { ...RESULT, findings: [{ rule: 'rule-a', message: 'broken' }] };
  assert.equal((await runSensor('s', sensor(async () => result), env())).status, 'fail');
});

test('a problem gives error even with findings', async () => {
  const result = { ...RESULT, findings: [{ rule: 'rule-a', message: 'x' }], problems: [{ message: 'no result', repair: 'r' }] };
  assert.equal((await runSensor('s', sensor(async () => result), env())).status, 'error');
});

test('a throwing sensor gives error', async () => {
  const run = await runSensor('s', sensor(async () => { throw new Error('boom'); }), env());
  assert.equal(run.status, 'error');
  assert.match(run.problems[0]?.message ?? '', /boom/);
});

test('checked === 0 gives error', async () => {
  const run = await runSensor('s', sensor(async () => ({ ...RESULT, checked: 0 })), env());
  assert.equal(run.status, 'error');
});

test('a missing required tool gives error and run() is not called', async () => {
  let ran = false;
  const run = await runSensor('s', sensor(async () => ((ran = true), RESULT), { requires: ['git', 'uv'] }), env({ missing: ['uv'] }));
  assert.equal(run.status, 'error');
  assert.equal(ran, false);
  assert.match(run.problems[0]?.message ?? '', /uv not found/);
});

for (const [label, exec] of [['timed out', { timedOut: true, exitCode: null }], ['failed to start', { spawnError: 'ENOENT', exitCode: null }]] as const) {
  test(`an exec that ${label} forces error even when run() reports a pass`, async () => {
    const definition = sensor(async () => RESULT);
    const withExec = defineSensor({ ...definition, run: async (ctx) => (await ctx.exec(['uv', 'sync'], { cwd: 'project', timeoutMs: 1000 }), RESULT) });
    const run = await runSensor('s', withExec, env({ exec }));
    assert.equal(run.status, 'error');
    assert.match(run.problems[0]?.message ?? '', new RegExp(label));
  });
}

test('sensors run in name order', async () => {
  const order: string[] = [];
  const make = (name: string) => sensor(async () => (order.push(name), RESULT));
  await runSensors(new Map([['zeta', make('zeta')], ['alpha', make('alpha')], ['mid-1', make('mid-1')]]), env());
  assert.deepEqual(order, ['alpha', 'mid-1', 'zeta']);
});

test('exit code aggregation: error beats fail beats pass and skipped', () => {
  assert.equal(exitCodeFor([]), 0);
  assert.equal(exitCodeFor(['pass', 'skipped']), 0);
  assert.equal(exitCodeFor(['pass', 'fail', 'skipped']), 1);
  assert.equal(exitCodeFor(['fail', 'error', 'pass']), 2);
  assert.deepEqual([0, 1, 2].map((code) => statusFor(code as 0 | 1 | 2)), ['pass', 'fail', 'error']);
});
