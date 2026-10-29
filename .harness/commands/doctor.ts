import { readFile, stat } from 'node:fs/promises';
import { join } from 'node:path';
import { describeChanges, detectChanges } from '../core/changes.ts';
import { defineCommand } from '../core/contracts.ts';
import type { Tool } from '../core/contracts.ts';
import { parseFlags } from './verify.ts';
import { exec, which } from '../core/process.ts';
import { TOOL_REPAIR } from '../core/run.ts';

const USAGE = './harness doctor';
const HARNESS_MINIMUM = '24.12.0';
const NODE_REPAIR = 'install Node.js 24.22.0 (see CONTRIBUTING.md, Prerequisites)';

const parse = (version: string): number[] => version.replace(/^v/, '').split('.').map((part) => Number.parseInt(part, 10) || 0);

function compare(a: string, b: string): number {
  const [x, y] = [parse(a), parse(b)];
  for (let i = 0; i < 3; i++) if ((x[i] ?? 0) !== (y[i] ?? 0)) return (x[i] ?? 0) - (y[i] ?? 0);
  return 0;
}

// Handles the space-separated comparator ranges used in engines fields, such as ">=24.22.0 <25".
export function satisfies(version: string, range: string): boolean {
  return range.trim().split(/\s+/).every((part) => {
    const match = /^(>=|<=|>|<|=)?v?(\d+(?:\.\d+){0,2})$/.exec(part);
    if (match === null) return false;
    const diff = compare(version, match[2] ?? '0');
    return { '>=': diff >= 0, '<=': diff <= 0, '>': diff > 0, '<': diff < 0, '=': diff === 0 }[match[1] ?? '='] ?? false;
  });
}

async function uiEngines(repoRoot: string): Promise<string | null> {
  try {
    const manifest = JSON.parse(await readFile(join(repoRoot, 'solution', 'ui', 'package.json'), 'utf8')) as { engines?: { node?: string } };
    return manifest.engines?.node ?? null;
  } catch {
    return null;
  }
}

export default defineCommand({
  description: 'Diagnose the environment: Node, uv, git, the base ref, installed node_modules, and discovery.',
  usage: USAGE,
  async run(ctx) {
    if (parseFlags('doctor', USAGE, ctx.argv, {}, ctx.write) === null) return 2;
    const lines: string[] = [];
    let missing = 0;
    const problem = (label: string, message: string, repair: string): void => {
      missing++;
      lines.push(`${label}: ${message}; repair: ${repair}`);
    };

    const node = process.versions.node;
    const engines = await uiEngines(ctx.repoRoot);
    const harnessOk = compare(node, HARNESS_MINIMUM) >= 0;
    const uiOk = engines === null || satisfies(node, engines);
    const detail = `harness needs >=${HARNESS_MINIMUM}; solution/ui needs ${engines ?? 'unknown (no engines field)'}`;
    if (harnessOk && uiOk) lines.push(`node: ${node} (${detail})`);
    else problem('node', `${node} is outside the supported range (${detail})`, NODE_REPAIR);

    for (const tool of ['uv', 'git'] as const satisfies readonly Tool[]) {
      if ((await which(tool)) === null) {
        problem(tool, 'not found', TOOL_REPAIR[tool]);
        continue;
      }
      const version = await exec(ctx.repoRoot, [tool, '--version'], { cwd: '.', timeoutMs: 15_000 }, false);
      if (version.exitCode === 0) lines.push(`${tool}: ${version.output.trim().split('\n')[0]}`);
      else problem(tool, `\`${tool} --version\` failed`, TOOL_REPAIR[tool]);
    }

    const changes = await detectChanges((argv, options, stderr) => exec(ctx.repoRoot, argv, options, stderr));
    lines.push(changes.ok ? describeChanges(changes.changes)[0] ?? 'base: none' : `base: none (${changes.message})`);

    for (const folder of ['solution/ui', '.harness']) {
      const present = (await stat(join(ctx.repoRoot, folder, 'node_modules')).catch(() => null))?.isDirectory() === true;
      if (present) lines.push(`${folder}/node_modules: present`);
      else problem(`${folder}/node_modules`, 'missing', `in ${folder}, run npm ci --ignore-scripts`);
    }
    lines.push(`discovery: ${ctx.sensors.size} sensors and ${ctx.commands.size} commands, all valid`);

    ctx.write(missing === 0 ? 'doctor: pass' : 'doctor: fail');
    for (const line of lines) ctx.write(line);
    ctx.write(missing === 0 ? 'next: ./harness verify' : 'next: apply the repairs above, then run ./harness doctor');
    return missing === 0 ? 0 : 1;
  },
});
