import assert from 'node:assert/strict';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { after, test } from 'node:test';
import type { SensorContext } from '../core/contracts.ts';
import infraGuard from '../sensors/infra-guard.ts';

const dirs: string[] = [];
after(async () => {
  for (const dir of dirs) await rm(dir, { recursive: true, force: true });
});

function ctx(repoRoot: string): SensorContext {
  return {
    repoRoot,
    changedFiles: null,
    exec: async () => assert.fail('infra-guard must not run subprocesses'),
    which: async () => null,
  };
}

async function fixture(files: Record<string, string>): Promise<string> {
  const root = await mkdtemp(join(tmpdir(), 'harness-infra-'));
  dirs.push(root);
  for (const [name, content] of Object.entries(files)) {
    await mkdir(join(root, name, '..'), { recursive: true });
    await writeFile(join(root, name), content);
  }
  return root;
}

test('a clean tree passes and counts every scanned file', async () => {
  const root = await fixture({
    'solution/infra/main.bicep': "param location string = 'eastus'\n",
    'solution/infra/modules/app.bicep': 'resource app {}\n',
    'solution/azure.yaml': 'name: biotrackr\n',
  });
  assert.deepEqual(await infraGuard.run(ctx(root)), { checked: 3, findings: [], problems: [], notes: [] });
});

test('each hit is a finding with path:line, case-insensitive, recursive', async () => {
  const root = await fixture({
    'solution/infra/main.bicep': "param a string\nvar issuer = 'LOCAL-Issuer'\n",
    'solution/infra/modules/app.bicep': "env: [\n  { name: 'ENABLE_DEVUI', value: 'true' }\n]\n",
    'solution/azure.yaml': 'hooks:\n  postprovision: use local_issuer\n',
  });
  const result = await infraGuard.run(ctx(root));
  assert.deepEqual(
    result.findings.map((finding) => [finding.rule, finding.location]),
    [
      ['no-local-issuer', 'solution/azure.yaml:2'],
      ['no-local-issuer', 'solution/infra/main.bicep:2'],
      ['no-devui', 'solution/infra/modules/app.bicep:2'],
    ],
  );
  assert.equal(result.checked, 3);
});

test('.env, .env.*, and *.env files are never read', async () => {
  const root = await fixture({
    'solution/infra/main.bicep': 'resource x {}\n',
    'solution/infra/.env': 'LOCAL_ISSUER_SECRET=devui\n',
    'solution/infra/.env.local': 'local_issuer=devui\n',
    'solution/infra/.env.production': 'local_issuer=devui\n',
    'solution/infra/params/.env.test': 'local_issuer=devui\n',
    'solution/infra/params/prod.env': 'local_issuer=1\n',
    'solution/azure.yaml': 'name: x\n',
  });
  const result = await infraGuard.run(ctx(root));
  assert.deepEqual(result.findings, []);
  assert.equal(result.checked, 2);
});

test('a missing infra folder or azure.yaml is a problem', async () => {
  const root = await fixture({ 'solution/README.md': 'x\n' });
  const result = await infraGuard.run(ctx(root));
  assert.equal(result.problems.length, 2);
  assert.equal(result.checked, 0);
});
