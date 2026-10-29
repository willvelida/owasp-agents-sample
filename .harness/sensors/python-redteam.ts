import { pythonSensor } from '../core/python.ts';

// redteam depends on client by path, so a client change re-checks redteam too.
export default pythonSensor({ project: 'redteam', paths: ['redteam/', 'client/', 'ruff.toml'] });
