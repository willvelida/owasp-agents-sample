import { spawn, spawnSync } from 'node:child_process';
import type { ChildProcess } from 'node:child_process';
import { stat } from 'node:fs/promises';
import { delimiter, join, resolve } from 'node:path';
import type { ExecOptions, ExecResult, Tool } from './contracts.ts';

export const OUTPUT_CAP_BYTES = 256 * 1024;
const SECRET_NAME = /KEY|TOKEN|SECRET|PASSWORD|CONNECTION_STRING|CREDENTIAL/i;
const SHELL_META = /[&|<>^%"\s]/;
// CSI, OSC, and single-character escape sequences.
const ANSI = /\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]/g;
const live = new Set<ChildProcess>();

export const stripAnsi = (text: string): string => text.replace(ANSI, '');

export function redact(text: string, env: Readonly<Record<string, string | undefined>>): string {
  const secrets = Object.entries(env)
    .flatMap(([name, value]) => SECRET_NAME.test(name) && value && value.length >= 8 ? [value] : [])
    .sort((a, b) => b.length - a.length);
  return secrets.reduce((result, secret) => result.split(secret).join('[redacted]'), text);
}

/** Applies overrides without mutating the parent; undefined removes every matching Windows casing. */
export function childEnv(extra: Readonly<Record<string, string | undefined>> = {}): Record<string, string | undefined> {
  const env: Record<string, string | undefined> = { ...process.env };
  for (const [name, value] of Object.entries({ NO_COLOR: '1', FORCE_COLOR: undefined, ...extra })) {
    for (const key of Object.keys(env)) if (process.platform === 'win32' ? key.toLowerCase() === name.toLowerCase() : key === name) delete env[key];
    if (value !== undefined) env[name] = value;
  }
  return env;
}

// Windows can only start npm through cmd.exe, so its arguments are limited to values cmd cannot reinterpret.
export function resolveCommand(argv: readonly string[], platform = process.platform): { file: string; args: string[] } | string {
  const [file, ...args] = argv as [string, ...string[]];
  if (platform !== 'win32' || file !== 'npm') return { file, args };
  const unsafe = args.find((arg) => arg === '' || SHELL_META.test(arg));
  if (unsafe !== undefined) return `refusing to pass '${unsafe}' to npm through cmd.exe`;
  return { file: process.env.ComSpec ?? 'cmd.exe', args: ['/d', '/s', '/c', 'npm', ...args] };
}

function killTree(child: ChildProcess, signal: 'SIGTERM' | 'SIGKILL'): boolean {
  if (child.pid === undefined) return false;
  if (process.platform === 'win32') {
    return spawnSync('taskkill', ['/pid', String(child.pid), '/T', '/F'], { stdio: 'ignore', windowsHide: true }).status === 0;
  }
  try {
    process.kill(-child.pid, signal);
    return true;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ESRCH') throw error;
    return false;
  }
}

/** Kills tracked process trees, including POSIX groups with exited leaders; returns the number signalled. */
export function killAll(): number {
  let count = 0;
  for (const child of live) if (killTree(child, 'SIGKILL')) count++;
  live.clear();
  return count;
}

// captureStderr=false is for callers that parse stdout; git warnings on stderr would otherwise corrupt it.
export function exec(repoRoot: string, argv: readonly [string, ...string[]], options: ExecOptions, captureStderr = true): Promise<ExecResult> {
  const started = Date.now();
  const env = childEnv(options.env);
  let tail = Buffer.alloc(0);
  let truncated = false;
  const finish = (partial: Partial<ExecResult>): ExecResult => ({
    exitCode: null, timedOut: false, spawnError: null, ...partial,
    output: redact(stripAnsi(tail.toString('utf8')), env), truncated, durationMs: Date.now() - started,
  });
  const command = resolveCommand(argv);
  if (typeof command === 'string') return Promise.resolve(finish({ spawnError: command }));

  return new Promise((done) => {
    let timedOut = false;
    let settled = false;
    const child = spawn(command.file, command.args, {
      cwd: resolve(repoRoot, options.cwd), env, shell: false, windowsHide: true,
      detached: process.platform !== 'win32', stdio: ['ignore', 'pipe', captureStderr ? 'pipe' : 'ignore'],
    });
    live.add(child);
    const collect = (chunk: Buffer): void => {
      tail = Buffer.concat([tail, chunk]);
      if (tail.length > OUTPUT_CAP_BYTES) [tail, truncated] = [tail.subarray(tail.length - OUTPUT_CAP_BYTES), true];
    };
    child.stdout?.on('data', collect);
    child.stderr?.on('data', collect);
    const settle = (partial: Partial<ExecResult>): void => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      if (!timedOut || process.platform === 'win32') live.delete(child);
      done(finish({ ...partial, timedOut }));
    };
    const drain = (code: number | null): void => {
      setTimeout(() => {
        if (!settled) [child.stdout?.destroy(), child.stderr?.destroy(), settle({ exitCode: code })];
      }, 5000).unref();
    };
    const timer = setTimeout(() => {
      timedOut = true;
      killTree(child, 'SIGTERM');
      if (process.platform !== 'win32') setTimeout(() => { killTree(child, 'SIGKILL'); live.delete(child); }, 2000);
      drain(null);
    }, options.timeoutMs);
    child.on('exit', (code) => {
      if (code !== 0 || timedOut) return;
      clearTimeout(timer);
      killTree(child, 'SIGKILL');
      drain(code);
    });
    child.on('error', (error) => settle({ spawnError: error.message }));
    child.on('close', (code) => settle({ exitCode: timedOut ? null : code }));
  });
}

export async function which(tool: Tool | string, env: NodeJS.ProcessEnv = process.env): Promise<string | null> {
  const win = process.platform === 'win32';
  const exts = win ? (env.PATHEXT ?? '.COM;.EXE;.BAT;.CMD').toLowerCase().split(';') : [''];
  for (const dir of (env.PATH ?? env.Path ?? '').split(delimiter).filter(Boolean)) {
    for (const ext of exts) {
      const candidate = join(dir, tool + ext);
      const info = await stat(candidate).catch(() => null);
      if (info?.isFile() && (win || (info.mode & 0o111) !== 0)) return candidate;
    }
  }
  return null;
}
