import { readdir } from 'node:fs/promises';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { TOOLS } from './contracts.ts';
import type { CommandDefinition, SensorDefinition } from './contracts.ts';

export type Kind = 'sensor' | 'command';

export class DiscoveryError extends Error {
  readonly kind: Kind;
  readonly file: string;
  constructor(kind: Kind, file: string, reason: string) {
    super(`invalid ${kind} ${file}: ${reason}`);
    this.kind = kind;
    this.file = file;
  }
}

const NAME = /^[a-z][a-z0-9-]*$/;
const RULE_ID = /^[a-z][a-z0-9]*(-[a-z0-9]+)*$/;
const KEYS: Record<Kind, { required: string[]; optional: string[] }> = {
  sensor: { required: ['description', 'paths', 'requires', 'rules', 'run'], optional: ['exclude'] },
  command: { required: ['description', 'usage', 'run'], optional: [] },
};

const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);
const filled = (value: unknown): value is string => typeof value === 'string' && value.trim().length > 0;

function keyProblem(value: Record<string, unknown>, keys: { required: string[]; optional: string[] }): string | null {
  const unknown = Object.keys(value).find((key) => !keys.required.includes(key) && !keys.optional.includes(key));
  if (unknown) return `unknown key '${unknown}'`;
  const missing = keys.required.find((key) => !(key in value));
  return missing ? `missing key '${missing}'` : null;
}

export function pathProblem(entry: unknown): string | null {
  if (!filled(entry)) return 'path entries must be non-empty strings';
  if (entry.includes('\\')) return `path '${entry}' must use forward slashes`;
  if (entry.startsWith('/') || /^[A-Za-z]:/.test(entry)) return `path '${entry}' must be repo-relative`;
  return entry.split('/').includes('..') ? `path '${entry}' must not contain '..'` : null;
}

function rulesProblem(rules: unknown): string | null {
  if (!Array.isArray(rules) || rules.length === 0) return "'rules' must be a non-empty array";
  const ids = new Set<string>();
  for (const rule of rules) {
    if (!isObject(rule) || keyProblem(rule, { required: ['id', 'expectation', 'repair'], optional: [] })) {
      return 'each rule must have exactly id, expectation, and repair';
    }
    if (typeof rule.id !== 'string' || !RULE_ID.test(rule.id)) return `rule id '${String(rule.id)}' must be kebab-case`;
    if (!filled(rule.expectation) || !filled(rule.repair)) return `rule '${rule.id}' needs an expectation and a repair`;
    if (ids.has(rule.id)) return `duplicate rule id '${rule.id}'`;
    ids.add(rule.id);
  }
  return null;
}

export function validate(kind: Kind, value: unknown): string | null {
  if (!isObject(value)) return `default export must be an object built with define${kind === 'sensor' ? 'Sensor' : 'Command'}`;
  const keys = keyProblem(value, KEYS[kind]);
  if (keys) return keys;
  if (!filled(value.description)) return "'description' must be a non-empty string";
  if (typeof value.run !== 'function') return "'run' must be a function";
  if (kind === 'command') return filled(value.usage) ? null : "'usage' must be a non-empty string";
  for (const key of ['paths', 'exclude']) {
    if (key === 'exclude' && value.exclude === undefined) continue;
    if (!Array.isArray(value[key])) return `'${key}' must be an array`;
    const problem = (value[key] as unknown[]).map(pathProblem).find(Boolean);
    if (problem) return problem;
  }
  if (!Array.isArray(value.requires) || value.requires.some((tool) => !TOOLS.includes(tool))) {
    return `'requires' may only contain ${TOOLS.join(', ')}`;
  }
  return rulesProblem(value.rules);
}

async function discover(dir: string, kind: Kind): Promise<Map<string, unknown>> {
  const entries = await readdir(dir, { withFileTypes: true }).catch((error: NodeJS.ErrnoException) => {
    if (error.code === 'ENOENT') return [];
    throw error;
  });
  const files = entries.filter((e) => e.isFile() && e.name.endsWith('.ts') && !e.name.endsWith('.test.ts')).map((e) => e.name);
  const found = new Map<string, unknown>();
  for (const file of files.sort()) {
    const name = file.slice(0, -3);
    if (!NAME.test(name)) throw new DiscoveryError(kind, file, 'file name must match ^[a-z][a-z0-9-]*\\.ts$');
    let mod: Record<string, unknown>;
    try {
      mod = (await import(pathToFileURL(join(dir, file)).href)) as Record<string, unknown>;
    } catch (error) {
      throw new DiscoveryError(kind, file, `failed to load: ${(error as Error).message.split('\n')[0]}`);
    }
    const reason = 'default' in mod ? validate(kind, mod.default) : 'missing default export';
    if (reason) throw new DiscoveryError(kind, file, reason);
    found.set(name, mod.default);
  }
  return found;
}

export const discoverSensors = (dir: string): Promise<Map<string, SensorDefinition>> =>
  discover(dir, 'sensor') as Promise<Map<string, SensorDefinition>>;
export const discoverCommands = (dir: string): Promise<Map<string, CommandDefinition>> =>
  discover(dir, 'command') as Promise<Map<string, CommandDefinition>>;
