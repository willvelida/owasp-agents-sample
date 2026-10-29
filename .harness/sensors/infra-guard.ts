// Ports the infra-guard job in .github/workflows/ci.yml (grep -rniE) to node:fs, so it also runs where grep is missing.
import { readdir, readFile, stat } from 'node:fs/promises';
import { basename, join, relative } from 'node:path';
import { defineSensor } from '../core/contracts.ts';
import type { Finding, Problem } from '../core/contracts.ts';

const INFRA = 'solution/infra';
const AZURE_YAML = 'solution/azure.yaml';
const PATTERNS = [
  { rule: 'no-local-issuer', pattern: /local[_-]issuer/i },
  { rule: 'no-devui', pattern: /devui/i },
] as const;

// The guard never reads secrets: .env, .env.*, and *.env files are skipped.
const isEnvFile = (path: string): boolean => {
  const name = basename(path);
  return name === '.env' || name.startsWith('.env.') || name.endsWith('.env');
};

export default defineSensor({
  description: `CI infra-guard job: no local issuer or DevUI reference in ${INFRA}/ or ${AZURE_YAML}.`,
  paths: [`${INFRA}/`, AZURE_YAML],
  requires: [],
  rules: [
    {
      id: 'no-local-issuer',
      expectation: `nothing under ${INFRA}/ or in ${AZURE_YAML} matches /local[_-]issuer/i`,
      repair: 'remove the reference; the local issuer is a stage-only simulator that must never reach Azure (docs/adr/0018-offline-identity-simulator.md)',
    },
    {
      id: 'no-devui',
      expectation: `nothing under ${INFRA}/ or in ${AZURE_YAML} matches /devui/i`,
      repair: 'remove the reference; DevUI is a local debugging UI with no auth and must never be deployed (see the infra-guard job in .github/workflows/ci.yml)',
    },
  ],
  async run(ctx) {
    const problems: Problem[] = [];
    const files: string[] = [];
    const infraEntries = await readdir(join(ctx.repoRoot, INFRA), { recursive: true, withFileTypes: true }).catch(() => null);
    if (infraEntries === null) problems.push({ message: `${INFRA}/ is missing`, repair: `restore ${INFRA}/` });
    for (const entry of infraEntries ?? []) {
      if (entry.isFile()) files.push(join(entry.parentPath, entry.name));
    }
    if ((await stat(join(ctx.repoRoot, AZURE_YAML)).catch(() => null))?.isFile()) files.push(join(ctx.repoRoot, AZURE_YAML));
    else problems.push({ message: `${AZURE_YAML} is missing`, repair: `restore ${AZURE_YAML}` });

    const findings: Finding[] = [];
    let checked = 0;
    for (const file of files.filter((path) => !isEnvFile(path)).sort()) {
      checked++;
      const location = relative(ctx.repoRoot, file).replaceAll('\\', '/');
      const lines = (await readFile(file, 'utf8')).split(/\r?\n/);
      lines.forEach((line, index) => {
        for (const { rule, pattern } of PATTERNS) {
          if (pattern.test(line)) findings.push({ rule, location: `${location}:${index + 1}`, message: line.trim().slice(0, 160) });
        }
      });
    }
    return { checked, findings, problems, notes: [] };
  },
});
