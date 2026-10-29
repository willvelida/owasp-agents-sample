import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtemp, rm, unlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { after, test } from 'node:test';
import { applies, describeChanges, detectChanges } from '../core/changes.ts';
import { exec } from '../core/process.ts';

const dirs: string[] = [];
after(async () => {
  for (const dir of dirs) await rm(dir, { recursive: true, force: true });
});

const IDENTITY = ['-c', 'user.name=harness-test', '-c', 'user.email=harness-test@example.invalid', '-c', 'commit.gpgsign=false'];

function git(cwd: string, ...args: string[]): void {
  const result = spawnSync('git', [...IDENTITY, ...args], { cwd, encoding: 'utf8' });
  assert.equal(result.status, 0, `git ${args.join(' ')}: ${result.stderr}`);
}

async function repo(branch = 'main'): Promise<string> {
  const dir = await mkdtemp(join(tmpdir(), 'harness-changes-'));
  dirs.push(dir);
  git(dir, 'init', '-q', '-b', branch);
  for (const name of ['a.txt', 'b.txt', 'c.txt']) await writeFile(join(dir, name), `${name}\n`);
  await writeFile(join(dir, '.gitignore'), 'ignored.txt\n');
  git(dir, 'add', '.');
  git(dir, 'commit', '-q', '-m', 'base');
  return dir;
}

const execIn = (dir: string) => (argv: readonly [string, ...string[]], options: { cwd: string; timeoutMs: number }, captureStderr?: boolean) =>
  exec(dir, argv, options, captureStderr);

test('applies matches directory prefixes and exact files, minus excludes', () => {
  const paths = ['solution/', 'ruff.toml'];
  assert.equal(applies(null, paths), true);
  assert.equal(applies([], paths), false);
  assert.equal(applies(['solution/src/app.py'], paths), true);
  assert.equal(applies(['ruff.toml'], paths), true);
  assert.equal(applies(['ruff.toml.bak', 'solutions/x'], paths), false);
  assert.equal(applies(['solution/ui/a.ts'], paths, ['solution/ui/']), false);
  assert.equal(applies(['solution/ui/a.ts', 'solution/x.py'], paths, ['solution/ui/']), true);
});

test('committed, staged, unstaged, deleted, and untracked files are all detected against main', async () => {
  const dir = await repo();
  git(dir, 'checkout', '-q', '-b', 'feature');
  await writeFile(join(dir, 'a.txt'), 'committed change\n');
  git(dir, 'commit', '-q', '-am', 'feature work');
  await writeFile(join(dir, 'd.txt'), 'staged\n');
  git(dir, 'add', 'd.txt');
  await writeFile(join(dir, 'b.txt'), 'unstaged\n');
  await unlink(join(dir, 'c.txt'));
  await writeFile(join(dir, 'e.txt'), 'untracked\n');
  await writeFile(join(dir, 'ignored.txt'), 'ignored\n');

  const result = await detectChanges(execIn(dir));
  assert.ok(result.ok);
  assert.equal(result.changes.base, 'main');
  assert.deepEqual(result.changes.files, ['a.txt', 'b.txt', 'c.txt', 'd.txt', 'e.txt']);
  assert.match(describeChanges(result.changes)[0] ?? '', /^base: main \(merge-base [0-9a-f]{7}\)$/);
  assert.equal(describeChanges(result.changes)[1], 'changed: 5 files');
});

test('--base overrides resolution, and an unknown ref is a usage error', async () => {
  const dir = await repo();
  const good = await detectChanges(execIn(dir), 'HEAD');
  assert.ok(good.ok);
  assert.equal(good.changes.base, 'HEAD');
  assert.deepEqual(good.changes.files, []);
  const bad = await detectChanges(execIn(dir), 'no-such-ref');
  assert.ok(!bad.ok);
  assert.equal(bad.usage, true);
});

test('no base ref means every sensor applies', async () => {
  const dir = await repo('trunk');
  const result = await detectChanges(execIn(dir));
  assert.ok(result.ok);
  assert.equal(result.changes.files, null);
  assert.match(describeChanges(result.changes)[0] ?? '', /^base: none \(no upstream\/main, origin\/main, main ref\); running all sensors$/);
});

test('outside a work tree is an error pointing at --all', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'harness-notrepo-'));
  dirs.push(dir);
  const result = await detectChanges(execIn(dir));
  assert.ok(!result.ok);
  assert.equal(result.usage, false);
  assert.equal(result.next, './harness verify --all');
});
