// Contracts every sensor and command is written against. Changing an exported shape means updating .harness/README.md.

export type Status = 'pass' | 'fail' | 'error' | 'skipped';
export type ExitCode = 0 | 1 | 2;
export type Tool = 'git' | 'uv' | 'npm';

export const TOOLS: readonly Tool[] = ['git', 'uv', 'npm'];

export interface Rule { readonly id: string; readonly expectation: string; readonly repair: string }

export interface Finding { readonly rule: string; readonly message: string; readonly location?: string; readonly detail?: string }

// A problem means no trustworthy result exists, so the sensor reports error rather than fail.
export interface Problem { readonly message: string; readonly repair: string; readonly detail?: string }

export interface SensorResult {
  readonly checked: number; // steps run or files scanned; 0 means error
  readonly findings: readonly Finding[];
  readonly problems: readonly Problem[];
  readonly notes: readonly string[];
}

// cwd is repo-relative; an env value of undefined removes that variable.
export interface ExecOptions { readonly cwd: string; readonly timeoutMs: number; readonly env?: Readonly<Record<string, string | undefined>> }

export interface ExecResult {
  readonly exitCode: number | null; // null when killed or never started
  readonly timedOut: boolean;
  readonly spawnError: string | null;
  readonly output: string; // interleaved stdout and stderr, ANSI stripped, capped tail
  readonly truncated: boolean;
  readonly durationMs: number;
}

export interface SensorContext {
  readonly repoRoot: string;
  readonly changedFiles: readonly string[] | null; // null under --all or when no base resolves
  exec(argv: readonly [string, ...string[]], options: ExecOptions): Promise<ExecResult>;
  which(tool: Tool): Promise<string | null>;
}

export interface SensorDefinition {
  readonly description: string;
  readonly paths: readonly string[]; // trailing "/" = directory prefix; otherwise an exact file
  readonly exclude?: readonly string[];
  readonly requires: readonly Tool[];
  readonly rules: readonly Rule[];
  run(ctx: SensorContext): Promise<SensorResult>;
}

export interface CommandContext {
  readonly repoRoot: string;
  readonly argv: readonly string[]; // arguments after the command name
  readonly sensors: ReadonlyMap<string, SensorDefinition>;
  readonly commands: ReadonlyMap<string, CommandDefinition>;
  write(line: string): void;
}

export interface CommandDefinition {
  readonly description: string;
  readonly usage: string;
  run(ctx: CommandContext): Promise<ExitCode>;
}

export const defineSensor = (definition: SensorDefinition): SensorDefinition => definition;
export const defineCommand = (definition: CommandDefinition): CommandDefinition => definition;
