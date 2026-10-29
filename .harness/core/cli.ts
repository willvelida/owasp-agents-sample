import { join } from 'node:path';
import type { CommandContext, CommandDefinition, ExitCode, SensorDefinition } from './contracts.ts';
import { DiscoveryError, discoverCommands, discoverSensors } from './discovery.ts';
import { oneLine } from './output.ts';
import { killAll } from './process.ts';

export interface MainOptions {
  readonly repoRoot: string;
  readonly argv: readonly string[];
  readonly write?: (line: string) => void;
}

const stdout = (line: string): void => void process.stdout.write(`${line}\n`);

function onInterrupt(name: string, write: (line: string) => void): void {
  const handler = (): void => {
    killAll();
    for (const line of [`${name}: error`, 'error: interrupted', `next: ./harness ${name}`]) write(line);
    process.exit(2);
  };
  process.once('SIGINT', handler);
  process.once('SIGTERM', handler);
}

function help(commands: ReadonlyMap<string, CommandDefinition>, write: (line: string) => void): ExitCode {
  write('help: pass');
  write('usage: ./harness [command] [flags]  (cmd: .\\harness)');
  write(commands.size === 0 ? 'commands: none' : 'commands:');
  for (const [name, command] of commands) write(`  ${name}: ${oneLine(command.description)}; usage: ${command.usage}`);
  write('next: ./harness (runs home)');
  return 0;
}

export async function main({ repoRoot, argv, write = stdout }: MainOptions): Promise<ExitCode> {
  const [first, ...rest] = argv;
  const name = first === undefined ? 'home' : first === 'help' || first === '--help' || first === '-h' ? 'help' : first;
  let sensors: Map<string, SensorDefinition>;
  let commands: Map<string, CommandDefinition>;
  try {
    commands = await discoverCommands(join(repoRoot, '.harness', 'commands'));
    sensors = await discoverSensors(join(repoRoot, '.harness', 'sensors'));
  } catch (error) {
    if (!(error instanceof DiscoveryError)) throw error;
    for (const line of [`${name}: error`, `error: ${error.message}`, `next: fix or remove .harness/${error.kind}s/${error.file}`]) write(line);
    return 2;
  }
  if (name === 'help') return help(commands, write);
  const command = commands.get(name);
  if (command === undefined) {
    const what = name.startsWith('-') ? `unknown option '${name}'` : `unknown command '${name}'`;
    for (const line of ['harness: error', `error: ${what}`, 'next: ./harness --help']) write(line);
    return 2;
  }
  onInterrupt(name, write);
  let written = 0;
  const counted = (line: string): void => void (written++, write(line));
  const ctx: CommandContext = { repoRoot, argv: rest, sensors, commands, write: counted };
  try {
    return await command.run(ctx);
  } catch (error) {
    if (written === 0) write(`${name}: error`);
    write(`error: ${name} failed: ${oneLine(error instanceof Error ? error.message : String(error))}`);
    write(`next: fix .harness/commands/${name}.ts`);
    return 2;
  }
}
