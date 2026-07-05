// static/editor/monitor.js — approximate preview: topmost video clip wins (spec §5)
import { clipDur, findMedia, on, setPlayhead, state } from './state.js';

const screen = document.getElementById('monitor-video');
const pool = document.getElementById('monitor-pool');
const btnPlay = document.getElementById('btn-play');
const tcEl = document.getElementById('tc');

const elements = new Map(); // mediaId -> <video>/<audio>
let rate = 1;
let lastFrame = 0;

function elementFor(media) {
  if (elements.has(media.id)) return elements.get(media.id);
  const el = document.createElement(media.type === 'audio' ? 'audio' : 'video');
  el.src = media.url;
  el.preload = 'auto';
  pool.appendChild(el);
  elements.set(media.id, el);
  return el;
}

function activeClip(track, t) {
  return track.clips.find(c => t >= c.start && t < c.start + clipDur(c)) || null;
}

function srcTime(clip, t) {
  return clip.in + (t - clip.start) * (clip.effects?.speed || 1);
}

function timecode(t) {
  const fps = state.project.settings.fps;
  const f = Math.floor((t % 1) * fps + 1e-4); // epsilon: 4 + 1/30 must show frame 1, not 0
  const s = Math.floor(t);
  const pad = n => String(n).padStart(2, '0');
  return `${pad(Math.floor(s / 3600))}:${pad(Math.floor(s / 60) % 60)}:${pad(s % 60)}:${pad(f)}`;
}

function update(t) {
  tcEl.textContent = timecode(t);
  let shown = null;
  const activeAudio = new Set();

  for (const track of state.project.tracks) {
    if (track.kind === 'video' ? track.hidden : track.muted) continue;
    const clip = activeClip(track, t);
    if (!clip) continue;
    const media = findMedia(clip.mediaId);
    if (!media || media.offline) continue;

    if (track.kind === 'video' && !shown) {
      shown = { clip, media };
    } else if (track.kind === 'audio') {
      activeAudio.add(media.id);
      const el = elementFor(media);
      el.playbackRate = (clip.effects?.speed || 1) * rate;
      syncElement(el, srcTime(clip, t));
    }
  }

  // pause audio elements that fell out of their clips
  for (const [id, el] of elements)
    if (el.tagName === 'AUDIO' && !activeAudio.has(id) && !el.paused) el.pause();

  if (!shown) {
    screen.removeAttribute('src');
    screen.style.background = '';
    screen.style.opacity = 1;
    screen.style.filter = '';
    return;
  }
  const { clip, media } = shown;
  if (media.type === 'image') {
    // images render as a CSS background on the <video> element
    screen.removeAttribute('src');
    screen.style.background = `url('${media.url}') center/contain no-repeat`;
  } else {
    screen.style.background = '';
    if (!screen.src.endsWith(media.url)) screen.src = media.url;
    screen.playbackRate = (clip.effects?.speed || 1) * rate;
    syncElement(screen, srcTime(clip, t));
    screen.muted = false;
  }
  screen.style.opacity = clip.effects?.opacity ?? 1;
  screen.style.filter = clip.effects?.filter || '';
}

function syncElement(el, target) {
  if (state.playing) {
    if (el.paused) el.play().catch(() => {});
    if (Math.abs(el.currentTime - target) > 0.15) el.currentTime = target;
  } else {
    if (!el.paused) el.pause();
    if (Math.abs(el.currentTime - target) > 1 / state.project.settings.fps)
      el.currentTime = target;
  }
}

function loop(now) {
  if (state.playing) {
    const dt = Math.min(0.1, (now - lastFrame) / 1000); // clamp: rAF gaps must not teleport the playhead
    setPlayhead(state.playhead + dt * rate);
  }
  lastFrame = now;
  update(state.playhead);
  requestAnimationFrame(loop);
}

function setPlaying(p) {
  state.playing = p;
  if (!p) rate = 1;
  btnPlay.textContent = p ? '⏸' : '▶';
  if (!p) {
    for (const el of elements.values()) el.pause();
    if (screen.src) screen.pause();
  }
}

function onKey(e) {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
  const frame = 1 / state.project.settings.fps;
  if (e.code === 'Space') setPlaying(!state.playing);
  else if (e.code === 'ArrowLeft') { setPlaying(false); setPlayhead(state.playhead - frame); }
  else if (e.code === 'ArrowRight') { setPlaying(false); setPlayhead(state.playhead + frame); }
  else if (e.code === 'KeyJ') setPlaying(false);                       // reverse unsupported → stop
  else if (e.code === 'KeyK') setPlaying(false);
  else if (e.code === 'KeyL') {
    if (!state.playing) { rate = 1; setPlaying(true); }
    else rate = rate >= 4 ? 1 : rate * 2;                              // 1x → 2x → 4x
  } else return;
  e.preventDefault();
}

export function initMonitor() {
  btnPlay.addEventListener('click', () => setPlaying(!state.playing));
  document.getElementById('btn-prev-frame').addEventListener('click',
    () => { setPlaying(false); setPlayhead(state.playhead - 1 / state.project.settings.fps); });
  document.getElementById('btn-next-frame').addEventListener('click',
    () => { setPlaying(false); setPlayhead(state.playhead + 1 / state.project.settings.fps); });
  window.addEventListener('keydown', onKey);
  // repaint on scrub/step even between rAF frames (and when the tab is hidden)
  on('playhead', () => { if (!state.playing) update(state.playhead); });
  on('project', () => update(state.playhead));
  // rAF stops in hidden tabs — pause instead of jumping on return
  document.addEventListener('visibilitychange', () => {
    if (document.hidden && state.playing) setPlaying(false);
  });
  on('previewMedia', media => {
    // clicking a pool item previews its source directly
    setPlaying(false);
    if (media.type === 'image') {
      screen.removeAttribute('src');
      screen.style.background = `url('${media.url}') center/contain no-repeat`;
    } else {
      screen.style.background = '';
      screen.src = media.url;
      screen.currentTime = 0;
    }
  });
  requestAnimationFrame(loop);
}
