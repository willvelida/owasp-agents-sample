// Mirrors the lint, typecheck, and unit-test steps of the web job in .github/workflows/ci.yml.
// build, the e2e stub check, Playwright, and the header check stay CI-only.
import { readFile, stat } from 'node:fs/promises';
import { join } from 'node:path';
import { defineSensor } from '../core/contracts.ts';
import type { Finding, Problem } from '../core/contracts.ts';

const UI = 'solution/ui';
const INSTALL = `cd ${UI} && npm ci --ignore-scripts`;

// Accepts only the ">=A.B.C <D" shape the UI pins; anything else is unparseable and reported as a problem.
export function nodeInRange(version: string, range: string): boolean | null {
  const match = /^>=(\d+)\.(\d+)\.(\d+)\s+<(\d+)$/.exec(range.trim());
  if (match === null) return null;
  const [major, minor, patch] = version.split('.').map(Number) as [number, number, number];
  const [low1, low2, low3, high] = match.slice(1).map(Number) as [number, number, number, number];
  const atLeast = major !== low1 ? major > low1 : minor !== low2 ? minor > low2 : patch >= low3;
  return atLeast && major < high;
}

const STEPS = [
  { rule: 'lint-clean', script: 'lint', timeoutMs: 300_000 },
  { rule: 'types-clean', script: 'typecheck', timeoutMs: 300_000 },
  { rule: 'tests-pass', script: 'test', timeoutMs: 600_000 },
] as const;

export default defineSensor({
  description: `CI web job for ${UI}/: npm run lint, npm run typecheck, and npm test.`,
  paths: [`${UI}/`],
  requires: ['npm'],
  rules: [
    { id: 'lint-clean', expectation: '`npm run lint` passes (ESLint, XSS bans included)', repair: `in ${UI}/, run \`npm run lint\` and fix the reported issues` },
    { id: 'types-clean', expectation: '`npm run typecheck` passes', repair: `in ${UI}/, run \`npm run typecheck\` and fix the type errors` },
    { id: 'tests-pass', expectation: '`npm test` passes', repair: `in ${UI}/, run \`npm test\` and fix the failing tests` },
  ],
  async run(ctx) {
    const problems: Problem[] = [];
    let range: string | undefined;
    try {
      const manifest = JSON.parse(await readFile(join(ctx.repoRoot, UI, 'package.json'), 'utf8')) as { engines?: { node?: string } };
      range = manifest.engines?.node;
    } catch (error) {
      problems.push({ message: `cannot read ${UI}/package.json: ${(error as Error).message}`, repair: `restore ${UI}/package.json` });
    }
    if (range !== undefined) {
      const fits = nodeInRange(process.versions.node, range);
      if (fits === null) problems.push({ message: `cannot parse engines.node '${range}' in ${UI}/package.json`, repair: 'update the ui sensor to understand the new range' });
      else if (!fits) problems.push({ message: `node ${process.versions.node} is outside ${UI}'s engines range ${range}`, repair: 'install Node.js 24.22.0 (see CONTRIBUTING.md, Prerequisites)' });
    } else if (problems.length === 0) {
      problems.push({ message: `${UI}/package.json has no engines.node range`, repair: `restore engines.node in ${UI}/package.json` });
    }
    if (!(await stat(join(ctx.repoRoot, UI, 'node_modules')).catch(() => null))?.isDirectory()) {
      problems.push({ message: `${UI}/node_modules is missing`, repair: INSTALL });
    }
    if (problems.length > 0) return { checked: 0, findings: [], problems, notes: [] };

    const findings: Finding[] = [];
    for (const step of STEPS) {
      const result = await ctx.exec(['npm', 'run', step.script], { cwd: UI, timeoutMs: step.timeoutMs });
      if (result.exitCode !== 0 && !result.timedOut && result.spawnError === null) {
        findings.push({ rule: step.rule, location: `${UI}/`, message: `\`npm run ${step.script}\` exited with ${result.exitCode}`, detail: result.output });
      }
    }
    return { checked: STEPS.length, findings, problems, notes: [] };
  },
});
