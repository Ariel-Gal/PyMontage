# PyMontage Editor Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Premiere-style editor at `/editor` — media pool, multi-track timeline (V2/V1/A1/A2), client-side preview monitor, server-side MoviePy export — driven by one project-JSON model.

**Architecture:** Browser owns the project JSON (source of truth, undo/redo, localStorage autosave). Flask gains a small API: media upload/streaming and an export job runner. New `timeline_renderer.py` turns project JSON into an MP4 via MoviePy. Frontend is vanilla ES modules + Tailwind CDN, no build step. Spec: `docs/superpowers/specs/2026-07-05-editor-timeline-design.md`.

**Tech Stack:** Flask 3, MoviePy 1.0.3, Pillow, vanilla JS (ES modules), Tailwind via CDN, Web Audio API for waveforms.

## Global Constraints

- No new Python or JS dependencies. No node toolchain.
- Old slideshow UI at `/` stays untouched; editor lives at `/editor`.
- Theme: zinc-900/950 surfaces, accent `#7c3aed`.
- Tracks fixed: V2, V1, A1, A2. First video track in array = topmost at composite.
- One export at a time (global lock → 409 for a second request).
- Upload cap 2 GB; accepted types per spec §3.
- Python tests run with `venv\Scripts\python -m pytest` from repo root (Windows).
- Commit after every task; messages in imperative mood.

---

### Task 1: Timeline renderer (project JSON → MP4)

**Files:**
- Create: `timeline_renderer.py`
- Test: `test_timeline_renderer.py`

**Interfaces:**
- Consumes: `video_engine.get_best_video_codec() -> str`
- Produces: `render_project(project: dict, media_paths: dict[str, str], output_path: str, progress_cb: callable | None = None) -> None` (raises `ValueError` on empty timeline). `media_paths` maps media id → absolute file path. Later tasks (export API) call exactly this.

- [ ] **Step 1: Write the failing test**

```python
# test_timeline_renderer.py
import os
import pytest
from moviepy.editor import ColorClip, VideoFileClip

from timeline_renderer import render_project


@pytest.fixture
def two_clip_project(tmp_path):
    """Two generated color videos placed back-to-back on V1."""
    paths = {}
    for mid, color in (("m1", (255, 0, 0)), ("m2", (0, 0, 255))):
        p = str(tmp_path / f"{mid}.mp4")
        ColorClip((64, 64), color=color, duration=2).write_videofile(
            p, fps=10, codec="libx264", audio=False, logger=None)
        paths[mid] = p
    project = {
        "settings": {"width": 128, "height": 72, "fps": 10},
        "media": [
            {"id": "m1", "name": "m1.mp4", "type": "video", "duration": 2.0},
            {"id": "m2", "name": "m2.mp4", "type": "video", "duration": 2.0},
        ],
        "tracks": [
            {"id": "V2", "kind": "video", "clips": []},
            {"id": "V1", "kind": "video", "clips": [
                {"id": "c1", "mediaId": "m1", "start": 0.0, "in": 0.0, "out": 1.5,
                 "effects": {"speed": 1.0, "opacity": 1.0, "filter": None}},
                {"id": "c2", "mediaId": "m2", "start": 1.5, "in": 0.5, "out": 2.0,
                 "effects": {"speed": 1.0, "opacity": 1.0, "filter": None}},
            ]},
            {"id": "A1", "kind": "audio", "clips": []},
            {"id": "A2", "kind": "audio", "clips": []},
        ],
    }
    return project, paths


def test_render_two_clips(two_clip_project, tmp_path):
    project, paths = two_clip_project
    out = str(tmp_path / "out.mp4")
    percents = []
    render_project(project, paths, out, progress_cb=percents.append)
    assert os.path.exists(out)
    with VideoFileClip(out) as clip:
        assert clip.duration == pytest.approx(2.0, abs=0.2)  # 1.5 + 0.5
        assert clip.size == [128, 72]
    assert percents and percents[-1] > 0.5


def test_empty_timeline_raises(two_clip_project, tmp_path):
    project, paths = two_clip_project
    for t in project["tracks"]:
        t["clips"] = []
    with pytest.raises(ValueError):
        render_project(project, paths, str(tmp_path / "x.mp4"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv\Scripts\python -m pytest test_timeline_renderer.py -v`
Expected: FAIL / ERROR with `ModuleNotFoundError: No module named 'timeline_renderer'`

- [ ] **Step 3: Write the implementation**

