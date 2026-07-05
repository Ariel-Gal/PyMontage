// static/editor/inspector.js
import { findClip, findMedia, mutate, on, state } from './state.js';

const body = document.getElementById('inspector-body');

const FIELDS = [
  { key: 'in', label: 'In (s)' },
  { key: 'out', label: 'Out (s)' },
  { key: 'start', label: 'Start (s)' },
];
const EFFECTS = [
  { key: 'speed', label: 'Speed', min: 0.1, max: 10 },
  { key: 'opacity', label: 'Opacity', min: 0, max: 1 },
];

function render() {
  const found = state.selectedClipId && findClip(state.selectedClipId);
  if (!found) {
    body.className = 'p-3 text-sm text-zinc-500';
    body.textContent = 'No clip selected';
    return;
  }
  const { clip } = found;
  const media = findMedia(clip.mediaId);
  body.className = 'p-3 text-sm flex flex-col gap-2';
  body.innerHTML = `<div class="text-zinc-400 truncate">${media?.name || '?'}</div>`;
  const row = (label, value, apply) => {
    const div = document.createElement('div');
    div.className = 'flex items-center justify-between gap-2';
    div.innerHTML = `<label class="text-zinc-500 text-xs">${label}</label>`;
    const input = document.createElement('input');
    input.type = 'number';
    input.step = '0.1';
    input.value = value;
    input.className = 'w-24 bg-zinc-800 rounded px-2 py-1 text-right text-xs';
    input.addEventListener('change', () => apply(parseFloat(input.value)));
    div.appendChild(input);
    body.appendChild(div);
  };
  for (const f of FIELDS)
    row(f.label, clip[f.key].toFixed(2), v => mutate(() => {
      if (!Number.isFinite(v) || v < 0) return;
      clip[f.key] = v;
    }));
  for (const f of EFFECTS)
    row(f.label, (clip.effects?.[f.key] ?? 1), v => mutate(() => {
      if (!Number.isFinite(v)) return;
      (clip.effects ||= {})[f.key] = Math.min(f.max, Math.max(f.min, v));
    }));

  const filt = document.createElement('div');
  filt.className = 'flex items-center justify-between gap-2';
  filt.innerHTML = '<label class="text-zinc-500 text-xs">Filter</label>';
  const sel = document.createElement('select');
  sel.className = 'bg-zinc-800 rounded px-2 py-1 text-xs';
  for (const opt of ['none', 'grayscale(1)', 'sepia(1)', 'contrast(1.3)'])
    sel.add(new Option(opt, opt === 'none' ? '' : opt));
  sel.value = clip.effects?.filter || '';
  sel.addEventListener('change', () =>
    mutate(() => { (clip.effects ||= {}).filter = sel.value || null; }));
  filt.appendChild(sel);
  body.appendChild(filt);
}

export function initInspector() {
  on('selection', render);
  on('project', render);
  render();
}
