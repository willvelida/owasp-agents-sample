import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { after, test } from 'node:test';
import doctor, { satisfies } from '../commands/doctor.ts';
import home from '../commands/home.ts';
import sensors from '../commands/sensors.ts';
import verify from '../commands/verify.ts';
import { defineSensor } from '../core/contracts.ts';
import type { CommandDefinition, SensorDefinition, SensorResult } from '../core/contracts.ts';

const dirs: string[] = [];
after(async () => {
  for (const dir of dirs) await rm(dir, { recursive: true, force: true });
});

const PASS: SensorResult = { checked: 2, findings: [], problems: [], notes: [] };
const sensor = (paths: string[], result: SensorResult = PASS): SensorDefinition =>
  defineSensor({
    description: 'checks a project',
    paths,
    requires: [],
    rules: [{ id: 'lint-clean', expectation: 'lint passes', repair: 'run the linter with --fix' }],
    run: async () => result,
  });

const REPO_ROOT = resolve(import.meta.dirname, '..', '..');
const COMMANDS = new Map<string, CommandDefinition>([['home', home], ['verify', verify], ['sensors', sensors], ['doctor', doctor]]);

async function call(command: CommandDefinition, argv: string[], sensorMap: Map<string, SensorDefinition>, repoRoot = REPO_ROOT) {
  const lines: string[] = [];
  const code = await command.run({ repoRoot, argv, sensors: sensorMap, commands: COMMANDS, write: (line) => lines.push(line) });
  return { code, lines };
}

async function gitRepo(): Promise<string> {
  const dir = await mkdtemp(join(tmpdir(), 'harness-commands-'));
  dirs.push(dir);
  const git = (...args: string[]) =>
    assert.equal(spawnSync('git', ['-c', 'user.name=harness-test', '-c', 'user.email=harness-test@example.invalid', '-c', 'commit.gpgsign=false', ...args], { cwd: dir }).status, 0);
  git('init', '-q', '-b', 'main');
  await writeFile(join(dir, 'README.md'), 'x\n');
  git('add', '.');
  git('commit', '-q', '-m', 'base');
  return dir;
}

const lastIsNext = (lines: string[]) => assert.match(lines.at(-1) ?? '', /^next: /);

test('sensors lists one line per sensor', async () => {
  const { code, lines } = await call(sensors, [], new Map([['alpha', sensor(['alpha/'])], ['beta', sensor(['beta/', 'b.toml'])]]));
  assert.equal(code, 0);
  assert.equal(lines[0], 'sensors: pass');
  assert.equal(lines[1], 'alpha: checks a project (paths: alpha/; requires: none)');
  assert.equal(lines[2], 'beta: checks a project (paths: beta/, b.toml; requires: none)');
  assert.equal(lines.length, 4);
  lastIsNext(lines);
});

test('sensors <name> explains the rules with their repairs', async () => {
  const { code, lines } = await call(sensors, ['alpha'], new Map([['alpha', sensor(['alpha/'])]]));
  assert.equal(code, 0);
  assert.equal(lines[0], 'sensors: pass');
  assert.ok(lines.includes('  lint-clean: lint passes; repair: run the linter with --fix'));
  lastIsNext(lines);
});

test('sensors with an unknown name exits 2', async () => {
  assert.deepEqual(await call(sensors, ['nope'], new Map()), {
    code: 2,
    lines: ['sensors: error', "error: unknown sensor 'nope'", 'next: ./harness sensors'],
  });
});

test('verify rejects --all with --base and unknown flags', async () => {
  const map = new Map([['alpha', sensor(['alpha/'])]]);
  const both = await call(verify, ['--all', '--base', 'main'], map);
  assert.equal(both.code, 2);
  assert.equal(both.lines[0], 'verify: error');
  assert.equal((await call(verify, ['--only', 'x'], map)).code, 2);
});

