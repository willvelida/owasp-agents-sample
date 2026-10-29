import assert from 'node:assert/strict';
import childProcess from 'node:child_process';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { syncBuiltinESMExports } from 'node:module';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { PassThrough } from 'node:stream';
import { after, before, test } from 'node:test';
import { setTimeout as sleep } from 'node:timers/promises';
import { childEnv, exec, killAll, OUTPUT_CAP_BYTES, redact, resolveCommand, stripAnsi, which } from '../core/process.ts';

const NODE = process.execPath;
let root = '';
before(async () => {
  root = await mkdtemp(join(tmpdir(), 'harness-process-'));
});
after(async () => {
  await rm(root, { recursive: true, force: true });
});

const run = (script: string, timeoutMs = 10_000, env?: Record<string, string | undefined>) =>
  exec(root, [NODE, '-e', script], { cwd: '.', timeoutMs, ...(env ? { env } : {}) });

function alive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

async function gone(pid: number): Promise<boolean> {
  for (let i = 0; i < 30 && alive(pid); i++) await sleep(100);
  return !alive(pid);
}

async function cleanup(pid: number): Promise<void> {
  if (pid > 0 && alive(pid)) {
    process.kill(pid, 'SIGKILL');
    assert.ok(await gone(pid), 'fixture process survived cleanup');
  }
}

const POSIX_ONLY = { skip: process.platform === 'win32' ? 'Windows taskkill cannot recover an exited leader tree' : false };

test('exit codes and output come back', async () => {
  const result = await run("console.log('hello'); console.error('oops'); process.exit(3)");
  assert.equal(result.exitCode, 3);
  assert.equal(result.timedOut, false);
  assert.match(result.output, /hello/);
  assert.match(result.output, /oops/);
});

test('stdout-only mode drops stderr so parsed output stays clean', async () => {
  const result = await exec(root, [NODE, '-e', "console.error('warning: noise'); process.stdout.write('a.txt\\0b.txt\\0')"], { cwd: '.', timeoutMs: 10_000 }, false);
  assert.equal(result.output, 'a.txt\0b.txt\0');
});

test('a timeout kills the child and its grandchild', async () => {
  const script = [
    "const { spawn } = require('node:child_process');",
    "const g = spawn(process.execPath, ['-e', 'setInterval(() => {}, 1000)'], { stdio: 'ignore' });",
    "console.log('GRANDCHILD ' + g.pid);",
    'setInterval(() => {}, 1000);',
  ].join('\n');
  const result = await run(script, 1500);
  assert.equal(result.timedOut, true);
  assert.equal(result.exitCode, null);
  const pid = Number(/GRANDCHILD (\d+)/.exec(result.output)?.[1]);
  assert.ok(pid > 0, `no grandchild pid in: ${result.output}`);
  assert.ok(await gone(pid), 'grandchild still running');
});

for (const earlyExit of [false, true]) {
  test(`POSIX timeout kills a SIGTERM-resistant descendant after its leader ${earlyExit ? 'already exited' : 'was killed'}`, POSIX_ONLY, async () => {
    const descendant = "process.on('SIGTERM', () => {}); process.send('ready'); setInterval(() => {}, 1000)";
    const script = `
      const { spawn } = require('node:child_process');
      const g = spawn(process.execPath, ['-e', ${JSON.stringify(descendant)}], { stdio: ['ignore', ${earlyExit ? "'inherit'" : "'ignore'"}, 'ignore', 'ipc'] });
      g.once('message', () => { console.log('GRANDCHILD ' + g.pid); ${earlyExit ? 'process.exit(1)' : 'setInterval(() => {}, 1000)'}; });
    `;
    let pid = 0;
    try {
      const result = await run(script, 1500);
      pid = Number(/GRANDCHILD (\d+)/.exec(result.output)?.[1]);
      assert.ok(pid > 0, 'descendant did not start');
      assert.equal(result.timedOut, true);
      assert.equal(result.exitCode, null);
      assert.ok(await gone(pid), 'descendant survived escalation after leader exit');
    } finally {
      await cleanup(pid);
    }
  });
}

