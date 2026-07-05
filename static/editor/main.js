// static/editor/main.js
import { loadProject, state } from './state.js';

loadProject();
console.log('PyMontage editor loaded', state.session, state.project);
