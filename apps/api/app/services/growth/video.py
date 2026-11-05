"""Vertical 9:16 Reels built with FFmpeg and checked with ffprobe.

Output targets the published Reels container constraints: MP4, H.264 high
profile, yuv420p, closed GOP, 30 fps, 1080x1920, AAC 48 kHz stereo, and the
moov atom before mdat. A missing FFmpeg binary is NOT_CONFIGURED; nothing is
faked.
"""

from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
import tempfile
from dataclasses import dataclass

from app.core.config import get_settings

WIDTH = 1080
HEIGHT = 1920
FPS = 30
TRANSITION = 0.5
MAX_BYTES = 300 * 1024 * 1024
MAX_VIDEO_BITRATE = 25_000_000


class VideoUnavailable(RuntimeError):
    """FFmpeg is missing or refused the job."""


@dataclass(frozen=True)
class Tools:
    ffmpeg: str
    ffprobe: str


def tools() -> Tools:
    settings = get_settings()
    ffmpeg = settings.ffmpeg_path.strip() or shutil.which("ffmpeg") or ""
    ffprobe = settings.ffprobe_path.strip() or shutil.which("ffprobe") or ""
    if not ffmpeg or not os.path.isfile(ffmpeg) or not ffprobe or not os.path.isfile(ffprobe):
        raise VideoUnavailable("NOT_CONFIGURED. FFmpeg and ffprobe are required for Reels. Install ffmpeg or set FFMPEG_PATH and FFPROBE_PATH.")
    return Tools(ffmpeg=ffmpeg, ffprobe=ffprobe)


def build_reel(frames: list[bytes], *, seconds: list[float]) -> bytes:
    """Each frame is a 1080x1920 image shown for its seconds with a slow push-in and crossfades."""
    if not frames or len(frames) != len(seconds):
        raise VideoUnavailable("A reel needs at least one frame and one duration per frame.")
    found = tools()
    with tempfile.TemporaryDirectory(prefix="growth-reel-") as workdir:
        inputs: list[str] = []
        filters: list[str] = []
        for index, (data, duration) in enumerate(zip(frames, seconds, strict=True)):
            path = os.path.join(workdir, f"frame_{index:03d}.jpg")
            with open(path, "wb") as handle:
                handle.write(data)
            inputs += ["-i", path]
            count = max(1, int(round(duration * FPS)))
            filters.append(
                f"[{index}:v]scale={WIDTH * 2}:{HEIGHT * 2}:out_range=tv,"
                f"zoompan=z='min(zoom+0.0006,1.08)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={count}:s={WIDTH}x{HEIGHT}:fps={FPS},"
                f"setsar=1,format=yuv420p[v{index}]"
            )
        label = "v0"
        elapsed = seconds[0]
        for index in range(1, len(frames)):
            offset = round(elapsed - TRANSITION, 3)
            filters.append(f"[{label}][v{index}]xfade=transition=fade:duration={TRANSITION}:offset={offset}[x{index}]")
            label = f"x{index}"
            elapsed = elapsed + seconds[index] - TRANSITION
        total = round(elapsed, 3)
        output = os.path.join(workdir, "reel.mp4")
        command = [
            found.ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            *inputs,
            "-f",
            "lavfi",
            "-t",
            str(total),
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-filter_complex",
            ";".join(filters),
            "-map",
            f"[{label}]",
            "-map",
            f"{len(frames)}:a",
            "-c:v",
            "libx264",
            "-profile:v",
            "high",
            "-preset",
            "medium",
            "-crf",
            "20",
            "-maxrate",
            "12M",
            "-bufsize",
            "24M",
            "-pix_fmt",
            "yuv420p",
            "-color_range",
            "tv",
            "-r",
            str(FPS),
            "-g",
            str(FPS * 2),
            "-keyint_min",
            str(FPS * 2),
            "-sc_threshold",
            "0",
            "-flags",
            "+cgop",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-t",
            str(total),
            "-movflags",
            "+faststart",
            output,
        ]
        try:
            completed = subprocess.run(command, capture_output=True, timeout=240, check=False)  # noqa: S603 - fixed argument list, no shell
        except subprocess.TimeoutExpired as exc:
            raise VideoUnavailable("FFmpeg timed out building the reel.") from exc
        if completed.returncode != 0 or not os.path.isfile(output):
            tail = completed.stderr.decode("utf-8", "replace")[-400:]
            raise VideoUnavailable(f"FFmpeg could not build the reel: {tail}")
        with open(output, "rb") as handle:
            return handle.read()