test('POSIX killAll kills a descendant after its leader exited', POSIX_ONLY, async () => {
  const pidFile = join(root, 'orphan-pids.json');
  const script = `
    const { spawn } = require('node:child_process');
    const g = spawn(process.execPath, ['-e', "process.on('SIGTERM', () => {}); process.send('ready'); setInterval(() => {}, 1000)"], { stdio: ['ignore', 'inherit', 'inherit', 'ipc'] });
    g.once('message', () => {
      require('node:fs').writeFileSync(${JSON.stringify(pidFile)}, JSON.stringify([process.pid, g.pid]));
      process.exit(1);
    });
  `;
  const pending = run(script, 60_000);
  let leader = 0;
  let descendant = 0;
  try {
    for (let i = 0; i < 50 && !descendant; i++) {
      await sleep(100);
      [leader, descendant] = JSON.parse(await readFile(pidFile, 'utf8').catch(() => '[0,0]')) as [number, number];
    }
    assert.ok(descendant > 0, 'descendant did not start');
    assert.ok(await gone(leader), 'leader did not exit');
    assert.ok(alive(descendant), 'descendant did not outlive the leader');
    assert.equal(killAll(), 1);
    assert.equal((await pending).timedOut, false);
    assert.ok(await gone(descendant), 'descendant survived killAll');
  } finally {
    killAll();
    await cleanup(descendant);
    await pending;
  }
});

test('a clean leader exit is not a timeout when a descendant holds stdout', async () => {
  const script = `
    const { spawn } = require('node:child_process');
    const g = spawn(process.execPath, ['-e', "process.send('ready'); setTimeout(() => process.exit(0), 4000)"], { stdio: ['ignore', 'inherit', 'inherit', 'ipc'] });
    g.once('message', () => { console.log('GRANDCHILD ' + g.pid); process.exit(0); });
  `;
  let pid = 0;
  try {
    const result = await run(script, 1500);
    pid = Number(/GRANDCHILD (\d+)/.exec(result.output)?.[1]);
    assert.ok(pid > 0, 'descendant did not start');
    assert.equal(result.exitCode, 0);
    assert.equal(result.timedOut, false);
  } finally {
    await cleanup(pid);
  }
});

test('POSIX group escalation and killAll still signal after leader exit and pipe closure (simulated)', async (t) => {
  const platform = Object.getOwnPropertyDescriptor(process, 'platform')!;
  const signals: [number, NodeJS.Signals | number | undefined][] = [];
  let child = new childProcess.ChildProcess();
  Object.defineProperty(child, 'pid', { value: 12345 });
  t.mock.timers.enable({ apis: ['setTimeout'] });
  t.mock.method(childProcess, 'spawn', () => child);
  t.mock.method(process, 'kill', (pid: number, signal?: NodeJS.Signals | number) => {
    signals.push([pid, signal]);
    return true;
  });
  Object.defineProperty(process, 'platform', { value: 'linux' });
  syncBuiltinESMExports();
  try {
    const pending = run('', 100);
    t.mock.timers.tick(100);
    Object.defineProperty(child, 'signalCode', { value: 'SIGTERM' });
    child.emit('exit', null, 'SIGTERM');
    child.emit('close', null, 'SIGTERM');
    assert.equal((await pending).timedOut, true);
    assert.deepEqual(signals, [[-12345, 'SIGTERM']]);
    t.mock.timers.tick(2000);
    assert.deepEqual(signals, [[-12345, 'SIGTERM'], [-12345, 'SIGKILL']]);

    child = new childProcess.ChildProcess();
    Object.defineProperty(child, 'pid', { value: 12346 });
    const interrupted = run('', 100);
    t.mock.timers.tick(100);
    Object.defineProperty(child, 'exitCode', { value: 1 });
    child.emit('exit', 1, null);
    child.emit('close', 1, null);
    await interrupted;
    assert.equal(killAll(), 1);
    assert.deepEqual(signals.at(-1), [-12346, 'SIGKILL']);

    child = new childProcess.ChildProcess();
    const stdout = new PassThrough();
    Object.defineProperties(child, { pid: { value: 12347 }, stdout: { value: stdout }, exitCode: { value: 0 } });
    const clean = run('', 100);
    child.emit('exit', 0, null);
    let completed = false;
    void clean.then(() => { completed = true; });
    t.mock.timers.tick(100);
    await Promise.resolve();
    assert.equal(completed, false, 'capture should wait for inherited pipes, not the step deadline');
    t.mock.timers.tick(4900);
    assert.equal((await clean).exitCode, 0);
    assert.equal((await clean).timedOut, false);
    assert.equal(stdout.destroyed, true);
    assert.deepEqual(signals.filter(([pid]) => pid === -12347), [[-12347, 'SIGKILL']]);
  } finally {
    killAll();
    Object.defineProperty(process, 'platform', platform);
    t.mock.restoreAll();
    t.mock.timers.reset();
    syncBuiltinESMExports();
  }
});

test('output is capped to the last 256 KiB', async () => {
  const result = await run(`process.stdout.write('a'.repeat(${OUTPUT_CAP_BYTES}) + 'b'.repeat(4096))`);
  assert.equal(result.truncated, true);
  assert.equal(result.output.length, OUTPUT_CAP_BYTES);
  assert.ok(result.output.endsWith('b'.repeat(4096)));
});

