// static/editor/main.js
import { loadProject } from './state.js';
import { initMediaPool } from './mediapool.js';
import { initTimeline } from './timeline.js';
import { initMonitor } from './monitor.js';

loadProject();
initMediaPool();
initTimeline();
initMonitor();
