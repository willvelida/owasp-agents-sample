import { applies } from './changes.ts';
import type { ExecOptions, ExecResult, ExitCode, Finding, Problem, SensorContext, SensorDefinition, Status, Tool } from './contracts.ts';

export type RunEnv = Pick<SensorContext, 'repoRoot' | 'changedFiles' | 'exec' | 'which'>;

export interface SensorRun {
  readonly name: string;
  readonly status: Status;
  readonly checked: number;
  readonly durationMs: number;
  readonly findings: readonly Finding[];
  readonly problems: readonly Problem[];
  readonly notes: readonly string[];
}

export const TOOL_REPAIR: Readonly<Record<Tool, string>> = {
  git: 'install git and put it on PATH',
  uv: 'install uv (https://docs.astral.sh/uv/) and put it on PATH',
  npm: 'install Node.js 24.22.0 or later, which includes npm (see CONTRIBUTING.md, Prerequisites)',
};

// A timeout or a spawn failure is always an error, whatever the sensor makes of the result.
function execProblem(argv: readonly string[], options: ExecOptions, result: ExecResult): Problem | null {
  const step = `\`${argv.join(' ')}\` in ${options.cwd}`;
  if (result.timedOut) {
    const message = `${step} timed out after ${Math.round(options.timeoutMs / 1000)}s`;
    return { message, repair: `run ${step} by hand to see why it hangs`, detail: result.output };
  }
  if (result.spawnError === null) return null;
  return { message: `${step} failed to start: ${result.spawnError}`, repair: `check that ${argv[0]} is installed`, detail: result.output };
}

export async function runSensor(name: string, sensor: SensorDefinition, env: RunEnv): Promise<SensorRun> {
  const started = Date.now();
  const make = (status: Status, partial: Partial<SensorRun> = {}): SensorRun =>
    ({ name, status, checked: 0, findings: [], problems: [], notes: [], ...partial, durationMs: Date.now() - started });
  if (!applies(env.changedFiles, sensor.paths, sensor.exclude)) return make('skipped');
  for (const tool of sensor.requires) {
    if ((await env.which(tool)) === null) return make('error', { problems: [{ message: `${tool} not found`, repair: TOOL_REPAIR[tool] }] });
  }

  const forced: Problem[] = [];
  const ctx: SensorContext = {
    repoRoot: env.repoRoot,
    changedFiles: env.changedFiles,
    which: env.which,
    exec: async (argv, options) => {
      const result = await env.exec(argv, options);
      const problem = execProblem(argv, options, result);
      if (problem) forced.push(problem);
      return result;
    },
  };
  try {
    const result = await sensor.run(ctx);
    const problems = [...forced, ...result.problems];
    if (problems.length === 0 && !(result.checked > 0)) {
      problems.push({ message: 'the sensor checked nothing', repair: `run ./harness sensors ${name} and check its paths` });
    }
    const status: Status = problems.length > 0 ? 'error' : result.findings.length > 0 ? 'fail' : 'pass';
    return make(status, { checked: result.checked, findings: result.findings, problems, notes: result.notes });
  } catch (error) {
    const message = `the sensor threw: ${error instanceof Error ? error.message : String(error)}`;
    return make('error', { problems: [...forced, { message, repair: `fix .harness/sensors/${name}.ts` }] });
  }
}

export async function runSensors(sensors: ReadonlyMap<string, SensorDefinition>, env: RunEnv): Promise<SensorRun[]> {
  const runs: SensorRun[] = [];
  for (const [name, sensor] of [...sensors].sort(([a], [b]) => (a < b ? -1 : 1))) runs.push(await runSensor(name, sensor, env));
  return runs;
}

export function exitCodeFor(statuses: Iterable<Status>): ExitCode {
  const all = [...statuses];
  return all.includes('error') ? 2 : all.includes('fail') ? 1 : 0;
}

export const statusFor = (code: ExitCode): 'pass' | 'fail' | 'error' => (['pass', 'fail', 'error'] as const)[code];