test('ANSI escape sequences are stripped', async () => {
  const result = await run("const e = String.fromCharCode(27); process.stdout.write(e + '[31mred' + e + '[0m plain' + e + ']0;title' + String.fromCharCode(7))");
  assert.equal(result.output, 'red plain');
  assert.equal(stripAnsi('\x1b[1;32mok\x1b[0m'), 'ok');
});

test('secret-named variable values are redacted, short ones and other names are not', async () => {
  const result = await run('console.log(process.env.MY_API_KEY, process.env.PLAIN_VALUE)', 10_000, {
    MY_API_KEY: 'supersecretvalue123',
    PLAIN_VALUE: 'supersecretvalue123-plain',
  });
  assert.doesNotMatch(result.output, /supersecretvalue123 /);
  assert.match(result.output, /^\[redacted\] \[redacted\]-plain/);
  assert.equal(redact('token abc and xyz', { SHORT_TOKEN: 'abc', DB_PASSWORD: 'longer-password' }), 'token abc and xyz');
});

test('the child gets NO_COLOR, loses FORCE_COLOR, and env undefined removes a variable', async () => {
  process.env.FORCE_COLOR = '1';
  process.env.HARNESS_TEST_REMOVE = 'present';
  try {
    const result = await run("console.log([process.env.NO_COLOR, process.env.FORCE_COLOR, process.env.HARNESS_TEST_REMOVE].join(','))", 10_000, {
      HARNESS_TEST_REMOVE: undefined,
    });
    assert.equal(result.output.trim(), '1,,');
  } finally {
    delete process.env.FORCE_COLOR;
    delete process.env.HARNESS_TEST_REMOVE;
  }
});

test('undefined env overrides remove mixed-case RUN_INTEGRATION on Windows', () => {
  const platform = Object.getOwnPropertyDescriptor(process, 'platform')!;
  const name = 'rUn_InTeGrAtIoN';
  const previous = process.env[name];
  try {
    process.env[name] = '1';
    Object.defineProperty(process, 'platform', { value: 'win32' });
    const env = childEnv({ RUN_INTEGRATION: undefined });
    assert.ok(!Object.keys(env).some((key) => key.toLowerCase() === 'run_integration'));
    assert.equal(process.env[name], '1', 'parent environment must not change');
    assert.equal(childEnv({ RUN_INTEGRATION: '0' }).RUN_INTEGRATION, '0');
    Object.defineProperty(process, 'platform', { value: 'linux' });
    assert.equal(childEnv({ RUN_INTEGRATION: undefined })[name], '1', 'POSIX names stay case-sensitive');
  } finally {
    Object.defineProperty(process, 'platform', platform);
    if (previous === undefined) delete process.env[name];
    else process.env[name] = previous;
  }
});
test('a missing executable is a spawn error', async () => {
  const result = await exec(root, ['harness-no-such-tool-xyz'], { cwd: '.', timeoutMs: 5000 });
  assert.notEqual(result.spawnError, null);
  assert.equal(result.exitCode, null);
});

test('npm on Windows goes through cmd.exe and rejects shell metacharacters', () => {
  assert.deepEqual(resolveCommand(['npm', 'run', 'lint'], 'linux'), { file: 'npm', args: ['run', 'lint'] });
  const routed = resolveCommand(['npm', 'run', 'lint'], 'win32');
  assert.ok(typeof routed !== 'string');
  assert.deepEqual(routed.args, ['/d', '/s', '/c', 'npm', 'run', 'lint']);
  for (const bad of ['a&b', 'a|b', 'a<b', 'a>b', 'a^b', '%PATH%', 'a"b', 'a b', '']) {
    assert.equal(typeof resolveCommand(['npm', 'run', bad], 'win32'), 'string', `accepted '${bad}'`);
  }
  assert.deepEqual(resolveCommand(['uv', 'a&b'], 'win32'), { file: 'uv', args: ['a&b'] });
});

test('killAll stops every live child, as the interrupt handler does', async () => {
  const pidFile = join(root, 'pid.txt');
  const script = `require('node:fs').writeFileSync(${JSON.stringify(pidFile)}, String(process.pid)); setInterval(() => {}, 1000);`;
  const pending = run(script, 60_000);
  let pid = 0;
  for (let i = 0; i < 50 && pid === 0; i++) {
    await sleep(100);
    pid = Number(await readFile(pidFile, 'utf8').catch(() => '0'));
  }
  assert.ok(pid > 0, 'child never started');
  assert.equal(killAll(), 1);
  const result = await pending;
  assert.notEqual(result.exitCode, 0);
  assert.ok(await gone(pid), 'child still running');
  assert.equal(killAll(), 0);
});

test('which finds tools on PATH without a shell', async () => {
  assert.notEqual(await which('node'), null);
  assert.equal(await which('harness-no-such-tool-xyz'), null);
});
