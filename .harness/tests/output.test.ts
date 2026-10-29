import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { Rule } from '../core/contracts.ts';
import { formatReport, parseFlags, TAIL_LINES, tail } from '../core/output.ts';
import type { SensorRun } from '../core/run.ts';

const RULES: readonly Rule[] = [{ id: 'ruff-clean', expectation: 'ruff passes', repair: 'run `uv run --locked ruff check --fix`' }];

function run(name: string, status: SensorRun['status'], extra: Partial<SensorRun> = {}): SensorRun {
  return { name, status, checked: status === 'skipped' ? 0 : 3, durationMs: 1234, findings: [], problems: [], notes: [], ...extra };
}

function report(runs: SensorRun[], full = false) {
  const rules = new Map(runs.map((r) => [r.name, RULES]));
  return formatReport({ command: 'verify', header: ['base: main (merge-base abc1234)', 'changed: 2 files'], runs, rules, full, rerun: './harness verify' });
}

const ANSI = /\x1b/;
const longDetail = Array.from({ length: 100 }, (_, i) => `line ${i + 1}`).join('\n');

test('a passing run starts with verify: pass, ends with next:, and stays within N + 6 lines', () => {
  const runs = [run('a', 'pass'), run('b', 'pass', { notes: ['pytest: not run (no tests/)'] }), run('c', 'pass'), run('d', 'skipped'), run('e', 'skipped')];
  const { lines, code } = report(runs);
  assert.equal(code, 0);
  assert.equal(lines[0], 'verify: pass');
  assert.match(lines.at(-1) ?? '', /^next: /);
  assert.ok(lines.length <= 3 + 6, `got ${lines.length} lines`);
  assert.ok(lines.includes('skipped: d, e'));
  assert.ok(!lines.some((line) => ANSI.test(line)));
});

test('a failing sensor prints the finding with its repair and at most 30 lines of detail', () => {
  const finding = { rule: 'ruff-clean', location: 'solution/app.py:12', message: 'F401 `os` imported\nbut unused', detail: longDetail };
  const { lines, code } = report([run('python-solution', 'fail', { findings: [finding] })]);
  assert.equal(code, 1);
  assert.equal(lines[0], 'verify: fail');
  assert.ok(lines.includes('  ruff-clean: solution/app.py:12: F401 `os` imported but unused; repair: run `uv run --locked ruff check --fix`'));
  const detail = lines.filter((line) => line.startsWith('    | '));
  assert.equal(detail.length, TAIL_LINES);
  assert.equal(detail.at(-1), '    | line 100');
  assert.equal(lines.at(-1), 'next: fix the python-solution findings, then run ./harness verify');
});

test('the 30-line cap applies per sensor, not per finding', () => {
  const findings = [1, 2, 3].map((n) => ({ rule: 'ruff-clean', message: `f${n}`, detail: `${longDetail}\nfrom ${n}` }));
  const detail = report([run('s', 'fail', { findings })]).lines.filter((line) => line.startsWith('    | '));
  assert.equal(detail.length, TAIL_LINES);
});

test('--full prints the whole captured tail', () => {
  const problem = { message: 'uv sync failed', repair: 'run uv sync --locked', detail: longDetail };
  const { lines, code } = report([run('python-client', 'error', { problems: [problem] })], true);
  assert.equal(code, 2);
  assert.equal(lines[0], 'verify: error');
  assert.equal(lines.filter((line) => line.startsWith('    | ')).length, 100);
  assert.match(lines.at(-1) ?? '', /^next: resolve the python-client problems/);
});

test('tail handles empty text and CRLF', () => {
  assert.deepEqual(tail('', false), []);
  assert.deepEqual(tail('a\r\nb\r\n', false), ['a', 'b']);
});

test('parseFlags rejects unknown flags with the error contract', () => {
  const lines: string[] = [];
  const parsed = parseFlags('verify', './harness verify [--all]', ['--bogus'], { all: { type: 'boolean' } }, (line) => lines.push(line));
  assert.equal(parsed, null);
  assert.equal(lines[0], 'verify: error');
  assert.match(lines[1] ?? '', /^error: .*--bogus/);
  assert.equal(lines.at(-1), 'next: ./harness --help');
});

test('parseFlags returns values for known flags', () => {
  const parsed = parseFlags('verify', 'u', ['--all', '--base', 'main'], { all: { type: 'boolean' }, base: { type: 'string' } }, () => {});
  assert.deepEqual(parsed?.values, { all: true, base: 'main' });
});