```python
# timeline_renderer.py
"""Render a project JSON (see spec §1) to an MP4 with MoviePy."""
from moviepy.editor import (AudioFileClip, ColorClip, CompositeAudioClip,
                            CompositeVideoClip, ImageClip, VideoFileClip, vfx)
from proglog import ProgressBarLogger

from video_engine import get_best_video_codec


class _JobLogger(ProgressBarLogger):
    """Forwards MoviePy's frame-writing progress to a 0..1 callback."""

    def __init__(self, cb):
        super().__init__()
        self._cb = cb

    def bars_callback(self, bar, attr, value, old_value=None):
        total = self.bars[bar].get("total")
        if attr == "index" and total:
            self._cb(value / total)


def _build_clip(spec, media, path, size):
    effects = spec.get("effects") or {}
    speed = effects.get("speed") or 1.0
    opacity = effects.get("opacity", 1.0)
    if media["type"] == "audio":
        clip = AudioFileClip(path).subclip(spec["in"], spec["out"])
        return clip.set_start(spec["start"])
    if media["type"] == "image":
        clip = ImageClip(path).set_duration((spec["out"] - spec["in"]) / speed)
    else:
        clip = VideoFileClip(path).subclip(spec["in"], spec["out"])
        if speed != 1.0:
            clip = clip.fx(vfx.speedx, speed)
    scale = min(size[0] / clip.w, size[1] / clip.h)  # letterbox: fit inside frame
    clip = clip.resize(scale).set_position("center")
    if opacity is not None and opacity < 1.0:
        clip = clip.set_opacity(opacity)
    return clip.set_start(spec["start"])


def render_project(project, media_paths, output_path, progress_cb=None):
    settings = project["settings"]
    size = (settings["width"], settings["height"])
    media_by_id = {m["id"]: m for m in project["media"]}

    video_clips, audio_clips = [], []
    video_tracks = [t for t in project["tracks"] if t["kind"] == "video"]
    for track in reversed(video_tracks):  # composite order: later = on top, first track topmost
        for spec in track["clips"]:
            m = media_by_id[spec["mediaId"]]
            video_clips.append(_build_clip(spec, m, media_paths[m["id"]], size))
    for track in project["tracks"]:
        if track["kind"] != "audio":
            continue
        for spec in track["clips"]:
            m = media_by_id[spec["mediaId"]]
            audio_clips.append(_build_clip(spec, m, media_paths[m["id"]], size))

    if not video_clips and not audio_clips:
        raise ValueError("Timeline is empty")

    end = max(c.end for c in video_clips + audio_clips)
    base = ColorClip(size, color=(0, 0, 0), duration=end)
    video = CompositeVideoClip([base] + video_clips, size=size).set_duration(end)
    audio_parts = list(audio_clips)
    if video.audio is not None:
        audio_parts.insert(0, video.audio)
    if audio_parts:
        video = video.set_audio(CompositeAudioClip(audio_parts).set_duration(end))

    video.write_videofile(
        output_path,
        fps=settings["fps"],
        codec=get_best_video_codec(),
        audio_codec="aac",
        threads=4,
        logger=_JobLogger(progress_cb) if progress_cb else None,
    )
    video.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `venv\Scripts\python -m pytest test_timeline_renderer.py -v`
Expected: 2 passed (takes ~30–60 s; MoviePy renders twice)

- [ ] **Step 5: Commit**

```bash
git add timeline_renderer.py test_timeline_renderer.py
git commit -m "feat: add timeline renderer (project JSON to MP4)"
```

---

### Task 2: Media API (upload, probe, stream, thumbnail)

**Files:**
- Modify: `app.py` (add routes after the existing `/fonts/download` route, ~line 125)
- Test: `test_media_api.py`

**Interfaces:**
- Produces:
  - `POST /api/media` — multipart `file` + form `session` (UUID string). Returns `{id, name, type, duration, width, height, url}` (width/height 0 for audio). 400 on bad session/type.
  - `GET /api/media/<session>/<media_id>` — streams file with Range support.
  - `GET /api/media/<session>/<media_id>/thumb` — JPEG thumbnail (404 for audio).
  - Helper `resolve_media_path(session, media_id) -> str | None` used by Task 3.

- [ ] **Step 1: Write the failing test**

```python
# test_media_api.py
import io
import uuid

import pytest
from PIL import Image

from app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    return app.test_client()


def _png_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (320, 200), (255, 0, 0)).save(buf, format="PNG")
    buf.seek(0)
    return buf


def test_upload_and_stream_image(client):
    session = str(uuid.uuid4())
    resp = client.post("/api/media", data={
        "session": session,
        "file": (_png_bytes(), "red.png"),
    })
    assert resp.status_code == 200
    meta = resp.get_json()
    assert meta["type"] == "image"
    assert meta["width"] == 320 and meta["height"] == 200
    assert meta["duration"] == 5.0

    got = client.get(meta["url"])
    assert got.status_code == 200

    partial = client.get(meta["url"], headers={"Range": "bytes=0-9"})
    assert partial.status_code == 206  # Range support required for <video> seeking

    thumb = client.get(meta["url"] + "/thumb")
    assert thumb.status_code == 200
    assert thumb.mimetype == "image/jpeg"


def test_rejects_bad_session_and_type(client):
    resp = client.post("/api/media", data={
        "session": "../../etc", "file": (_png_bytes(), "red.png")})
    assert resp.status_code == 400
    resp = client.post("/api/media", data={
        "session": str(uuid.uuid4()), "file": (io.BytesIO(b"x"), "evil.exe")})
    assert resp.status_code == 400


