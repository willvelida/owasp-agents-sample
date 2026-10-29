import assert from 'node:assert/strict';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { after, test } from 'node:test';
import { DiscoveryError, discoverCommands, discoverSensors } from '../core/discovery.ts';

const dirs: string[] = [];
after(async () => {
  for (const dir of dirs) await rm(dir, { recursive: true, force: true });
});

const VALID_SENSOR = `export default {
  description: 'a sensor',
  paths: ['solution/', 'azure.yaml'],
  exclude: ['solution/docs/'],
  requires: ['uv'],
  rules: [{ id: 'rule-one', expectation: 'it holds', repair: 'fix it' }],
  run: async () => ({ checked: 1, findings: [], problems: [], notes: [] }),
};
`;

async function folder(files: Record<string, string>): Promise<string> {
  const dir = await mkdtemp(join(tmpdir(), 'harness-discovery-'));
  dirs.push(dir);
  await writeFile(join(dir, 'package.json'), '{"type":"module"}');
  for (const [name, content] of Object.entries(files)) {
    await mkdir(join(dir, name, '..'), { recursive: true });
    await writeFile(join(dir, name), content);
  }
  return dir;
}

async function rejects(files: Record<string, string>, pattern: RegExp): Promise<void> {
  const dir = await folder(files);
  await assert.rejects(discoverSensors(dir), (error: unknown) => {
    assert.ok(error instanceof DiscoveryError);
    assert.match(error.message, pattern);
    return true;
  });
}

test('a valid sensor is named from its file; nested folders and test files are ignored', async () => {
  const dir = await folder({ 'python-x.ts': VALID_SENSOR, 'nested/inner.ts': VALID_SENSOR, 'python-x.test.ts': 'throw new Error()' });
  const sensors = await discoverSensors(dir);
  assert.deepEqual([...sensors.keys()], ['python-x']);
  assert.deepEqual(sensors.get('python-x')?.paths, ['solution/', 'azure.yaml']);
});

test('modules load in name order', async () => {
  const dir = await folder({ 'zeta.ts': VALID_SENSOR, 'alpha.ts': VALID_SENSOR, 'mid.ts': VALID_SENSOR });
  assert.deepEqual([...(await discoverSensors(dir)).keys()], ['alpha', 'mid', 'zeta']);
});

test('a missing folder discovers nothing', async () => {
  assert.equal((await discoverSensors(join(tmpdir(), 'harness-does-not-exist-0'))).size, 0);
});

test('an unknown key is rejected', async () => {
  await rejects({ 'extra.ts': VALID_SENSOR.replace("description: 'a sensor',", "description: 'a sensor', name: 'x',") }, /invalid sensor extra\.ts: unknown key 'name'/);
});

test('a duplicate rule id is rejected', async () => {
  const duplicate = VALID_SENSOR.replace("rules: [{ id: 'rule-one', expectation: 'it holds', repair: 'fix it' }]",
    "rules: [{ id: 'rule-one', expectation: 'a', repair: 'b' }, { id: 'rule-one', expectation: 'c', repair: 'd' }]");
  await rejects({ 'dup.ts': duplicate }, /duplicate rule id 'rule-one'/);
});

for (const bad of ['../outside/', '/abs/', 'C:/drive/', 'back\\\\slash/']) {
  test(`a bad path '${bad}' is rejected`, async () => {
    await rejects({ 'bad-path.ts': VALID_SENSOR.replace("'azure.yaml'", `'${bad}'`) }, /invalid sensor bad-path\.ts: path/);
  });
}

test('a bad file name is rejected', async () => {
  await rejects({ 'Bad_Name.ts': VALID_SENSOR }, /invalid sensor Bad_Name\.ts: file name/);
});

test('a missing default export is rejected', async () => {
  await rejects({ 'no-default.ts': 'export const sensor = 1;\n' }, /invalid sensor no-default\.ts: missing default export/);
});

test('an unknown tool, empty rules, and a non-function run are rejected', async () => {
  await rejects({ 'tool.ts': VALID_SENSOR.replace("requires: ['uv']", "requires: ['node']") }, /'requires' may only contain/);
  await rejects({ 'rules.ts': VALID_SENSOR.replace(/rules: \[.*\],/, 'rules: [],') }, /'rules' must be a non-empty array/);
  await rejects({ 'run.ts': VALID_SENSOR.replace(/run: async .*,\n/, 'run: 1,\n') }, /'run' must be a function/);
});

test('commands are validated against the command contract', async () => {
  const good = "export default { description: 'd', usage: './harness x', run: async () => 0 };\n";
  const dir = await folder({ 'x.ts': good });
  assert.deepEqual([...(await discoverCommands(dir)).keys()], ['x']);
  const bad = await folder({ 'y.ts': "export default { description: 'd', run: async () => 0 };\n" });
  await assert.rejects(discoverCommands(bad), /invalid command y\.ts: missing key 'usage'/);
});
