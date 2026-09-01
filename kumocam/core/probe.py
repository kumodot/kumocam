"""Metadata probing for DJI Osmo Pocket media files.

Videos are probed with ffprobe (bundled with FFmpeg). Photos are read with
the pure-python exifread library, so no external tool is needed for images.

Key DJI facts (validated on real Osmo Pocket 4P files):
- MP4 format tags carry 'com.dji.camera.ColorGammaSxS' = 'D-Log' | 'Rec.709'
  and 'encoder' = 'DJI OsmoPocket4P'.
- Vertical clips are stored with real portrait dimensions (e.g. 1728x3072),
  no rotation matrix needed.
- Slow-motion clips have NO audio stream in the MP4; the real-time audio is
  saved in a sidecar .AAC with the same base name. The capture framerate is
  playback_fps * (mp4_duration / aac_duration), e.g. 25 * 4 = 100 fps.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import exifread

# ---------------------------------------------------------------------------
# ffprobe location
# ---------------------------------------------------------------------------

_FFPROBE_CACHE: Optional[str] = None

_WINDOWS_FALLBACKS = [
    r"C:\ffmpeg\bin\ffprobe.exe",
    r"C:\Program Files\ffmpeg\bin\ffprobe.exe",
]


def find_ffprobe() -> Optional[str]:
    """Locate ffprobe in PATH, next to the app, or in common install spots."""
    global _FFPROBE_CACHE
    if _FFPROBE_CACHE and os.path.exists(_FFPROBE_CACHE):
        return _FFPROBE_CACHE

    exe = "ffprobe.exe" if os.name == "nt" else "ffprobe"

    # 1. Bundled next to the application (bin/ffprobe[.exe])
    app_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for candidate in (os.path.join(app_dir, "bin", exe), os.path.join(app_dir, exe)):
        if os.path.exists(candidate):
            _FFPROBE_CACHE = candidate
            return candidate

    # 2. PATH
    found = shutil.which("ffprobe")
    if found:
        _FFPROBE_CACHE = found
        return found

    # 3. Common Windows locations
    if os.name == "nt":
        for candidate in _WINDOWS_FALLBACKS:
            if os.path.exists(candidate):
                _FFPROBE_CACHE = candidate
                return candidate
    return None


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class MediaMeta:
    """Normalized metadata for one media file."""
    width: int = 0
    height: int = 0
    fps: float = 0.0               # playback fps (videos)
    capture_fps: float = 0.0       # real capture fps (differs for slow motion)
    is_slow_motion: bool = False
    gamma: str = ""                # 'D-Log', 'D-Log2', 'Rec.709', ... ('' = unknown)
    has_audio: bool = True
    duration: float = 0.0
    creation: Optional[datetime] = None
    camera_make: str = ""
    camera_model: str = ""
    encoder: str = ""              # video container 'encoder' tag
    orientation: str = ""          # 'landscape' | 'portrait' | 'square'
    errors: list = field(default_factory=list)

    @property
    def resolution_label(self) -> str:
        """Human label for the resolution class (8K / 4K / FHD / HD / 48MP...)."""
        long_edge = max(self.width, self.height)
        if long_edge == 0:
            return ""
        if long_edge >= 7000:
            return "8K"
        if long_edge >= 3600:
            return "4K"
        if long_edge >= 2900:
            return "3K"
        if long_edge >= 2500:
            return "2.7K"
        if long_edge >= 1900:
            return "FHD"
        if long_edge >= 1200:
            return "HD"
        return f"{long_edge}px"

    @property
    def megapixel_label(self) -> str:
        mp = self.width * self.height / 1_000_000
        return f"{round(mp)}MP" if mp >= 1 else ""

    @property
    def fps_label(self) -> str:
        if self.capture_fps and self.is_slow_motion:
            return f"{_fmt_fps(self.capture_fps)}fps"
        if self.fps:
            return f"{_fmt_fps(self.fps)}fps"
        return ""

    @property
    def gamma_label(self) -> str:
        """Filename-safe gamma tag. Known values get canonical names;
        anything else the camera writes passes through sanitized, so future
        profiles (D-Log3, whatever) work without code changes."""
        import re
        g = re.sub(r"[^A-Za-z0-9]", "", self.gamma).upper()
        if g.startswith("DLOG"):
            return g          # DLOG, DLOG2, DLOG3...
        if "709" in g:
            return "REC709"
        if "HLG" in g:
            return "HLG"
        return g


def _fmt_fps(v: float) -> str:
    """59.94 -> 60, 29.97 -> 30, 23.976 -> 24, 25 -> 25."""
    return str(int(round(v)))


def _orientation(width: int, height: int) -> str:
    if width == 0 or height == 0:
        return ""
    if width > height:
        return "landscape"
    if height > width:
        return "portrait"
    return "square"


# ---------------------------------------------------------------------------
# Video probing
# ---------------------------------------------------------------------------

def probe_video(path: str, sidecar_aac: Optional[str] = None) -> MediaMeta:
    meta = MediaMeta()
    ffprobe = find_ffprobe()
    if not ffprobe:
        meta.errors.append("ffprobe not found - install FFmpeg or place it in the app's bin folder")
        _fallback_creation_from_mtime(path, meta)
        return meta

    data = _run_ffprobe(ffprobe, path)
    if data is None:
        meta.errors.append("ffprobe failed to read the file")
        _fallback_creation_from_mtime(path, meta)
        return meta

    fmt = data.get("format", {})
    tags = fmt.get("tags", {}) or {}
    # Gamma: try every tag any loaded camera profile declares (DJI writes
    # com.dji.camera.ColorGammaSxS; other makers get added via profiles).
    from .profiles import get_profiles
    gamma_tags = ["com.dji.camera.ColorGammaSxS"]
    for profile in get_profiles():
        for t in profile.gamma_tags:
            if t not in gamma_tags:
                gamma_tags.append(t)
    for t in gamma_tags:
        value = tags.get(t, "").strip()
        if value:
            meta.gamma = value
            break
    meta.camera_model = (tags.get("com.dji.camera.CameraModel", "").strip()
                         or tags.get("com.apple.quicktime.model", "").strip()
                         or tags.get("model", "").strip())
    meta.camera_make = (tags.get("com.apple.quicktime.make", "").strip()
                        or tags.get("make", "").strip())
    meta.encoder = tags.get("encoder", "").strip()
    meta.duration = _to_float(fmt.get("duration"))

    creation = tags.get("creation_time", "")

    has_audio = False
    for stream in data.get("streams", []):
        ctype = stream.get("codec_type")
        if ctype == "audio":
            has_audio = True
        elif ctype == "video" and stream.get("codec_name") != "mjpeg":
            # mjpeg stream is the embedded thumbnail track - skip it
            meta.width = int(stream.get("width") or 0)
            meta.height = int(stream.get("height") or 0)
            meta.fps = _parse_rate(stream.get("avg_frame_rate") or stream.get("r_frame_rate"))
            stags = stream.get("tags", {}) or {}
            creation = creation or stags.get("creation_time", "")

    meta.has_audio = has_audio
    meta.orientation = _orientation(meta.width, meta.height)
    # Prefer the timestamp encoded in the DJI filename: it is local camera
    # time, while the MP4 creation_time tag is UTC.
    meta.creation = _creation_from_dji_name(path) or _parse_iso(creation)
    if meta.creation is None:
        _fallback_creation_from_mtime(path, meta)

    # Slow-motion detection, two complementary rules:
    # 1. Conformed slow motion: silent MP4 + same-name AAC sidecar holding
    #    the real-time audio - capture fps = playback fps * duration ratio.
    # 2. High-frame-rate rule: any clip captured above 60 fps is treated as
    #    slow motion, whatever mode produced it.
    if not has_audio and sidecar_aac and os.path.exists(sidecar_aac):
        aac_dur = _probe_duration(ffprobe, sidecar_aac)
        if aac_dur and meta.duration and meta.fps:
            factor = meta.duration / aac_dur
            if factor >= 1.5:  # genuine slow motion, not a sync hiccup
                meta.is_slow_motion = True
                # DJI slow factors are integers (2x, 4x, 8x): snap to the
                # nearest integer factor when the measurement is close.
                snapped = round(factor)
                if snapped >= 2 and abs(factor - snapped) / snapped < 0.15:
                    factor = snapped
                meta.capture_fps = round(meta.fps * factor)
    if not meta.is_slow_motion and meta.fps > 61:
        # Played back at capture speed but shot high-frame-rate (e.g. 100 or
        # 120 fps): still slow-motion material. 61 tolerates 59.94/60 modes.
        meta.is_slow_motion = True
        meta.capture_fps = round(meta.fps)
    return meta


def _run_ffprobe(ffprobe: str, path: str) -> Optional[dict]:
    cmd = [ffprobe, "-v", "quiet", "-print_format", "json",
           "-show_format", "-show_streams", path]
    try:
        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        out = subprocess.run(cmd, capture_output=True, timeout=60, **kwargs)
        if out.returncode != 0:
            return None
        return json.loads(out.stdout.decode("utf-8", "replace"))
    except Exception:
        return None


def _probe_duration(ffprobe: str, path: str) -> float:
    data = _run_ffprobe(ffprobe, path)
    if not data:
        return 0.0
    return _to_float(data.get("format", {}).get("duration"))


# ---------------------------------------------------------------------------
# Photo probing
# ---------------------------------------------------------------------------

def probe_photo(path: str) -> MediaMeta:
    meta = MediaMeta()
    try:
        with open(path, "rb") as f:
            tags = exifread.process_file(f, details=False)
    except Exception as exc:
        meta.errors.append(f"EXIF read failed: {exc}")
        _fallback_creation_from_mtime(path, meta)
        return meta

    meta.camera_make = str(tags.get("Image Make", "")).strip()
    meta.camera_model = str(tags.get("Image Model", "")).strip()

    width = _exif_int(tags, "EXIF ExifImageWidth") or _exif_int(tags, "Image ImageWidth")
    height = _exif_int(tags, "EXIF ExifImageLength") or _exif_int(tags, "Image ImageLength")

    # DNG main IFD may describe the tiny preview; fall back to the JPG pair
    # dimensions at scan level if needed.
    meta.width, meta.height = width, height

    # JPG without usable EXIF dimensions: read them from the image header.
    if (width == 0 or height == 0) and path.lower().endswith((".jpg", ".jpeg")):
        try:
            from PIL import Image
            with Image.open(path) as img:
                meta.width, meta.height = img.size
        except Exception:
            pass

    orient = str(tags.get("Image Orientation", ""))
    if "90" in orient or "270" in orient:
        # EXIF says the stored pixels must be rotated to display: swap.
        meta.width, meta.height = meta.height, meta.width
    meta.orientation = _orientation(meta.width, meta.height)

    dt = str(tags.get("EXIF DateTimeOriginal", "")) or str(tags.get("Image DateTime", ""))
    meta.creation = _parse_exif_dt(dt) or _creation_from_dji_name(path)
    if meta.creation is None:
        _fallback_creation_from_mtime(path, meta)
    return meta


def _exif_int(tags: dict, key: str) -> int:
    try:
        v = tags.get(key)
        return int(str(v)) if v is not None else 0
    except (TypeError, ValueError):
        return 0


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def _parse_iso(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        # ffprobe gives e.g. 2026-08-24T14:52:37.000000Z (UTC). DJI also puts
        # local time in the filename; the filename wins when available.
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _parse_exif_dt(value: str) -> Optional[datetime]:
    try:
        return datetime.strptime(value.strip(), "%Y:%m:%d %H:%M:%S")
    except (ValueError, AttributeError):
        return None


def _creation_from_dji_name(path: str) -> Optional[datetime]:
    """DJI_20260824165159_0692_D.MP4 -> 2026-08-24 16:51:59 (local time)."""
    name = os.path.basename(path)
    parts = name.split("_")
    if len(parts) >= 2 and parts[0].upper() == "DJI" and len(parts[1]) == 14 and parts[1].isdigit():
        try:
            return datetime.strptime(parts[1], "%Y%m%d%H%M%S")
        except ValueError:
            return None
    return None


def _fallback_creation_from_mtime(path: str, meta: MediaMeta) -> None:
    try:
        meta.creation = datetime.fromtimestamp(os.path.getmtime(path))
    except OSError:
        meta.creation = None


def _parse_rate(value: Optional[str]) -> float:
    if not value or "/" not in value:
        return _to_float(value)
    num, den = value.split("/", 1)
    try:
        num_f, den_f = float(num), float(den)
        return num_f / den_f if den_f else 0.0
    except ValueError:
        return 0.0


def _to_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
