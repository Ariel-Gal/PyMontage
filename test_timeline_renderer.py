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
                {"id": "c2", "mediaId": "m2", "start": 1.5, "in": 0.5, "out": 1.0,
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
