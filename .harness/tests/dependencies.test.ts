import assert from 'node:assert/strict';
import { readdir, readFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { test } from 'node:test';

// NFR-001: the harness has no runtime dependencies, exact dev pins, a committed lockfile, and the UI's npm settings.
const HARNESS = resolve(import.meta.dirname, '..');
const REPO = resolve(HARNESS, '..');
const json = async (path: string) => JSON.parse(await readFile(path, 'utf8')) as Record<string, unknown>;
const lines = async (path: string) => (await readFile(path, 'utf8')).split(/\r?\n/).map((line) => line.trim()).filter(Boolean);

test('package.json has no dependencies key and exact dev pins', async () => {
  const manifest = await json(join(HARNESS, 'package.json'));
  assert.equal('dependencies' in manifest, false);
  const dev = manifest.devDependencies as Record<string, string>;
  assert.deepEqual(Object.keys(dev).sort(), ['@types/node', 'typescript']);
  for (const [name, version] of Object.entries(dev)) assert.match(version, /^\d+\.\d+\.\d+$/, `${name} must be exact`);
});

test('package-lock.json is committed and pins the same dev versions', async () => {
  const manifest = await json(join(HARNESS, 'package.json'));
  const lock = await json(join(HARNESS, 'package-lock.json'));
  const root = (lock.packages as Record<string, { devDependencies?: Record<string, string>; dependencies?: unknown }>)[''];
  assert.deepEqual(root?.devDependencies, manifest.devDependencies);
  assert.equal(root?.dependencies, undefined);
  const packages = lock.packages as Record<string, { version?: string }>;
  for (const [name, version] of Object.entries(manifest.devDependencies as Record<string, string>)) {
    assert.equal(packages[`node_modules/${name}`]?.version, version);
  }
});

test('.npmrc matches solution/ui/.npmrc', async () => {
  assert.deepEqual(await lines(join(HARNESS, '.npmrc')), await lines(join(REPO, 'solution', 'ui', '.npmrc')));
});

test('every import under core/, commands/, and sensors/ is node: or relative', async () => {
  const specifier = /(?:\bfrom\s+|\bimport\s*\(\s*|^\s*import\s+)['"]([^'"]+)['"]/gm;
  let files = 0;
  for (const folder of ['core', 'commands', 'sensors']) {
    for (const name of await readdir(join(HARNESS, folder))) {
      if (!name.endsWith('.ts')) continue;
      files++;
      const source = await readFile(join(HARNESS, folder, name), 'utf8');
      for (const match of source.matchAll(specifier)) {
        const spec = match[1] ?? '';
        assert.ok(spec.startsWith('node:') || spec.startsWith('.'), `${folder}/${name} imports '${spec}'`);
      }
    }
  }
  assert.ok(files >= 15, `expected the core, commands, and sensors; found ${files} files`);
});