def probe(data: bytes) -> dict:
    found = tools()
    with tempfile.TemporaryDirectory(prefix="growth-probe-") as workdir:
        path = os.path.join(workdir, "probe.mp4")
        with open(path, "wb") as handle:
            handle.write(data)
        completed = subprocess.run(  # noqa: S603 - fixed argument list, no shell
            [found.ffprobe, "-v", "error", "-print_format", "json", "-show_streams", "-show_format", path],
            capture_output=True,
            timeout=60,
            check=False,
        )
    if completed.returncode != 0:
        raise VideoUnavailable("ffprobe could not read the file.")
    return json.loads(completed.stdout.decode("utf-8", "replace") or "{}")


def top_level_boxes(data: bytes) -> list[str]:
    boxes: list[str] = []
    index = 0
    while index + 8 <= len(data) and len(boxes) < 64:
        size, kind = struct.unpack(">I4s", data[index : index + 8])
        if size == 1 and index + 16 <= len(data):
            size = struct.unpack(">Q", data[index + 8 : index + 16])[0]
        boxes.append(kind.decode("latin-1"))
        if size < 8:
            break
        index += size
    return boxes


def _rate(value: str) -> float:
    try:
        top, bottom = value.split("/")
        return float(top) / float(bottom) if float(bottom) else 0.0
    except (ValueError, ZeroDivisionError):
        return 0.0


def check_reel(data: bytes, *, max_seconds: int) -> dict:
    """Return passed or failed with every check that ran. A failed probe is a failed check."""
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    try:
        info = probe(data)
    except (VideoUnavailable, ValueError) as exc:
        return {"state": "failed", "checks": [{"name": "probe", "ok": False, "detail": str(exc)}]}
    streams = info.get("streams") or []
    video = next((item for item in streams if item.get("codec_type") == "video"), {})
    audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
    fmt = info.get("format") or {}
    duration = float(fmt.get("duration") or video.get("duration") or 0)
    fps = _rate(str(video.get("avg_frame_rate") or "0/1"))
    width, height = int(video.get("width") or 0), int(video.get("height") or 0)
    bitrate = int(video.get("bit_rate") or fmt.get("bit_rate") or 0)
    boxes = top_level_boxes(data)
    check("container", "mp4" in str(fmt.get("format_name") or ""), str(fmt.get("format_name") or "unknown"))
    check("video_codec", video.get("codec_name") == "h264", str(video.get("codec_name") or "none"))
    check("pixel_format", video.get("pix_fmt") == "yuv420p", str(video.get("pix_fmt") or "none"))
    check("dimensions_9_16", (width, height) == (WIDTH, HEIGHT), f"{width}x{height}")
    check("frame_rate", 23 <= fps <= 60, f"{fps:.2f} fps")
    check("duration", 3 <= duration <= max_seconds, f"{duration:.2f} s (3-{max_seconds} s)")
    check("video_bitrate", 0 < bitrate <= MAX_VIDEO_BITRATE, f"{bitrate} bit/s")
    check("audio_codec", audio is not None and audio.get("codec_name") == "aac", str((audio or {}).get("codec_name") or "none"))
    check("audio_sample_rate", audio is not None and int(audio.get("sample_rate") or 0) <= 48000, str((audio or {}).get("sample_rate") or "none"))
    check("audio_channels", audio is not None and int(audio.get("channels") or 0) in {1, 2}, str((audio or {}).get("channels") or "none"))
    moov_first = "moov" in boxes and "mdat" in boxes and boxes.index("moov") < boxes.index("mdat")
    check("faststart", moov_first, " ".join(boxes[:6]))
    check("file_size", len(data) <= MAX_BYTES, f"{len(data)} bytes")
    return {
        "state": "passed" if all(item["ok"] for item in checks) else "failed",
        "checks": checks,
        "duration_ms": int(duration * 1000),
        "width": width,
        "height": height,
    }
