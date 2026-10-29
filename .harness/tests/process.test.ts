import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { after, before, test } from 'node:test';
import { setTimeout as sleep } from 'node:timers/promises';
import { exec, killAll, OUTPUT_CAP_BYTES, redact, resolveCommand, stripAnsi, which } from '../core/process.ts';

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