def test_missing_media_404(client):
    assert client.get(f"/api/media/{uuid.uuid4()}/deadbeef").status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv\Scripts\python -m pytest test_media_api.py -v`
Expected: FAIL — 404s on `/api/media` routes

- [ ] **Step 3: Add media API to app.py**

Add near the top of `app.py` (with the other imports):

```python
import glob
import re
from PIL import Image
```

Add after the folder setup (`os.makedirs(app.config['OUTPUT_FOLDER'], ...)`):

```python
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 ** 3  # 2 GB upload cap

UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
MEDIA_EXTS = {
    'video': {'.mp4', '.mov', '.webm', '.mkv'},
    'audio': {'.mp3', '.wav', '.m4a', '.flac', '.ogg'},
    'image': {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tif', '.tiff',
              '.webp', '.heic', '.heif'},
}


def media_type_for(ext):
    for mtype, exts in MEDIA_EXTS.items():
        if ext in exts:
            return mtype
    return None


def resolve_media_path(session, media_id):
    """Return the stored file for a media id, or None. Validates both parts."""
    if not UUID_RE.match(session or '') or not re.match(r'^[0-9a-f]{32}$', media_id or ''):
        return None
    folder = os.path.join(app.config['UPLOAD_FOLDER'], session)
    matches = [p for p in glob.glob(os.path.join(folder, media_id + '.*'))
               if not p.endswith('.thumb.jpg')]
    return matches[0] if matches else None


def probe_media(path, mtype):
    if mtype == 'image':
        with Image.open(path) as im:
            return {'duration': 5.0, 'width': im.width, 'height': im.height}
    from moviepy.editor import AudioFileClip, VideoFileClip
    if mtype == 'video':
        with VideoFileClip(path) as clip:
            return {'duration': round(clip.duration, 3),
                    'width': clip.w, 'height': clip.h}
    with AudioFileClip(path) as clip:
        return {'duration': round(clip.duration, 3), 'width': 0, 'height': 0}
```

Add the routes after `/fonts/download`:

```python
@app.route('/editor')
def editor():
    return render_template('editor.html')


@app.route('/api/media', methods=['POST'])
def upload_media():
    session = request.form.get('session', '')
    if not UUID_RE.match(session):
        return jsonify({'error': 'Invalid session'}), 400
    file = request.files.get('file')
    if not file or not file.filename:
        return jsonify({'error': 'No file'}), 400
    ext = os.path.splitext(file.filename)[1].lower()
    mtype = media_type_for(ext)
    if not mtype:
        return jsonify({'error': f'Unsupported file type: {ext}'}), 400

    folder = os.path.join(app.config['UPLOAD_FOLDER'], session)
    os.makedirs(folder, exist_ok=True)
    media_id = uuid.uuid4().hex
    path = os.path.join(folder, media_id + ext)
    file.save(path)
    try:
        meta = probe_media(path, mtype)
    except Exception as e:
        os.remove(path)
        return jsonify({'error': f'Could not read file: {e}'}), 400
    return jsonify({'id': media_id, 'name': file.filename, 'type': mtype,
                    'url': f'/api/media/{session}/{media_id}', **meta})


@app.route('/api/media/<session>/<media_id>')
def get_media(session, media_id):
    path = resolve_media_path(session, media_id)
    if not path:
        return jsonify({'error': 'Not found'}), 404
    return send_file(path, conditional=True)  # conditional=True → Range support


@app.route('/api/media/<session>/<media_id>/thumb')
def get_media_thumb(session, media_id):
    path = resolve_media_path(session, media_id)
    if not path:
        return jsonify({'error': 'Not found'}), 404
    mtype = media_type_for(os.path.splitext(path)[1].lower())
    if mtype == 'audio':
        return jsonify({'error': 'No thumbnail for audio'}), 404
    thumb = os.path.join(os.path.dirname(path), media_id + '.thumb.jpg')
    if not os.path.exists(thumb):
        if mtype == 'image':
            with Image.open(path) as im:
                im = im.convert('RGB')
                im.thumbnail((160, 160))
                im.save(thumb, 'JPEG')
        else:
            ffmpeg = shutil.which('ffmpeg')
            if not ffmpeg:
                import imageio_ffmpeg
                ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
            import subprocess
            subprocess.run([ffmpeg, '-y', '-ss', '0.5', '-i', path,
                            '-frames:v', '1', '-vf', 'scale=160:-2', thumb],
                           capture_output=True, timeout=30)
            if not os.path.exists(thumb):
                return jsonify({'error': 'Thumbnail failed'}), 500
    return send_file(thumb, mimetype='image/jpeg')
