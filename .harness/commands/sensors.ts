import { defineCommand } from '../core/contracts.ts';
import type { SensorDefinition } from '../core/contracts.ts';
import { oneLine, parseFlags } from '../core/output.ts';

const USAGE = './harness sensors [<name>]';

function scope(sensor: SensorDefinition): string {
  const parts = [`paths: ${sensor.paths.join(', ')}`];
  if (sensor.exclude && sensor.exclude.length > 0) parts.push(`exclude: ${sensor.exclude.join(', ')}`);
  parts.push(`requires: ${sensor.requires.length > 0 ? sensor.requires.join(', ') : 'none'}`);
  return parts.join('; ');
}

export default defineCommand({
  description: "List the sensors, or explain one sensor's rules with their repairs.",
  usage: USAGE,
  async run(ctx) {
    const parsed = parseFlags('sensors', USAGE, ctx.argv, {}, ctx.write, true);
    if (parsed === null) return 2;
    const [name, ...extra] = parsed.positionals;
    if (extra.length > 0) {
      for (const line of ['sensors: error', `error: expected at most one sensor name`, `usage: ${USAGE}`, 'next: ./harness sensors']) ctx.write(line);
      return 2;
    }
    if (name === undefined) {
      ctx.write('sensors: pass');
      if (ctx.sensors.size === 0) ctx.write('sensors: none found in .harness/sensors/');
      for (const [sensorName, sensor] of ctx.sensors) ctx.write(`${sensorName}: ${oneLine(sensor.description)} (${scope(sensor)})`);
      ctx.write("next: ./harness sensors <name> to see a sensor's rules");
      return 0;
    }
    const sensor = ctx.sensors.get(name);
    if (sensor === undefined) {
      for (const line of ['sensors: error', `error: unknown sensor '${name}'`, 'next: ./harness sensors']) ctx.write(line);
      return 2;
    }
    ctx.write('sensors: pass');
    ctx.write(`sensor: ${name}`);
    ctx.write(`description: ${oneLine(sensor.description)}`);
    ctx.write(`scope: ${scope(sensor)}`);
    ctx.write('rules:');
    for (const rule of sensor.rules) ctx.write(`  ${rule.id}: ${oneLine(rule.expectation)}; repair: ${oneLine(rule.repair)}`);
    ctx.write('next: ./harness verify');
    return 0;
  },
});
