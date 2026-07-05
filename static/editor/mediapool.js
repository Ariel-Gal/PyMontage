// static/editor/mediapool.js
import { emit, mutate, on, state } from './state.js';

const drop = document.getElementById('pool-drop');
const fileInput = document.getElementById('pool-file');
const list = document.getElementById('pool-list');

function toast(msg) {
  const el = document.createElement('div');
  el.textContent = msg;
  el.className = 'fixed top-3 right-3 bg-red-800 text-white text-sm px-3 py-2 rounded z-50';
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

async function upload(files) {
  for (const file of files) {
    const form = new FormData();
    form.append('session', state.session);
    form.append('file', file);
    let resp;
    try {
      resp = await fetch('/api/media', { method: 'POST', body: form });
    } catch {
      toast(`Upload failed: ${file.name}`);
      continue;
    }
    const data = await resp.json();
    if (!resp.ok) {
      toast(data.error || `Upload failed: ${file.name}`);
      continue;
    }
    mutate(p => p.media.push({ ...data, offline: false }));
  }
}

function render() {
  list.innerHTML = '';
  for (const m of state.project.media) {
    const card = document.createElement('div');
    card.className = 'rounded bg-zinc-800 overflow-hidden cursor-pointer relative group'
      + (m.offline ? ' opacity-50' : '');
    card.draggable = !m.offline;
    card.innerHTML = `
      <div class="h-16 flex items-center justify-center bg-zinc-950 text-2xl">
        ${m.type === 'audio' ? '🎵' : `<img src="${m.url}/thumb" class="h-full w-full object-cover" onerror="this.remove()">`}
      </div>
      <div class="p-1 text-[11px] leading-tight">
        <div class="truncate">${m.name}${m.offline ? ' (offline)' : ''}</div>
        <div class="text-zinc-500">${m.duration.toFixed(1)}s</div>
      </div>
      <button data-del class="absolute top-0.5 right-0.5 hidden group-hover:block bg-zinc-900/80 rounded px-1 text-xs">✕</button>`;
    card.addEventListener('dragstart', e =>
      e.dataTransfer.setData('application/x-pm-media', m.id));
    card.addEventListener('click', e => {
      if (e.target.closest('[data-del]')) return;
      emit('previewMedia', m);
    });
    card.querySelector('[data-del]').addEventListener('click', () => {
      if (!confirm(`Remove ${m.name} and all its clips?`)) return;
      mutate(p => {
        p.media = p.media.filter(x => x.id !== m.id);
        for (const t of p.tracks) t.clips = t.clips.filter(c => c.mediaId !== m.id);
      });
    });
    list.appendChild(card);
  }
}

async function checkOffline() {
  // After a server restart temp_uploads is gone; mark missing media offline (spec §8).
  let changed = false;
  for (const m of state.project.media) {
    const ok = await fetch(m.url, { method: 'HEAD' }).then(r => r.ok, () => false);
    if (!ok !== m.offline) { m.offline = !ok; changed = true; }
  }
  if (changed) {
    emit('project');
    if (state.project.media.some(m => m.offline)) {
      toast('Some media files are gone (server restarted?) — re-upload them.');
    }
  }
}

export function initMediaPool() {
  drop.addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', () => { upload([...fileInput.files]); fileInput.value = ''; });
  drop.addEventListener('dragover', e => { e.preventDefault(); });
  drop.addEventListener('drop', e => { e.preventDefault(); upload([...e.dataTransfer.files]); });
  on('project', render);
  render();
  checkOffline();
}
