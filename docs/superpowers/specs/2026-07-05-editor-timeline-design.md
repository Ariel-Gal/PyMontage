# PyMontage Editor — Phase 1: Premiere-Style Editor UI + Timeline

**Date:** 2026-07-05
**Status:** Approved
**Scope:** First slice of the "PyMontage → web NLE" transformation. Editor UI, multi-track timeline, client-side preview, server-side export. Automation features (auto-montage, silence trim, batch templates, aspect presets) are phase 2 and out of scope here except for UI stubs.

## Decisions made during brainstorming

| Question | Decision |
|---|---|
| First slice | Editor UI + timeline foundation; automation plugs in later |
| Stack | Keep Flask; single-page frontend in place (vanilla JS + Tailwind CDN, no build step) |
| Preview | Client-side approximate playback; exact result only at export |
| Existing slideshow | Becomes an automation preset in phase 2; old `/` page untouched during phase 1 |
| Timeline rendering | DOM (positioned divs), not canvas — 100+-clip scale doesn't exist yet |

## 1. Project model (single source of truth)

One JSON object, owned by the browser, is the contract between frontend and backend:

```json
{
  "settings": { "width": 1920, "height": 1080, "fps": 30 },
  "media": [
    { "id": "m1", "name": "clip.mp4", "type": "video", "duration": 12.3,
      "url": "/api/media/<session>/m1", "width": 1920, "height": 1080 }
  ],
  "tracks": [
    { "id": "V2", "kind": "video", "clips": [] },
    { "id": "V1", "kind": "video", "clips": [
      { "id": "c1", "mediaId": "m1", "start": 4.0, "in": 1.2, "out": 6.5,
        "effects": { "speed": 1.0, "opacity": 1.0, "filter": null } }
    ]},
    { "id": "A1", "kind": "audio", "clips": [] },
    { "id": "A2", "kind": "audio", "clips": [] }
  ]
}
```

- `start` — position on the timeline (seconds). `in`/`out` — trim points into the source media. Clip timeline duration = `(out - in) / speed`.
- Track order in the array = compositing order (first = topmost video track).
- `type: "image"` media get an implicit infinite source; `out - in` is display duration.
- Undo/redo: stack of `structuredClone` snapshots, capped at 50.
- Autosave: serialized to `localStorage` on every mutation (debounced); restored on load if the session's media files still exist.

## 2. Layout & theme

- Route: `GET /editor` → `templates/editor.html`. Old slideshow stays at `/`.
- CSS grid: media pool (top-left), program monitor (top-center/right), inspector + automation sidebar (right column), timeline (bottom, full width). Panels resizable via CSS `resize` where cheap; fixed proportions otherwise.
- Theme: Tailwind CDN, zinc-900/950 surfaces, zinc-700 borders, accent `#7c3aed` (purple) for selection, playhead, active states. One small custom stylesheet (`static/editor.css`) for timeline specifics.
- Frontend code: vanilla ES modules under `static/editor/` (e.g. `state.js`, `timeline.js`, `monitor.js`, `mediapool.js`, `export.js`). No bundler.

## 3. Media pool

- Drag-and-drop or file picker → `POST /api/media` (multipart). Server: per-session folder under `temp_uploads/<session>/`, ffprobe for duration/dimensions, thumbnail JPEG (first frame / image resize / generic icon for audio), returns media metadata JSON.
- `GET /api/media/<session>/<id>` streams the file **with HTTP Range support** (required for `<video>` seeking).
- Accepted types: video (mp4, mov, webm, mkv), audio (mp3, wav, m4a, flac, ogg), image (existing supported list incl. HEIC — reuse `video_engine.read_image_safe` helpers). Reject others server-side with a clear error; client shows a toast. Size cap: 2 GB per file.
- Pool UI: thumbnail grid, name + duration badge, click to preview in monitor, drag onto a timeline track to insert a clip, delete button (removes media and any clips referencing it, with confirm).

## 4. Timeline

- Tracks V2, V1, A1, A2 as fixed lanes (adding tracks is out of scope). Header column with track name + mute toggle (audio) / hide toggle (video).
- Clips: absolutely-positioned divs, width = `duration × pixelsPerSecond`. Video clips show name + filmstrip-colored body; audio clips show a waveform.
- Waveforms: client-side via Web Audio `decodeAudioData` → downsampled min/max peaks → drawn to a per-clip `<canvas>`. Peaks cached per media id. No server involvement.
- Interactions:
  - Drag clip to move (within track and across same-kind tracks); snapping to clip edges, playhead, and t=0 (±8px threshold, disable with Alt).
  - Drag left/right clip edge to trim (`in`/`out` clamped to source duration).
  - `S` splits selected clip at playhead; `Delete` removes selection; `Ctrl+Z`/`Ctrl+Shift+Z` undo/redo; `Space` play/pause.
  - Overlaps within a track are disallowed: a drop that overlaps pushes the clip to the nearest free spot.
