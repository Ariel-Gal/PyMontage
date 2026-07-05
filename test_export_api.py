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

    def fake_render(project, media_paths, output_path, progress_cb=None):
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

    # second export while first runs -> 409
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
