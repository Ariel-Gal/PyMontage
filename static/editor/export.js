// static/editor/export.js
import { state } from './state.js';

const btn = document.getElementById('btn-export');
const progress = document.getElementById('export-progress');

async function poll(job) {
  while (true) {
    const status = await (await fetch(`/api/export/${job}/status`)).json();
    if (status.state === 'failed') throw new Error(status.error || 'Export failed');
    progress.textContent = `Rendering… ${status.percent}%`;
    if (status.state === 'done') return;
    await new Promise(r => setTimeout(r, 1000));
  }
}

async function doExport() {
  btn.disabled = true;
  progress.classList.remove('hidden');
  progress.textContent = 'Starting…';
  try {
    const resp = await fetch('/api/export', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session: state.session, project: state.project }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || 'Export rejected');
    await poll(data.job);
    progress.textContent = 'Done — downloading…';
    window.location.href = `/api/export/${data.job}/download`;
    setTimeout(() => progress.classList.add('hidden'), 5000);
  } catch (e) {
    progress.textContent = `⚠ ${e.message}`;
  } finally {
    btn.disabled = false;
  }
}

export function initExport() {
  btn.addEventListener('click', doExport);
}
