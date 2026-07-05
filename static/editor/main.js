// static/editor/main.js
import { loadProject } from './state.js';
import { initMediaPool } from './mediapool.js';
import { initTimeline } from './timeline.js';
import { initMonitor } from './monitor.js';
import { initInspector } from './inspector.js';
import { initExport } from './export.js';

loadProject();
initMediaPool();
initTimeline();
initMonitor();
initInspector();
initExport();
