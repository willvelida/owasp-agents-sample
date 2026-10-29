import assert from 'node:assert/strict';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { after, test } from 'node:test';
import type { ExecResult, SensorContext } from '../core/contracts.ts';
import { runSensor } from '../core/run.ts';
import ui, { nodeInRange } from '../sensors/ui.ts';

const dirs: string[] = [];
after(async () => {
  for (const dir of dirs) await rm(dir, { recursive: true, force: true });
});

test('nodeInRange reads the >=A.B.C <D shape and rejects anything else', () => {
  assert.equal(nodeInRange('24.22.1', '>=24.22.0 <25'), true);
  assert.equal(nodeInRange('24.22.0', '>=24.22.0 <25'), true);
  assert.equal(nodeInRange('24.21.9', '>=24.22.0 <25'), false);
  assert.equal(nodeInRange('25.0.0', '>=24.22.0 <25'), false);
  assert.equal(nodeInRange('24.22.1', '^24.22.0'), null);
});

test('missing node_modules or an unparseable range is a problem, and no npm step runs', async () => {
  const root = await mkdtemp(join(tmpdir(), 'harness-ui-'));
  dirs.push(root);
  await mkdir(join(root, 'solution', 'ui'), { recursive: true });
  await writeFile(join(root, 'solution', 'ui', 'package.json'), JSON.stringify({ engines: { node: '^24' } }));
  const ctx: SensorContext = { repoRoot: root, changedFiles: null, exec: async () => assert.fail('no npm step may run'), which: async () => null };
  const result = await ui.run(ctx);
  assert.equal(result.checked, 0);
  assert.deepEqual(result.problems.map((problem) => problem.message.split(' ')[0]), ['cannot', 'solution/ui/node_modules']);
  assert.equal(result.problems[1]?.repair, 'cd solution/ui && npm ci --ignore-scripts');
});

test('each UI step maps non-zero to its finding rule and null to error', async () => {
  const root = await mkdtemp(join(tmpdir(), 'harness-ui-steps-'));
  dirs.push(root);
  await mkdir(join(root, 'solution', 'ui', 'node_modules'), { recursive: true });
  const major = Number(process.versions.node.split('.')[0]);
  await writeFile(join(root, 'solution', 'ui', 'package.json'), JSON.stringify({ engines: { node: `>=${major}.0.0 <${major + 1}` } }));
  const steps = [['lint', 'lint-clean'], ['typecheck', 'types-clean'], ['test', 'tests-pass']] as const;
  for (const [script, rule] of steps) {
    for (const exitCode of [1, null]) {
      const calls: string[] = [];
      const ctx: SensorContext = {
        repoRoot: root, changedFiles: null, which: async () => 'synthetic-npm',
        exec: async (argv, options): Promise<ExecResult> => {
          assert.deepEqual(argv.slice(0, 2), ['npm', 'run']);
          assert.equal(options.cwd, 'solution/ui');
          calls.push(argv[2]!);
          return { exitCode: argv[2] === script ? exitCode : 0, timedOut: false, spawnError: null, output: 'synthetic output', truncated: false, durationMs: 1 };
        },
      };
      const result = await runSensor('ui', ui, ctx);
      assert.deepEqual(calls, ['lint', 'typecheck', 'test']);
      assert.equal(result.checked, 3);
      assert.equal(result.status, exitCode === null ? 'error' : 'fail');
      assert.deepEqual(result.findings.map((finding) => finding.rule), exitCode === null ? [] : [rule]);
      assert.equal(result.problems.length, exitCode === null ? 1 : 0);
    }
  }
});
