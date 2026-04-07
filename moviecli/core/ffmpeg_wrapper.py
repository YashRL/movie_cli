"""FFmpeg execution helpers."""

import subprocess
import shutil
from pathlib import Path


def ffmpeg(*args: str) -> None:
    """Run ffmpeg with given args. Raises on non-zero exit."""
    cmd = ["ffmpeg", "-y", *args]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr)


def probe(path: str) -> dict:
    """Return ffprobe JSON for a file."""
    import json
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", "-show_format", path],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Cannot probe {path}: {result.stderr}")
    return json.loads(result.stdout)


def video_info(path: str) -> dict:
    """Return width, height, fps, duration of the video stream."""
    data = probe(path)
    vs = next(s for s in data["streams"] if s["codec_type"] == "video")
    fps_parts = vs["r_frame_rate"].split("/")
    fps = int(fps_parts[0]) / int(fps_parts[1])
    return {
        "width": int(vs["width"]),
        "height": int(vs["height"]),
        "fps": fps,
        "duration": float(data["format"]["duration"]),
    }


def require_ffmpeg() -> None:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found. Install it or activate the movie conda env.")