```

(`templates/editor.html` does not exist yet — the `/editor` route 500s until Task 4; the tests here don't touch it.)

- [ ] **Step 4: Run test to verify it passes**

Run: `venv\Scripts\python -m pytest test_media_api.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add app.py test_media_api.py
git commit -m "feat: add media upload/stream/thumbnail API"
```

---

### Task 3: Export job API

**Files:**
- Modify: `app.py` (append after the media routes)
- Test: `test_export_api.py`

**Interfaces:**
- Consumes: `timeline_renderer.render_project`, `resolve_media_path` (Task 2).
- Produces:
  - `POST /api/export` body `{"session": "<uuid>", "project": {...}}` → `{"job": "<id>"}`; 400 on invalid payload, 409 if an export is running.
  - `GET /api/export/<job>/status` → `{"state": "running|done|failed", "percent": int, "error": str|null}`; 404 unknown job.
  - `GET /api/export/<job>/download` → MP4 attachment, file deleted after send; 404/409 otherwise.

- [ ] **Step 1: Write the failing test**

```python
# test_export_api.py
import time
import uuid

import pytest

import app as app_module
from app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    return app.test_client()


def _project(media=(), tracks=None):
    return {
        "settings": {"width": 128, "height": 72, "fps": 10},
        "media": list(media),
        "tracks": tracks or [
            {"id": "V1", "kind": "video", "clips": []},
            {"id": "A1", "kind": "audio", "clips": []},
        ],
    }


def test_rejects_invalid_payloads(client):
    assert client.post("/api/export", json={}).status_code == 400
    assert client.post("/api/export", json={
        "session": "bad", "project": _project()}).status_code == 400
    # references a media id that was never uploaded
    proj = _project(
        media=[{"id": "nope" * 8, "type": "video", "duration": 1}],
        tracks=[{"id": "V1", "kind": "video", "clips": [
            {"id": "c1", "mediaId": "nope" * 8, "start": 0, "in": 0, "out": 1,
             "effects": {}}]}])
    resp = client.post("/api/export", json={
        "session": str(uuid.uuid4()), "project": proj})
    assert resp.status_code == 400


def test_job_lifecycle_and_lock(client, monkeypatch, tmp_path):
    session = str(uuid.uuid4())
    media_id = uuid.uuid4().hex
    src = tmp_path / "fake.mp4"
    src.write_bytes(b"x")
    monkeypatch.setattr(app_module, "resolve_media_path",
                        lambda s, m: str(src))

    started = []

    def fake_render(project, media_paths, output_path, progress_cb=None):
        started.append(output_path)
        progress_cb(0.5)
        time.sleep(0.5)
        with open(output_path, "wb") as f:
            f.write(b"video")

    monkeypatch.setattr(app_module, "render_project", fake_render)

    proj = _project(
        media=[{"id": media_id, "type": "video", "duration": 1}],
        tracks=[{"id": "V1", "kind": "video", "clips": [
            {"id": "c1", "mediaId": media_id, "start": 0, "in": 0, "out": 1,
             "effects": {}}]}])
    resp = client.post("/api/export", json={"session": session, "project": proj})
    assert resp.status_code == 200
    job = resp.get_json()["job"]

    # second export while first runs → 409
    resp2 = client.post("/api/export", json={"session": session, "project": proj})
    assert resp2.status_code == 409

    for _ in range(50):
        status = client.get(f"/api/export/{job}/status").get_json()
        if status["state"] == "done":
            break
        time.sleep(0.1)
    assert status["state"] == "done"
    assert status["percent"] == 100

    dl = client.get(f"/api/export/{job}/download")
    assert dl.status_code == 200
    assert dl.data == b"video"


def test_unknown_job_404(client):
    assert client.get("/api/export/nope/status").status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `venv\Scripts\python -m pytest test_export_api.py -v`
Expected: FAIL — 404 on `/api/export`

- [ ] **Step 3: Add export API to app.py**

Add imports at top of `app.py`:

```python
import threading
from timeline_renderer import render_project
```

Append after the media routes:

