// Plain JavaScript on purpose: the version gate must run on a Node too old to strip TypeScript types.
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const MINIMUM = [24, 12, 0];
const current = process.versions.node.split('.').map(Number);

function isOlder(actual, minimum) {
  for (let i = 0; i < minimum.length; i++) {
    if ((actual[i] ?? 0) !== minimum[i]) return (actual[i] ?? 0) < minimum[i];
  }
  return false;
}

if (isOlder(current, MINIMUM)) {
  console.log(`error: node ${process.versions.node} is older than ${MINIMUM.join('.')}`);
  console.log('next: install Node.js 24.22.0 or later (see CONTRIBUTING.md, Prerequisites)');
  process.exit(2);
}

const repoRoot = resolve(fileURLToPath(new URL('..', import.meta.url)));
const { main } = await import('./core/cli.ts');
process.exitCode = await main({ repoRoot, argv: process.argv.slice(2) });
