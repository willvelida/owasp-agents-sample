import assert from 'node:assert/strict';
import { mkdir, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import type { ExecResult, SensorContext } from '../core/contracts.ts';
import { runSensor } from '../core/run.ts';
import harness from '../sensors/harness.ts';

test('each harness step maps non-zero to its finding rule and null to error', async () => {
  const root = await mkdtemp(join(tmpdir(), 'harness-self-steps-'));
  try {
    await mkdir(join(root, '.harness', 'node_modules', 'typescript'), { recursive: true });
    for (const rule of ['types-clean', 'tests-pass']) {
      for (const exitCode of [1, null]) {
        const calls: string[] = [];
        const ctx: SensorContext = {
          repoRoot: root, changedFiles: null, which: async () => assert.fail('no tool lookup needed'),
          exec: async (argv, options): Promise<ExecResult> => {
            assert.equal(argv[0], process.execPath);
            assert.equal(options.cwd, '.');
            const step = argv[1] === '--test' ? 'tests-pass' : 'types-clean';
            calls.push(step);
            return { exitCode: step === rule ? exitCode : 0, timedOut: false, spawnError: null, output: 'synthetic output', truncated: false, durationMs: 1 };
          },
        };
        const result = await runSensor('harness', harness, ctx);
        assert.deepEqual(calls, ['types-clean', 'tests-pass']);
        assert.equal(result.checked, 2);
        assert.equal(result.status, exitCode === null ? 'error' : 'fail');
        assert.deepEqual(result.findings.map((finding) => finding.rule), exitCode === null ? [] : [rule]);
        assert.equal(result.problems.length, exitCode === null ? 1 : 0);
      }
    }
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
