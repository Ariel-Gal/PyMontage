// static/editor/main.js
import { loadProject } from './state.js';
import { initMediaPool } from './mediapool.js';
import { initTimeline } from './timeline.js';

loadProject();
initMediaPool();
initTimeline();
