import assert from 'node:assert/strict';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { after, test } from 'node:test';
import type { SensorContext } from '../core/contracts.ts';
import ui, { nodeInRange } from '../sensors/ui.ts';

const dirs: string[] = [];
after(async () => {
  for (const dir of dirs) await rm(dir, { recursive: true, force: true });
});

test('nodeInRange reads the >=A.B.C <D shape and rejects anything else', () => {
  assert.equal(nodeInRange('24.22.1', '>=24.22.0 <25'), true);
  assert.equal(nodeInRange('24.22.0', '>=24.22.0 <25'), true);
  assert.equal(nodeInRange('24.21.9', '>=24.22.0 <25'), false);
  assert.equal(nodeInRange('25.0.0', '>=24.22.0 <25'), false);
  assert.equal(nodeInRange('24.22.1', '^24.22.0'), null);
});

test('missing node_modules or an unparseable range is a problem, and no npm step runs', async () => {
  const root = await mkdtemp(join(tmpdir(), 'harness-ui-'));
  dirs.push(root);
  await mkdir(join(root, 'solution', 'ui'), { recursive: true });
  await writeFile(join(root, 'solution', 'ui', 'package.json'), JSON.stringify({ engines: { node: '^24' } }));
  const ctx: SensorContext = { repoRoot: root, changedFiles: null, exec: async () => assert.fail('no npm step may run'), which: async () => null };
  const result = await ui.run(ctx);
  assert.equal(result.checked, 0);
  assert.deepEqual(result.problems.map((problem) => problem.message.split(' ')[0]), ['cannot', 'solution/ui/node_modules']);
  assert.equal(result.problems[1]?.repair, 'cd solution/ui && npm ci --ignore-scripts');
});