```python
EXPORT_JOBS = {}
# ponytail: global lock, one export at a time; job queue if concurrent users ever matter
EXPORT_LOCK = threading.Lock()


def _validate_export(data):
    """Returns (session, project, media_paths) or raises ValueError."""
    session = data.get('session', '')
    project = data.get('project')
    if not UUID_RE.match(session) or not isinstance(project, dict):
        raise ValueError('Invalid session or project')
    for key in ('settings', 'media', 'tracks'):
        if key not in project:
            raise ValueError(f'Project missing "{key}"')
    s = project['settings']
    if not (16 <= int(s.get('width', 0)) <= 7680 and
            16 <= int(s.get('height', 0)) <= 4320 and
            1 <= int(s.get('fps', 0)) <= 120):
        raise ValueError('Invalid project settings')
    used_ids = {c['mediaId'] for t in project['tracks'] for c in t['clips']}
    media_paths = {}
    for mid in used_ids:
        path = resolve_media_path(session, mid)
        if not path:
            raise ValueError(f'Media {mid} not found on server')
        media_paths[mid] = path
    return session, project, media_paths


@app.route('/api/export', methods=['POST'])
def start_export():
    data = request.get_json(silent=True) or {}
    try:
        session, project, media_paths = _validate_export(data)
    except (ValueError, KeyError, TypeError) as e:
        return jsonify({'error': str(e)}), 400

    if not EXPORT_LOCK.acquire(blocking=False):
        return jsonify({'error': 'An export is already running'}), 409

    job_id = uuid.uuid4().hex
    output_path = os.path.join(app.config['OUTPUT_FOLDER'], f'export_{job_id}.mp4')
    EXPORT_JOBS[job_id] = {'state': 'running', 'percent': 0,
                           'error': None, 'path': output_path}

    def run():
        job = EXPORT_JOBS[job_id]
        try:
            render_project(project, media_paths, output_path,
                           progress_cb=lambda p: job.update(percent=int(p * 100)))
            job.update(state='done', percent=100)
        except Exception as e:
            job.update(state='failed', error=str(e))
            if os.path.exists(output_path):
                try:
                    os.remove(output_path)
                except OSError:
                    pass
        finally:
            EXPORT_LOCK.release()

    threading.Thread(target=run, daemon=True).start()
    return jsonify({'job': job_id})


@app.route('/api/export/<job_id>/status')
def export_status(job_id):
    job = EXPORT_JOBS.get(job_id)
    if not job:
        return jsonify({'error': 'Unknown job'}), 404
    return jsonify({'state': job['state'], 'percent': job['percent'],
                    'error': job['error']})


@app.route('/api/export/<job_id>/download')
def export_download(job_id):
    job = EXPORT_JOBS.get(job_id)
    if not job:
        return jsonify({'error': 'Unknown job'}), 404
    if job['state'] != 'done':
        return jsonify({'error': 'Not finished'}), 409
    path = job['path']
    if not os.path.exists(path):
        return jsonify({'error': 'File gone'}), 404

    @after_this_request
    def cleanup(response):
        try:
            os.remove(path)
        except OSError:
            pass
        EXPORT_JOBS.pop(job_id, None)
        return response

    return send_file(path, as_attachment=True, download_name='export.mp4')
```

Note: `test_export_api.py` monkeypatches `app.render_project` and `app.resolve_media_path` — this works because `app.py` imports them into its own namespace.

- [ ] **Step 4: Run test to verify it passes**

Run: `venv\Scripts\python -m pytest test_export_api.py -v`
Expected: 3 passed

- [ ] **Step 5: Run all tests together**

Run: `venv\Scripts\python -m pytest -v`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add app.py test_export_api.py
git commit -m "feat: add export job API with progress and global lock"
```

---

### Task 4: Editor page shell (layout + theme)

**Files:**
- Create: `templates/editor.html`
- Create: `static/editor.css`

**Interfaces:**
- Produces: DOM ids used by all later frontend tasks: `#pool-list`, `#pool-drop`, `#monitor-video`, `#monitor-canvas-label`, `#transport`, `#tc`, `#btn-play`, `#btn-prev-frame`, `#btn-next-frame`, `#inspector-body`, `#automation`, `#btn-export`, `#export-progress`, `#timeline-scroll`, `#ruler`, `#tracks`, `#playhead`, `#monitor-pool`.

- [ ] **Step 1: Write templates/editor.html**

