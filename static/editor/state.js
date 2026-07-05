// static/editor/state.js — project model: single source of truth (spec §1)

export const state = {
  session: localStorage.getItem('pm_session') || crypto.randomUUID(),
  project: null,
  selectedClipId: null,
  playhead: 0,
  pixelsPerSecond: 40,
  playing: false,
};
localStorage.setItem('pm_session', state.session);

const listeners = {};
export function on(event, fn) { (listeners[event] ||= []).push(fn); }
export function emit(event, data) { (listeners[event] || []).forEach(fn => fn(data)); }

export function uid() { return crypto.randomUUID().replaceAll('-', ''); }

function newProject() {
  return {
    settings: { width: 1920, height: 1080, fps: 30 },
    media: [],
    tracks: [
      { id: 'V2', kind: 'video', clips: [] },
      { id: 'V1', kind: 'video', clips: [] },
      { id: 'A1', kind: 'audio', clips: [] },
      { id: 'A2', kind: 'audio', clips: [] },
    ],
  };
}

export function loadProject() {
  const saved = localStorage.getItem('pm_project');
  state.project = saved ? JSON.parse(saved) : newProject();
  emit('project');
}

function save() {
  localStorage.setItem('pm_project', JSON.stringify(state.project));
}

const undoStack = [];
const redoStack = [];

export function mutate(fn) {
  undoStack.push(structuredClone(state.project));
  if (undoStack.length > 50) undoStack.shift();
  redoStack.length = 0;
  fn(state.project);
  save();
  emit('project');
}

// Drag interactions mutate the model live but push a single undo entry on release.
export function beginDrag() { return structuredClone(state.project); }
export function commitDrag(snapshot) {
  undoStack.push(snapshot);
  if (undoStack.length > 50) undoStack.shift();
  redoStack.length = 0;
  save();
  emit('project');
}

export function undo() {
  if (!undoStack.length) return;
  redoStack.push(structuredClone(state.project));
  state.project = undoStack.pop();
  save();
  emit('project');
}

export function redo() {
  if (!redoStack.length) return;
  undoStack.push(structuredClone(state.project));
  state.project = redoStack.pop();
  save();
  emit('project');
}

export function findClip(id) {
  for (const track of state.project.tracks) {
    const clip = track.clips.find(c => c.id === id);
    if (clip) return { clip, track };
  }
  return null;
}

export function findMedia(id) {
  return state.project.media.find(m => m.id === id) || null;
}

export function clipDur(clip) {
  const speed = clip.effects?.speed || 1;
  return (clip.out - clip.in) / speed;
}

export function setPlayhead(t) {
  state.playhead = Math.max(0, t);
  emit('playhead', state.playhead);
}

export function selectClip(id) {
  state.selectedClipId = id;
  emit('selection', id);
}