- Ruler with time labels; scroll-wheel = horizontal scroll, `Ctrl`+wheel = zoom (pixelsPerSecond 2–500); draggable playhead.
- Selected clip's properties (in/out/speed/opacity/filter) shown in the inspector sidebar, editable as numeric fields.

## 5. Program monitor (client-side approximate playback)

- One hidden `<video>`/`<audio>` element per media item, created lazily.
- A `requestAnimationFrame` loop maps timeline time → active clip per track → per-clip source time (`in + (t - start) × speed`). Topmost active video clip is displayed (swap visible element); all active audio elements play, mixed natively by the browser.
- Approximations: `opacity` and `filter` applied as CSS; `speed` via `playbackRate`. No compositing of two simultaneous video tracks in preview — topmost wins. UI labels the monitor "editing preview — export is exact".
- Transport: play/pause (space), frame step ±1/fps, J-K-L (reverse not supported — J stops, K pause, L cycles 1×/2×/4×), timecode display, click/drag to scrub with seek-throttling.
- Seek tolerance: browsers seek to keyframes; acceptable for editing preview.

## 6. Export (server-side, exact)

- `POST /api/export` body = full project JSON. Server validates (media ids exist, numbers sane), spawns a background thread, returns `{ "job": "<id>" }`.
- New module `timeline_renderer.py`:
  - Per clip: `VideoFileClip/AudioFileClip/ImageClip` → `.subclip(in, out)` → speed via `vfx.speedx` → `.set_start(start)` → `.set_opacity(...)`; letterbox/scale each source to project resolution.
  - `CompositeVideoClip` (track order = z-order) + `CompositeAudioClip`; write MP4 using the existing `get_best_video_codec()` from `video_engine.py` (NVENC fallback logic reused, not duplicated).
  - Progress: MoviePy logger callback updates a module-level jobs dict `{id: {state, percent, error}}`.
- `GET /api/export/<job>/status` → polling. `GET /api/export/<job>/download` → `send_file`, deletes file after send (same pattern as current `/create`).
- One export at a time — global lock, second request gets 409. `# ponytail: global lock; job queue if concurrent users ever matter.`
- Failed jobs record the exception string in status and delete partial output.

## 7. Automation sidebar (stubs only in phase 1)

Sidebar section "Automation" with four buttons: Auto-Montage, Smart Trim, Auto-Slideshow, Aspect Presets — all disabled with "coming soon" tooltips. Phase 2 wires each to endpoints that return clip placements merged into the project JSON (Auto-Slideshow will be a refactored entry point into `video_engine.py` that returns placements instead of writing an MP4).

## 8. Error handling

- Uploads: type/size rejection server-side → 4xx JSON message → toast.
- Export: validation errors → 400 with details; runtime errors → job status `failed` with message; partial files cleaned.
- Media element decode failure in preview: clip rendered in red "offline" state; playback skips it rather than throwing.
- Session folder missing after restart (temp cleanup): media pool marks items offline, prompts re-upload.

## 9. Testing

- `test_timeline_renderer.py`: build a small project JSON from programmatically generated color/tone clips, render at low res, assert file exists and duration matches expectation within ±0.2 s. Runnable with plain `python -m pytest` or as a `__main__` self-check. No frontend test harness — manual verification via preview.

## 10. Out of scope (phase 1)

Transitions between clips, keyframes, timeline text/titles, added/removed tracks, multiple saved projects, auth/multi-user, real automation features, two-video-track compositing in the *preview* (export composites correctly).

## File changes summary

| File | Change |
|---|---|
| `templates/editor.html` | New — editor page shell |
| `static/editor.css`, `static/editor/*.js` | New — frontend modules |
| `timeline_renderer.py` | New — project JSON → MP4 |
| `app.py` | Add `/editor`, `/api/media*`, `/api/export*` routes |
| `video_engine.py` | Untouched except importing `get_best_video_codec` |
| `test_timeline_renderer.py` | New — render smoke test |