```html
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PyMontage Editor</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="stylesheet" href="{{ url_for('static', filename='editor.css') }}">
</head>
<body class="bg-zinc-950 text-zinc-200 h-screen overflow-hidden select-none">
  <div class="grid h-full"
       style="grid-template-rows: 1fr 340px;
              grid-template-columns: 280px 1fr 300px;
              grid-template-areas: 'pool monitor side' 'timeline timeline side';">

    <!-- Media pool -->
    <section style="grid-area: pool"
             class="border-r border-zinc-800 bg-zinc-900 flex flex-col min-h-0">
      <header class="px-3 py-2 text-xs font-semibold tracking-wider text-zinc-400 border-b border-zinc-800">
        MEDIA POOL
      </header>
      <div id="pool-drop"
           class="m-2 p-3 border border-dashed border-zinc-700 rounded text-center text-xs text-zinc-500 cursor-pointer hover:border-violet-500">
        Drop files here or click to upload
        <input id="pool-file" type="file" multiple class="hidden">
      </div>
      <div id="pool-list" class="flex-1 overflow-y-auto grid grid-cols-2 gap-2 p-2 content-start"></div>
    </section>

    <!-- Program monitor -->
    <section style="grid-area: monitor" class="bg-zinc-950 flex flex-col min-h-0">
      <div class="flex-1 relative flex items-center justify-center bg-black m-2 rounded overflow-hidden">
        <video id="monitor-video" class="max-h-full max-w-full" playsinline muted></video>
        <span id="monitor-canvas-label"
              class="absolute bottom-2 right-2 text-[10px] text-zinc-500 bg-zinc-900/80 px-2 py-0.5 rounded">
          editing preview — export is exact
        </span>
      </div>
      <div id="transport" class="flex items-center justify-center gap-3 pb-2">
        <button id="btn-prev-frame" class="tbtn" title="Previous frame (←)">⏮</button>
        <button id="btn-play" class="tbtn text-lg" title="Play/Pause (Space)">▶</button>
        <button id="btn-next-frame" class="tbtn" title="Next frame (→)">⏭</button>
        <span id="tc" class="font-mono text-sm text-violet-400 ml-3">00:00:00:00</span>
      </div>
    </section>

    <!-- Sidebar: inspector + automation + export -->
    <aside style="grid-area: side"
           class="border-l border-zinc-800 bg-zinc-900 flex flex-col min-h-0 overflow-y-auto">
      <header class="px-3 py-2 text-xs font-semibold tracking-wider text-zinc-400 border-b border-zinc-800">
        INSPECTOR
      </header>
      <div id="inspector-body" class="p-3 text-sm text-zinc-500">No clip selected</div>

      <header class="px-3 py-2 text-xs font-semibold tracking-wider text-zinc-400 border-y border-zinc-800">
        AUTOMATION
      </header>
      <div id="automation" class="p-3 flex flex-col gap-2">
        <button class="abtn" disabled title="Coming soon">🎵 Auto-Montage</button>
        <button class="abtn" disabled title="Coming soon">✂️ Smart Trim</button>
        <button class="abtn" disabled title="Coming soon">🖼 Auto-Slideshow</button>
        <button class="abtn" disabled title="Coming soon">📐 Aspect Presets</button>
      </div>

      <div class="mt-auto p-3 border-t border-zinc-800">
        <button id="btn-export"
                class="w-full py-2 rounded bg-violet-600 hover:bg-violet-500 text-white font-semibold">
          Export MP4
        </button>
        <div id="export-progress" class="hidden mt-2 text-xs text-zinc-400"></div>
      </div>
    </aside>

    <!-- Timeline -->
    <section style="grid-area: timeline"
             class="border-t border-zinc-800 bg-zinc-900 flex flex-col min-h-0">
      <div id="timeline-scroll" class="flex-1 overflow-x-auto overflow-y-hidden relative">
        <div id="ruler" class="h-6 relative border-b border-zinc-800 sticky-left"></div>
        <div id="tracks" class="relative"></div>
        <div id="playhead" class="absolute top-0 bottom-0 w-px bg-violet-500 z-30 pointer-events-none">
          <div class="w-3 h-3 bg-violet-500 -ml-1.5 rotate-45"></div>
        </div>
      </div>
    </section>
  </div>

  <div id="monitor-pool" class="hidden"></div>
  <script type="module" src="{{ url_for('static', filename='editor/main.js') }}"></script>
</body>
</html>
```

- [ ] **Step 2: Write static/editor.css**

```css
/* Timeline + widget styles that are awkward as utility classes */
.tbtn {
  padding: 2px 10px;
  border-radius: 4px;
  background: #27272a;         /* zinc-800 */
  color: #d4d4d8;
}
.tbtn:hover { background: #3f3f46; }

.abtn {
  padding: 6px 10px;
  border-radius: 4px;
  background: #27272a;
  color: #71717a;
  text-align: left;
  font-size: 13px;
  cursor: not-allowed;
}

.track {
  height: 56px;
  position: relative;
  border-bottom: 1px solid #27272a;
}
.track-header {
  position: sticky;
  left: 0;
  z-index: 20;
  width: 96px;
  height: 100%;
  background: #18181b;         /* zinc-900 */
  border-right: 1px solid #3f3f46;
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 8px;
  font-size: 11px;
  color: #a1a1aa;
  float: left;
}

.clip {
  position: absolute;
  top: 4px;
  height: 48px;
  border-radius: 4px;
  overflow: hidden;
  cursor: grab;
  font-size: 11px;
  color: #fafafa;
  border: 1px solid transparent;
}
.clip.video { background: #3730a3; }   /* indigo-800 */
.clip.image { background: #155e75; }   /* cyan-800 */
.clip.audio { background: #14532d; }   /* green-900 */
.clip.selected { border-color: #7c3aed; box-shadow: 0 0 0 1px #7c3aed; }
.clip.offline { background: #7f1d1d; } /* red-900 */
.clip .clip-label {
  position: absolute;
  top: 2px;
  left: 6px;
  right: 6px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  pointer-events: none;
}
.clip canvas { width: 100%; height: 100%; display: block; }
.clip .edge {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 6px;
  cursor: ew-resize;
  z-index: 5;
}
.clip .edge.left { left: 0; }
.clip .edge.right { right: 0; }

.ruler-tick {
  position: absolute;
  top: 0;
  bottom: 0;
  border-left: 1px solid #3f3f46;
  padding-left: 3px;
  font-size: 9px;
  color: #71717a;
}
```

- [ ] **Step 3: Create empty static/editor/main.js so the page loads without a 404**

```js
// static/editor/main.js
console.log('PyMontage editor loaded');
```

- [ ] **Step 4: Verify manually**