test('verify passes with a definitive message when no sensor applies', async () => {
  const repo = await gitRepo();
  const { code, lines } = await call(verify, [], new Map([['alpha', sensor(['alpha/'])]]), repo);
  assert.equal(code, 0);
  assert.deepEqual(lines, ['verify: pass', 'sensors: none apply to the changed files', 'next: ./harness verify --all to check everything']);
});

test('verify --all runs every sensor within the N + 6 line budget and aggregates failures', async () => {
  const map = new Map([['alpha', sensor(['alpha/'])], ['beta', sensor(['beta/'])]]);
  const passing = await call(verify, ['--all'], map);
  assert.equal(passing.code, 0);
  assert.equal(passing.lines[0], 'verify: pass');
  assert.ok(passing.lines.length <= 2 + 6);
  lastIsNext(passing.lines);
  map.set('gamma', sensor(['gamma/'], { ...PASS, findings: [{ rule: 'lint-clean', message: 'bad', location: 'gamma/x.py:3' }] }));
  const failing = await call(verify, ['--all'], map);
  assert.equal(failing.code, 1);
  assert.ok(failing.lines.includes('  lint-clean: gamma/x.py:3: bad; repair: run the linter with --fix'));
  assert.equal(failing.lines.at(-1), 'next: fix the gamma findings, then run ./harness verify --all');
});

test('home reports base, change size, applicable sensors, and next', async () => {
  const repo = await gitRepo();
  await writeFile(join(repo, 'new.txt'), 'untracked\n');
  const { code, lines } = await call(home, [], new Map([['alpha', sensor(['alpha/'])], ['root', sensor(['new.txt'])]]), repo);
  assert.equal(code, 0);
  assert.equal(lines[0], 'home: pass');
  assert.match(lines[1] ?? '', /^base: main \(merge-base [0-9a-f]{7}\)$/);
  assert.equal(lines[2], 'changed: 1 file');
  assert.equal(lines[3], 'applies: root');
  assert.equal(lines[4], 'commands: home, verify, sensors, doctor');
  assert.equal(lines.at(-1), 'next: ./harness verify');
  assert.ok(lines.length <= 8);
});

test('home outside a work tree is an error', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'harness-home-'));
  dirs.push(dir);
  const { code, lines } = await call(home, [], new Map(), dir);
  assert.equal(code, 2);
  assert.equal(lines[0], 'home: error');
  assert.equal(lines.at(-1), 'next: ./harness verify --all');
});

test('doctor checks engine ranges', () => {
  assert.equal(satisfies('24.22.1', '>=24.22.0 <25'), true);
  assert.equal(satisfies('24.12.0', '>=24.22.0 <25'), false);
  assert.equal(satisfies('25.0.0', '>=24.22.0 <25'), false);
  assert.equal(satisfies('24.12.0', '>=24.12.0'), true);
});

test('doctor reports one line per item with a first-line status and next', async () => {
  const { code, lines } = await call(doctor, [], new Map());
  assert.ok(code === 0 || code === 1);
  assert.equal(lines[0], code === 0 ? 'doctor: pass' : 'doctor: fail');
  for (const prefix of ['node: ', 'uv: ', 'git: ', 'base: ', 'solution/ui/node_modules: ', '.harness/node_modules: ', 'discovery: ']) {
    assert.ok(lines.some((line) => line.startsWith(prefix)), `missing ${prefix}`);
  }
  lastIsNext(lines);
});

test('doctor fails deterministically with exit 1 and repairs when node_modules is absent', async () => {
  const root = await gitRepo();
  const { code, lines } = await call(doctor, [], new Map(), root);
  assert.equal(code, 1);
  assert.equal(lines[0], 'doctor: fail');
  for (const folder of ['solution/ui', '.harness']) {
    assert.ok(lines.includes(`${folder}/node_modules: missing; repair: in ${folder}, run npm ci --ignore-scripts`));
  }
  lastIsNext(lines);
});
