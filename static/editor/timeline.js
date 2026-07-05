// static/editor/timeline.js
import {
  beginDrag, clipDur, commitDrag, findClip, findMedia, mutate, on,
  redo, selectClip, setPlayhead, state, uid, undo,
} from './state.js';

const scroll = document.getElementById('timeline-scroll');
const rulerEl = document.getElementById('ruler');
const tracksEl = document.getElementById('tracks');
const playheadEl = document.getElementById('playhead');
const HEADER_W = 96;
const SNAP_PX = 8;

const pps = () => state.pixelsPerSecond;
const xToTime = x => Math.max(0, (x - HEADER_W) / pps());
const timeToX = t => HEADER_W + t * pps();

function timelineEnd() {
  let end = 60;
  for (const t of state.project.tracks)
    for (const c of t.clips) end = Math.max(end, c.start + clipDur(c) + 10);
  return end;
}

/* ---------- waveforms ---------- */
const peakCache = new Map();
async function getPeaks(media) {
  if (peakCache.has(media.id)) return peakCache.get(media.id);
  const promise = (async () => {
    const buf = await (await fetch(media.url)).arrayBuffer();
    const ctx = new OfflineAudioContext(1, 1, 44100);
    const audio = await ctx.decodeAudioData(buf);
    const data = audio.getChannelData(0);
    const buckets = 2000, out = new Float32Array(buckets);
    const step = Math.floor(data.length / buckets) || 1;
    for (let i = 0; i < buckets; i++) {
      let max = 0;
      for (let j = i * step; j < (i + 1) * step && j < data.length; j++)
        max = Math.max(max, Math.abs(data[j]));
      out[i] = max;
    }
    return out;
  })();
  peakCache.set(media.id, promise);
  return promise;
}

async function drawWave(canvas, media, clip) {
  try {
    const peaks = await getPeaks(media);
    const ctx = canvas.getContext('2d');
    const { width: w, height: h } = canvas;
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = '#4ade80';
    const from = (clip.in / media.duration) * peaks.length;
    const span = ((clip.out - clip.in) / media.duration) * peaks.length;
    for (let x = 0; x < w; x++) {
      const p = peaks[Math.min(peaks.length - 1, Math.floor(from + (x / w) * span))];
      const bar = Math.max(1, p * h);
      ctx.fillRect(x, (h - bar) / 2, 1, bar);
    }
  } catch { /* decode failed — plain clip body is fine */ }
}

/* ---------- rendering ---------- */
function renderRuler(width) {
  rulerEl.innerHTML = '';
  rulerEl.style.width = width + 'px';
  // tick spacing: nearest "nice" interval that yields >= 70px between labels
  const intervals = [0.5, 1, 2, 5, 10, 30, 60, 120, 300];
  const step = intervals.find(i => i * pps() >= 70) || 600;
  for (let t = 0; t <= xToTime(width); t += step) {
    const tick = document.createElement('div');
    tick.className = 'ruler-tick';
    tick.style.left = timeToX(t) + 'px';
    const m = Math.floor(t / 60), s = (t % 60).toFixed(step < 1 ? 1 : 0);
    tick.textContent = `${m}:${String(s).padStart(2, '0')}`;
    rulerEl.appendChild(tick);
  }
}