Run: `venv\Scripts\python app.py`, open `http://127.0.0.1:5000/editor`.
Expected: dark 4-panel layout — media pool left, black monitor center with transport, sidebar right (4 disabled automation buttons + purple Export button), timeline strip at the bottom. Console shows "PyMontage editor loaded", no 404s.

- [ ] **Step 5: Commit**

```bash
git add templates/editor.html static/editor.css static/editor/main.js
git commit -m "feat: add editor page shell with Premiere-style layout"
```

---

### Task 5: Frontend state module (project model, undo/redo, autosave)

**Files:**
- Create: `static/editor/state.js`
- Modify: `static/editor/main.js`

**Interfaces:**
- Produces (all later frontend tasks import from `./state.js`):
  - `state` — `{ session, project, selectedClipId, playhead, pixelsPerSecond, playing }`
  - `on(event, fn)` / `emit(event, data)` — events used: `'project'` (any model change), `'playhead'`, `'selection'`, `'previewMedia'`
  - `loadProject()`, `mutate(fn)`, `beginDrag()` → snapshot, `commitDrag(snapshot)`, `undo()`, `redo()`
  - `findClip(id) -> {clip, track} | null`, `findMedia(id)`, `clipDur(clip)`, `uid()`
  - `setPlayhead(t)`, `selectClip(idOrNull)`

- [ ] **Step 1: Write static/editor/state.js**

```js
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
```

- [ ] **Step 2: Replace static/editor/main.js**

```js
// static/editor/main.js
import { loadProject, state } from './state.js';

loadProject();
console.log('PyMontage editor loaded', state.session, state.project);
```

- [ ] **Step 3: Verify manually**

Reload `http://127.0.0.1:5000/editor`. Console shows the session UUID and a project object with 4 tracks. Reload again — same session UUID persists.

- [ ] **Step 4: Commit**

```bash
git add static/editor/state.js static/editor/main.js
git commit -m "feat: add editor state module with undo/redo and autosave"
```

---

### Task 6: Media pool (upload, thumbnails, drag source)

**Files:**
- Create: `static/editor/mediapool.js`
- Modify: `static/editor/main.js`

**Interfaces:**
- Consumes: `state, on, emit, mutate` from `./state.js`; `POST /api/media`, thumb URL (Task 2); DOM ids `#pool-drop`, `#pool-file`, `#pool-list` (Task 4).
- Produces: `initMediaPool()`. Dragging a pool item sets `dataTransfer 'application/x-pm-media'` = media id (Task 7 drops it). Clicking an item emits `'previewMedia'` with the media object (Task 8 listens). Adds `media` entries to the project (each also gets `offline: false`; set true if a HEAD request for its URL fails after reload).

- [ ] **Step 1: Write static/editor/mediapool.js**

```js
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
```

- [ ] **Step 2: Update static/editor/main.js**

```js
// static/editor/main.js
import { loadProject } from './state.js';
import { initMediaPool } from './mediapool.js';

loadProject();
initMediaPool();
```

- [ ] **Step 3: Verify manually**

Reload `/editor`. Upload an image, a short video, and an MP3 (click and drag-drop both). Expected: cards appear with thumbnails (🎵 for audio), name + duration; ✕ removes with confirm; an unsupported file (e.g. `.txt`) shows a red toast. Reload the page — media persists; restart Flask and reload — cards show "(offline)" with a toast.

- [ ] **Step 4: Commit**

```bash
git add static/editor/mediapool.js static/editor/main.js
git commit -m "feat: add media pool with upload, thumbnails, offline detection"
```

---

### Task 7: Timeline (tracks, clips, drag/trim/split, waveforms, zoom)

**Files:**
- Create: `static/editor/timeline.js`
- Modify: `static/editor/main.js`

**Interfaces:**
- Consumes: everything from `./state.js`; drop data `'application/x-pm-media'` (Task 6); DOM ids `#timeline-scroll`, `#ruler`, `#tracks`, `#playhead` (Task 4).
- Produces: `initTimeline()`. Keyboard handling for S/Delete/undo/redo lives here. Clip divs carry `data-clip-id`.

- [ ] **Step 1: Write static/editor/timeline.js**

```js
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
        if (target && target !== track && target.kind === track.kind) {
          track.clips = track.clips.filter(c => c.id !== clip.id);
          target.clips.push(clip);
          Object.assign(found, { track: target });
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
  if (e.target.tagName === 'INPUT') return;
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
```

- [ ] **Step 2: Update static/editor/main.js**

```js
// static/editor/main.js
import { loadProject } from './state.js';
import { initMediaPool } from './mediapool.js';
import { initTimeline } from './timeline.js';

loadProject();
initMediaPool();
initTimeline();
```

- [ ] **Step 3: Verify manually**

