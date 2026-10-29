import { pythonSensor } from '../core/python.ts';

export default pythonSensor({ project: 'solution', paths: ['solution/', 'ruff.toml'], exclude: ['solution/ui/'] });
