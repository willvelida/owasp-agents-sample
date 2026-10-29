import { applies, describeChanges, detectChanges } from '../core/changes.ts';
import { defineCommand } from '../core/contracts.ts';
import type { Rule } from '../core/contracts.ts';
import { formatReport, oneLine } from '../core/output.ts';
import { exec, which } from '../core/process.ts';
import { runSensors } from '../core/run.ts';

const USAGE = './harness verify [--all] [--base <ref>] [--full]';

export type FlagValues = Record<string, string | boolean | undefined>;
type Parsed = { values: FlagValues; positionals: string[] } | null;

/** Parses a command's flags strictly; writes usage errors and returns null so the command can exit 2. */
export function parseFlags(command: string, usage: string, argv: readonly string[], options: NonNullable<ParseArgsConfig['options']>, write: (line: string) => void, allowPositionals = false): Parsed {
  try {
    const parsed = parseArgs({ args: [...argv], options, strict: true, allowPositionals });
    return { values: { ...parsed.values } as FlagValues, positionals: parsed.positionals };
  } catch (error) {
    for (const line of [`${command}: error`, `error: ${oneLine((error as Error).message)}`, `usage: ${usage}`, 'next: ./harness --help']) write(line);
    return null;
  }
}

export default defineCommand({
  description: 'Definition of done: run every sensor that applies to the change (or all with --all).',
  usage: USAGE,
  async run(ctx) {
    const options = { all: { type: 'boolean' }, base: { type: 'string' }, full: { type: 'boolean' } } as const;
    const parsed = parseFlags('verify', USAGE, ctx.argv, options, ctx.write);
    if (parsed === null) return 2;
    const all = parsed.values.all === true;
    const base = typeof parsed.values.base === 'string' ? parsed.values.base : undefined;
    const fail = (message: string, next: string): 2 => {
      for (const line of ['verify: error', `error: ${message}`, `next: ${next}`]) ctx.write(line);
      return 2;
    };
    if (all && base !== undefined) return fail('--all and --base cannot be used together', './harness --help');
    if (ctx.sensors.size === 0) return fail('no sensors found in .harness/sensors/', './harness doctor');

    const run = (argv: readonly [string, ...string[]], opts: { cwd: string; timeoutMs: number }, stderr?: boolean) =>
      exec(ctx.repoRoot, argv, opts, stderr);
    let changedFiles: readonly string[] | null = null;
    let header = ['scope: all sensors (--all)'];
    if (!all) {
      const result = await detectChanges(run, base);
      if (!result.ok) return fail(result.message, result.next);
      changedFiles = result.changes.files;
      header = describeChanges(result.changes);
      const anyApplies = [...ctx.sensors.values()].some((sensor) => applies(changedFiles, sensor.paths, sensor.exclude));
      if (!anyApplies) {
        for (const line of ['verify: pass', 'sensors: none apply to the changed files', 'next: ./harness verify --all to check everything']) {
          ctx.write(line);
        }
        return 0;
      }
    }

    const runs = await runSensors(ctx.sensors, { repoRoot: ctx.repoRoot, changedFiles, exec: run, which });
    const rules = new Map<string, readonly Rule[]>([...ctx.sensors].map(([name, sensor]) => [name, sensor.rules]));
    const rerun = all ? './harness verify --all' : base !== undefined ? `./harness verify --base ${base}` : './harness verify';
    const { lines, code } = formatReport({ command: 'verify', header, runs, rules, full: parsed.values.full === true, rerun });
    for (const line of lines) ctx.write(line);
    return code;
  },
});
import { parseArgs } from 'node:util';
import type { ParseArgsConfig } from 'node:util';
