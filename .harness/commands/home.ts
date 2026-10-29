import { applies, describeChanges, detectChanges } from '../core/changes.ts';
import { defineCommand } from '../core/contracts.ts';
import { parseFlags } from '../core/output.ts';
import { exec } from '../core/process.ts';

const USAGE = './harness [home]';

export default defineCommand({
  description: 'Orientation (the default): base, change size, which sensors apply, and what to run next.',
  usage: USAGE,
  async run(ctx) {
    if (parseFlags('home', USAGE, ctx.argv, {}, ctx.write) === null) return 2;
    const result = await detectChanges((argv, options, stderr) => exec(ctx.repoRoot, argv, options, stderr));
    if (!result.ok) {
      for (const line of ['home: error', `error: ${result.message}`, `next: ${result.next}`]) ctx.write(line);
      return 2;
    }
    const names = [...ctx.sensors].filter(([, sensor]) => applies(result.changes.files, sensor.paths, sensor.exclude)).map(([name]) => name);
    ctx.write('home: pass');
    for (const line of describeChanges(result.changes)) ctx.write(line);
    ctx.write(`applies: ${names.length > 0 ? names.join(', ') : 'none'}`);
    ctx.write(`commands: ${[...ctx.commands.keys()].join(', ')}`);
    ctx.write(names.length > 0 ? 'next: ./harness verify' : 'next: ./harness verify --all');
    return 0;
  },
});
