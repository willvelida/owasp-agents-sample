import assert from 'node:assert/strict';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { after, test } from 'node:test';
import { main } from '../core/cli.ts';

const dirs: string[] = [];
after(async () => {
  for (const dir of dirs) await rm(dir, { recursive: true, force: true });
});

const HOME = "export default { description: 'orientation', usage: './harness home', run: async (ctx) => { ctx.write('home: pass'); ctx.write('next: ./harness verify'); return 0; } };\n";
const THROWS = "export default { description: 'broken', usage: './harness boom', run: async () => { throw new Error('kaput'); } };\n";

async function repoWith(files: Record<string, string>): Promise<string> {
  const root = await mkdtemp(join(tmpdir(), 'harness-cli-'));
  dirs.push(root);
  await writeFile(join(root, 'package.json'), '{"type":"module"}');
  for (const [name, content] of Object.entries(files)) {
    await mkdir(join(root, '.harness', name, '..'), { recursive: true });
    await writeFile(join(root, '.harness', name), content);
  }
  return root;
}

async function call(repoRoot: string, argv: string[]): Promise<{ code: number; lines: string[] }> {
  const lines: string[] = [];
  const code = await main({ repoRoot, argv, write: (line) => lines.push(line) });
  return { code, lines };
}

test('no command runs home', async () => {
  const root = await repoWith({ 'commands/home.ts': HOME });
  assert.deepEqual(await call(root, []), { code: 0, lines: ['home: pass', 'next: ./harness verify'] });
});

test('--help and help list the commands', async () => {
  const root = await repoWith({ 'commands/home.ts': HOME });
  for (const flag of ['--help', 'help']) {
    const { code, lines } = await call(root, [flag]);
    assert.equal(code, 0);
    assert.equal(lines[0], 'help: pass');
    assert.ok(lines.some((line) => line.startsWith('  home: orientation')));
    assert.match(lines.at(-1) ?? '', /^next: /);
  }
});

test('an unknown command or top-level flag exits 2 with a next step', async () => {
  const root = await repoWith({ 'commands/home.ts': HOME });
  assert.deepEqual(await call(root, ['nope']), { code: 2, lines: ['harness: error', "error: unknown command 'nope'", 'next: ./harness --help'] });
  assert.equal((await call(root, ['--bogus'])).code, 2);
});

test('an invalid sensor stops every command and names the file', async () => {
  const root = await repoWith({ 'commands/home.ts': HOME, 'sensors/bad.ts': "export default { description: 'x' };\n" });
  for (const argv of [[], ['help']]) {
    const { code, lines } = await call(root, argv);
    assert.equal(code, 2);
    assert.match(lines[1] ?? '', /^error: invalid sensor bad\.ts: /);
    assert.equal(lines.at(-1), 'next: fix or remove .harness/sensors/bad.ts');
  }
});

test('a command that throws exits 2', async () => {
  const root = await repoWith({ 'commands/boom.ts': THROWS });
  const { code, lines } = await call(root, ['boom']);
  assert.equal(code, 2);
  assert.deepEqual(lines, ['boom: error', 'error: boom failed: kaput', 'next: fix .harness/commands/boom.ts']);
});
