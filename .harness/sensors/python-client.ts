import { pythonSensor } from '../core/python.ts';

export default pythonSensor({ project: 'client', paths: ['client/', 'ruff.toml'] });
