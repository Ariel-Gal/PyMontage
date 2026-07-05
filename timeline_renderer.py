"""Render a project JSON (see docs/superpowers/specs/2026-07-05-editor-timeline-design.md §1) to an MP4."""
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
