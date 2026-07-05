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
