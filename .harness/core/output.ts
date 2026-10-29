import { parseArgs } from 'node:util';
import type { ParseArgsConfig } from 'node:util';
import type { ExitCode, Rule } from './contracts.ts';
import { exitCodeFor, statusFor } from './run.ts';
import type { SensorRun } from './run.ts';

export const TAIL_LINES = 30;
export const oneLine = (text: string): string => text.replace(/\s*\r?\n\s*/g, ' ').trim();

export function tail(text: string, full: boolean): string[] {
  const trimmed = text.replace(/\r\n/g, '\n').replace(/\n+$/, '');
  if (trimmed === '') return [];
  const lines = trimmed.split('\n');
  return full ? lines : lines.slice(-TAIL_LINES);
}

// One line per finding or problem with its repair, then one capped tail of the tool output for the whole sensor.
export function sensorLines(run: SensorRun, rules: readonly Rule[], full: boolean): string[] {
  const notes = run.notes.length > 0 ? `; ${run.notes.map(oneLine).join('; ')}` : '';
  const lines = [`${run.name}: ${run.status} (${run.checked} checked, ${(run.durationMs / 1000).toFixed(1)}s${notes})`];
  if (run.status !== 'fail' && run.status !== 'error') return lines;
  const details = new Set<string>();
  for (const problem of run.problems) {
    lines.push(`  problem: ${oneLine(problem.message)}; repair: ${oneLine(problem.repair)}`);
    if (problem.detail?.trim()) details.add(problem.detail);
  }
  for (const finding of run.findings) {
    const repair = rules.find((rule) => rule.id === finding.rule)?.repair ?? `see ./harness sensors ${run.name}`;
    const where = finding.location ? `${finding.location}: ` : '';
    lines.push(`  ${finding.rule}: ${where}${oneLine(finding.message)}; repair: ${oneLine(repair)}`);
    if (finding.detail?.trim()) details.add(finding.detail);
  }
  return [...lines, ...tail([...details].join('\n'), full).map((line) => `    | ${line}`)];
}

export interface Report {
  readonly command: string;
  readonly header: readonly string[];
  readonly runs: readonly SensorRun[];
  readonly rules: ReadonlyMap<string, readonly Rule[]>;
  readonly full: boolean;
  readonly rerun: string;
}

export function formatReport(report: Report): { lines: string[]; code: ExitCode } {
  const code = exitCodeFor(report.runs.map((run) => run.status));
  const ran = report.runs.filter((run) => run.status !== 'skipped');
  const skipped = report.runs.filter((run) => run.status === 'skipped').map((run) => run.name);
  const lines = [`${report.command}: ${statusFor(code)}`, ...report.header];
  for (const run of ran) lines.push(...sensorLines(run, report.rules.get(run.name) ?? [], report.full));
  if (skipped.length > 0) lines.push(`skipped: ${skipped.join(', ')}`);
  const names = (status: string): string => ran.filter((run) => run.status === status).map((run) => run.name).join(', ');
  if (code === 0) lines.push('next: all checks pass; the change is ready to commit');
  else lines.push(code === 1 ? `next: fix the ${names('fail')} findings, then run ${report.rerun}` : `next: resolve the ${names('error')} problems, then run ${report.rerun}`);
  return { lines, code };
}

export type FlagValues = Record<string, string | boolean | undefined>;
type Parsed = { values: FlagValues; positionals: string[] } | null;

// Strict parsing of a command's own flags. On a usage error it writes the error lines and returns null; the command exits 2.
export function parseFlags(command: string, usage: string, argv: readonly string[], options: NonNullable<ParseArgsConfig['options']>, write: (line: string) => void, allowPositionals = false): Parsed {
  try {
    const parsed = parseArgs({ args: [...argv], options, strict: true, allowPositionals });
    return { values: { ...parsed.values } as FlagValues, positionals: parsed.positionals };
  } catch (error) {
    for (const line of [`${command}: error`, `error: ${oneLine((error as Error).message)}`, `usage: ${usage}`, 'next: ./harness --help']) write(line);
    return null;
  }
}
