import type { ExecOptions, ExecResult } from './contracts.ts';

export type Exec = (argv: readonly [string, ...string[]], options: ExecOptions, captureStderr?: boolean) => Promise<ExecResult>;
export const BASE_CANDIDATES = ['upstream/main', 'origin/main', 'main'] as const;

// files is null when no base resolves; every sensor then applies.
export interface ChangeSet { readonly base: string | null; readonly mergeBase: string | null; readonly files: readonly string[] | null; readonly reason: string | null }
export type ChangeResult =
  | { readonly ok: true; readonly changes: ChangeSet }
  | { readonly ok: false; readonly usage: boolean; readonly message: string; readonly next: string };

const matches = (path: string, pattern: string): boolean => (pattern.endsWith('/') ? path.startsWith(pattern) : path === pattern);

export function applies(files: readonly string[] | null, paths: readonly string[], exclude: readonly string[] = []): boolean {
  return files === null || files.some((file) => paths.some((p) => matches(file, p)) && !exclude.some((p) => matches(file, p)));
}

// Never fetches: a stale base gives a larger change set, not a smaller one.
export async function detectChanges(exec: Exec, baseOverride?: string): Promise<ChangeResult> {
  const git = (...args: string[]): Promise<ExecResult> => exec(['git', '-c', 'core.quotepath=false', ...args], { cwd: '.', timeoutMs: 30_000 }, false);
  const gitError = (message: string): ChangeResult => ({ ok: false, usage: false, message, next: './harness verify --all' });
  const inside = await git('rev-parse', '--is-inside-work-tree');
  if (inside.spawnError !== null) return gitError(`git not found (${inside.spawnError})`);
  if (inside.exitCode !== 0 || inside.output.trim() !== 'true') return gitError('not inside a git work tree');

  const resolves = async (ref: string): Promise<boolean> => (await git('rev-parse', '--verify', '--quiet', `${ref}^{commit}`)).exitCode === 0;
  let base: string | null = null;
  for (const candidate of baseOverride === undefined ? BASE_CANDIDATES : [baseOverride]) {
    if (await resolves(candidate)) {
      base = candidate;
      break;
    }
  }
  if (baseOverride !== undefined && base === null) {
    return { ok: false, usage: true, message: `--base ${baseOverride} does not resolve to a commit`, next: './harness --help' };
  }
  const none = (reason: string): ChangeResult => ({ ok: true, changes: { base, mergeBase: null, files: null, reason } });
  if (base === null) return none(`no ${BASE_CANDIDATES.join(', ')} ref`);
  const mergeBase = await git('merge-base', base, 'HEAD');
  if (mergeBase.exitCode !== 0) return none(`no merge-base with ${base}; the clone may be shallow`);
  const point = mergeBase.output.trim();

  const results = [await git('diff', '--name-only', '--no-renames', '-z', point), await git('ls-files', '--others', '--exclude-standard', '-z')];
  for (const result of results) {
    if (result.exitCode !== 0) return gitError(`git exited with ${result.exitCode} while listing changes`);
    if (result.truncated) return none('change list too large to read');
  }
  const files = [...new Set(results.flatMap((result) => result.output.split('\0').filter(Boolean)))].sort();
  return { ok: true, changes: { base, mergeBase: point, files, reason: null } };
}

export function describeChanges(changes: ChangeSet): string[] {
  if (changes.files === null) return [`base: none (${changes.reason ?? 'unknown'}); running all sensors`];
  const count = changes.files.length;
  return [`base: ${changes.base} (merge-base ${(changes.mergeBase ?? '').slice(0, 7)})`, `changed: ${count} ${count === 1 ? 'file' : 'files'}`];
}