function render() {
  const width = timeToX(timelineEnd());
  renderRuler(width);
  tracksEl.innerHTML = '';
  tracksEl.style.width = width + 'px';
  for (const track of state.project.tracks) {
    const lane = document.createElement('div');
    lane.className = 'track';
    lane.dataset.trackId = track.id;
    const off = track.kind === 'video' ? track.hidden : track.muted;
    lane.innerHTML = `<div class="track-header"><span>${track.id}</span>
      <button data-toggle class="ml-auto text-xs ${off ? 'text-red-400' : 'text-zinc-500'}"
        title="${track.kind === 'video' ? 'Hide track' : 'Mute track'}">
        ${track.kind === 'video' ? '👁' : '🔊'}</button></div>`;
    lane.querySelector('[data-toggle]').addEventListener('pointerdown', e => {
      e.stopPropagation();
      const key = track.kind === 'video' ? 'hidden' : 'muted';
      mutate(p => {
        const t = p.tracks.find(x => x.id === track.id);
        t[key] = !t[key];
      });
    });
    for (const clip of track.clips) {
      const media = findMedia(clip.mediaId);
      const el = document.createElement('div');
      el.className = `clip ${media ? media.type : ''}`
        + (clip.id === state.selectedClipId ? ' selected' : '')
        + (!media || media.offline ? ' offline' : '');
      el.dataset.clipId = clip.id;
      el.style.left = timeToX(clip.start) + 'px';
      el.style.width = Math.max(8, clipDur(clip) * pps()) + 'px';
      el.innerHTML = `<span class="clip-label">${media?.name || '?'}</span>
        <div class="edge left"></div><div class="edge right"></div>`;
      if (media?.type === 'audio' && !media.offline) {
        const canvas = document.createElement('canvas');
        canvas.width = Math.max(8, Math.floor(clipDur(clip) * pps()));
        canvas.height = 48;
        el.prepend(canvas);
        drawWave(canvas, media, clip);
      }
      lane.appendChild(el);
    }
    tracksEl.appendChild(lane);
  }
  positionPlayhead();
}

function positionPlayhead() {
  // playhead is an abspos child of the scroll container, so it scrolls with content
  playheadEl.style.left = timeToX(state.playhead) + 'px';
}

/* ---------- snapping & overlap ---------- */
function snapPoints(excludeClipId) {
  const pts = [0, state.playhead];
  for (const t of state.project.tracks)
    for (const c of t.clips) {
      if (c.id === excludeClipId) continue;
      pts.push(c.start, c.start + clipDur(c));
    }
  return pts;
}

function snap(t, excludeClipId, disabled) {
  if (disabled) return t;
  const threshold = SNAP_PX / pps();
  for (const p of snapPoints(excludeClipId))
    if (Math.abs(t - p) < threshold) return p;
  return t;
}

function resolveOverlap(track, clip) {
  // spec §4: overlaps disallowed — nudge to the end of the clip we landed on
  for (const other of track.clips) {
    if (other.id === clip.id) continue;
    const aEnd = clip.start + clipDur(clip);
    const bEnd = other.start + clipDur(other);
    if (clip.start < bEnd && aEnd > other.start) clip.start = bEnd;
  }
}

/* ---------- interactions ---------- */
function onPointerDown(e) {
  const clipEl = e.target.closest('.clip');
  if (!clipEl) {
    // click on empty timeline = move playhead + deselect
    const x = e.clientX - scroll.getBoundingClientRect().left + scroll.scrollLeft;
    setPlayhead(xToTime(x));
    selectClip(null);
    render();
    return;
  }
  const found = findClip(clipEl.dataset.clipId);
  if (!found) return;
  const { clip, track } = found;
  selectClip(clip.id);
  render();

  const media = findMedia(clip.mediaId);
  const mode = e.target.classList.contains('edge')
    ? (e.target.classList.contains('left') ? 'trim-l' : 'trim-r') : 'move';
  const snapshot = beginDrag();
  const startX = e.clientX;
  const orig = { start: clip.start, in: clip.in, out: clip.out };
  const speed = clip.effects?.speed || 1;
  const maxOut = media?.type === 'image' ? 3600 : (media?.duration ?? clip.out);

  function move(ev) {
    const dt = (ev.clientX - startX) / pps();
    if (mode === 'move') {
      clip.start = Math.max(0, snap(orig.start + dt, clip.id, ev.altKey));
      // cross-track move (same kind only)
      const lane = document.elementFromPoint(ev.clientX, ev.clientY)?.closest('.track');
      if (lane) {
        const target = state.project.tracks.find(t => t.id === lane.dataset.trackId);
        if (target && target !== found.track && target.kind === track.kind) {
          found.track.clips = found.track.clips.filter(c => c.id !== clip.id);
          target.clips.push(clip);
          found.track = target;
        }
      }
    } else if (mode === 'trim-l') {
      const din = dt * speed;
      clip.in = Math.min(Math.max(0, orig.in + din), clip.out - 0.1);
      clip.start = orig.start + (clip.in - orig.in) / speed;
    } else {
      clip.out = Math.max(clip.in + 0.1, Math.min(maxOut, orig.out + dt * speed));
    }
    render();
  }
  function up() {
    window.removeEventListener('pointermove', move);
    window.removeEventListener('pointerup', up);
    resolveOverlap(found.track, clip);
    commitDrag(snapshot);
  }
  window.addEventListener('pointermove', move);
  window.addEventListener('pointerup', up);
}

