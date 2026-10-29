// The harness checks itself: CI does not run it, so this sensor is the only automatic check on .harness/.
import { stat } from 'node:fs/promises';
import { join } from 'node:path';
import { defineSensor } from '../core/contracts.ts';
import type { Finding, Problem } from '../core/contracts.ts';

const INSTALL = 'cd .harness && npm ci --ignore-scripts';

export default defineSensor({
  description: 'The harness itself: tsc --noEmit (erasable syntax, contracts) and node --test.',
  paths: ['.harness/', 'harness', 'harness.cmd'],
  requires: [],
  rules: [
    { id: 'types-clean', expectation: '`tsc --noEmit -p .harness/tsconfig.json` reports no errors', repair: 'in .harness/, run `npm run typecheck` and fix the errors' },
    { id: 'tests-pass', expectation: '`node --test` passes for .harness/tests', repair: 'in .harness/, run `npm test` and fix the failing tests' },
  ],
  async run(ctx) {
    if (!(await stat(join(ctx.repoRoot, '.harness', 'node_modules', 'typescript')).catch(() => null))?.isDirectory()) {
      return { checked: 0, findings: [], problems: [{ message: '.harness/node_modules/typescript is missing', repair: INSTALL }], notes: [] };
    }
    // process.execPath runs tsc and the test runner without the Windows npm.cmd shim.
    const steps = [
      { rule: 'types-clean', argv: [process.execPath, '.harness/node_modules/typescript/bin/tsc', '--noEmit', '-p', '.harness/tsconfig.json'], timeoutMs: 180_000 },
      { rule: 'tests-pass', argv: [process.execPath, '--test', '.harness/tests/**/*.test.ts'], timeoutMs: 300_000 },
    ] as const;
    const findings: Finding[] = [];
    const problems: Problem[] = [];
    for (const step of steps) {
      const result = await ctx.exec(step.argv, { cwd: '.', timeoutMs: step.timeoutMs });
      if (result.exitCode !== 0 && !result.timedOut && result.spawnError === null) {
        const command = step.rule === 'types-clean' ? 'npm run typecheck' : 'npm test';
        const message = `${step.rule === 'types-clean' ? 'tsc' : 'node --test'} exited with ${result.exitCode}`;
        if (result.exitCode === null) problems.push({ message, repair: `in .harness/, run \`${command}\` by hand to diagnose termination`, detail: result.output });
        else findings.push({ rule: step.rule, location: '.harness/', message, detail: result.output });
      }
    }
    return { checked: steps.length, findings, problems, notes: [] };
  },
});