On `/editor` with media uploaded, check each:
1. Drag a video from the pool onto V1 → indigo clip appears; audio only drops on A1/A2 (green, waveform renders).
2. Drag clip left/right — snaps near another clip's edge and t=0; Alt disables snapping.
3. Drag clip edges — width changes; can't trim past source duration or below 0.1 s.
4. Click empty timeline — playhead moves. Select clip, press `S` at playhead inside it — splits into two.
5. `Delete` removes selection; `Ctrl+Z` / `Ctrl+Shift+Z` undo/redo all of the above.
6. `Ctrl`+wheel zooms; ruler labels stay readable; dropping one clip on another nudges it clear.
7. Track header 👁/🔊 buttons toggle red (hidden/muted state stored on the track; the monitor honors it in Task 8).

- [ ] **Step 4: Commit**

```bash
git add static/editor/timeline.js static/editor/main.js
git commit -m "feat: add multi-track timeline with drag, trim, split, waveforms"
```

---

### Task 8: Program monitor (client-side playback)

**Files:**
- Create: `static/editor/monitor.js`
- Modify: `static/editor/main.js`

**Interfaces:**
- Consumes: `state, on, setPlayhead, findMedia, clipDur` from `./state.js`; `'previewMedia'` event (Task 6); DOM ids `#monitor-video`, `#monitor-pool`, `#btn-play`, `#btn-prev-frame`, `#btn-next-frame`, `#tc` (Task 4).
- Produces: `initMonitor()`. Space/←/→/J/K/L handled here.

- [ ] **Step 1: Write static/editor/monitor.js**

```js
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
  const f = Math.floor((t % 1) * fps);
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
    const dt = (now - lastFrame) / 1000;
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
  if (!p) for (const el of elements.values()) el.pause();
  if (!p) screen.pause();
}

function onKey(e) {
  if (e.target.tagName === 'INPUT') return;
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
```

- [ ] **Step 2: Update static/editor/main.js**

```js
// static/editor/main.js
import { loadProject } from './state.js';
import { initMediaPool } from './mediapool.js';
import { initTimeline } from './timeline.js';
import { initMonitor } from './monitor.js';

loadProject();
initMediaPool();
initTimeline();
initMonitor();
```

- [ ] **Step 3: Verify manually**

1. Click a pool video → plays in monitor when pressing Space? (Space plays the *timeline*; pool click just loads the source — both behaviors present.)
2. Place two video clips and an audio clip on the timeline. Press Space at t=0 → playhead moves, monitor switches sources at the cut, audio plays under video.
3. ←/→ steps the timecode by one frame; scrubbing by dragging in an empty timeline area updates the picture.
4. `L` twice → 2× playback (timecode races); `K` pauses.
5. Timecode format `HH:MM:SS:FF` matches project fps.

- [ ] **Step 4: Commit**

```bash
git add static/editor/monitor.js static/editor/main.js
git commit -m "feat: add program monitor with client-side timeline playback"
```

---

### Task 9: Inspector + export UI

**Files:**
- Create: `static/editor/inspector.js`
- Create: `static/editor/export.js`
- Modify: `static/editor/main.js`

**Interfaces:**
- Consumes: `state, on, mutate, findClip, findMedia` from `./state.js`; `POST /api/export` + status/download routes (Task 3); DOM ids `#inspector-body`, `#btn-export`, `#export-progress` (Task 4).
- Produces: `initInspector()`, `initExport()`.

- [ ] **Step 1: Write static/editor/inspector.js**

```js
// static/editor/inspector.js
import { findClip, findMedia, mutate, on, state } from './state.js';

const body = document.getElementById('inspector-body');

const FIELDS = [
  { key: 'in', label: 'In (s)', step: 0.1 },
  { key: 'out', label: 'Out (s)', step: 0.1 },
  { key: 'start', label: 'Start (s)', step: 0.1 },
];
const EFFECTS = [
  { key: 'speed', label: 'Speed', step: 0.1, min: 0.1, max: 10 },
  { key: 'opacity', label: 'Opacity', step: 0.05, min: 0, max: 1 },
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
```

Note: `filter` is preview-approximate (CSS) and intentionally ignored by the exporter in phase 1 — matching spec §5/§10 (effects beyond speed/opacity are out of export scope).

- [ ] **Step 2: Write static/editor/export.js**

```js
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
```

- [ ] **Step 3: Update static/editor/main.js (final form)**

```js
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
```

- [ ] **Step 4: Verify manually (end-to-end)**

1. Select a clip → inspector shows In/Out/Start/Speed/Opacity/Filter; change Speed to 2 → clip halves on the timeline; set Filter grayscale → preview goes gray.
2. Build a small timeline (2 video clips + 1 audio clip), click **Export MP4** → progress % climbs → file downloads → downloaded MP4 matches the timeline (cuts at the right times, audio present, speed/opacity applied).
3. Click Export again while one runs (two tabs) → second shows "An export is already running".
4. Empty timeline → export shows a clear error, button re-enables.

- [ ] **Step 5: Run the full test suite one last time**

Run: `venv\Scripts\python -m pytest -v`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add static/editor/inspector.js static/editor/export.js static/editor/main.js
git commit -m "feat: add inspector panel and export UI"
```