function onDrop(e) {
  const mediaId = e.dataTransfer.getData('application/x-pm-media');
  if (!mediaId) return;
  e.preventDefault();
  const lane = e.target.closest('.track');
  const media = findMedia(mediaId);
  if (!lane || !media) return;
  const track = state.project.tracks.find(t => t.id === lane.dataset.trackId);
  const wantKind = media.type === 'audio' ? 'audio' : 'video';
  if (track.kind !== wantKind) return;
  const x = e.clientX - scroll.getBoundingClientRect().left + scroll.scrollLeft;
  const clip = {
    id: uid(), mediaId, start: xToTime(x), in: 0, out: media.duration,
    effects: { speed: 1.0, opacity: 1.0, filter: null },
  };
  mutate(p => {
    const t = p.tracks.find(t2 => t2.id === track.id);
    t.clips.push(clip);
    resolveOverlap(t, clip);
  });
  selectClip(clip.id);
}

function splitAtPlayhead() {
  const found = state.selectedClipId && findClip(state.selectedClipId);
  if (!found) return;
  const { clip, track } = found;
  const t = state.playhead;
  if (t <= clip.start || t >= clip.start + clipDur(clip)) return;
  const speed = clip.effects?.speed || 1;
  const cut = clip.in + (t - clip.start) * speed;
  mutate(p => {
    const tr = p.tracks.find(x => x.id === track.id);
    const c = tr.clips.find(x => x.id === clip.id);
    const right = { ...structuredClone(c), id: uid(), start: t, in: cut };
    c.out = cut;
    tr.clips.push(right);
  });
}

function onKey(e) {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
  if (e.code === 'KeyS' && !e.ctrlKey) splitAtPlayhead();
  else if (e.code === 'Delete' || e.code === 'Backspace') {
    if (!state.selectedClipId) return;
    const id = state.selectedClipId;
    mutate(p => { for (const t of p.tracks) t.clips = t.clips.filter(c => c.id !== id); });
    selectClip(null);
  } else if (e.ctrlKey && e.code === 'KeyZ' && e.shiftKey) redo();
  else if (e.ctrlKey && e.code === 'KeyZ') undo();
  else return;
  e.preventDefault();
}

export function initTimeline() {
  tracksEl.addEventListener('pointerdown', onPointerDown);
  rulerEl.addEventListener('pointerdown', onPointerDown);
  tracksEl.addEventListener('dragover', e => e.preventDefault());
  tracksEl.addEventListener('drop', onDrop);
  window.addEventListener('keydown', onKey);
  scroll.addEventListener('wheel', e => {
    if (!e.ctrlKey) return;
    e.preventDefault();
    state.pixelsPerSecond = Math.min(500, Math.max(2,
      state.pixelsPerSecond * (e.deltaY < 0 ? 1.2 : 1 / 1.2)));
    render();
  }, { passive: false });
  on('project', render);
  on('selection', render);
  on('playhead', positionPlayhead);
  render();
}
