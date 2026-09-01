"""Scanner for DJI Osmo Pocket source volumes.

Walks the selected sources (camera internal drive, SD card, or any folder),
collects importable media and groups panorama folders, while skipping what
should not be imported by default:

- .LRF  low-resolution reference proxies
- .WAV  separate audio recordings (optional include)
- MISC/ folder (thumbnails + internal DJI database)

.AAC sidecars are NOT standalone items: they carry the real-time audio of
slow-motion clips (and external mic recordings) and travel with their MP4.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from .probe import MediaMeta, probe_photo, probe_video

VIDEO_EXTS = {".mp4", ".mov"}
PHOTO_EXTS = {".jpg", ".jpeg", ".dng"}
SKIP_DIRS = {"misc"}
PANORAMA_DIR = "panorama"


@dataclass
class MediaItem:
    """One importable unit: a photo, a video (with optional AAC sidecar),
    or a whole panorama segment folder."""
    kind: str                    # 'photo' | 'video' | 'panorama'
    src_path: str                # file path, or folder path for panoramas
    size: int = 0
    meta: MediaMeta = field(default_factory=MediaMeta)
    sidecar_aac: Optional[str] = None    # videos only
    pano_files: List[str] = field(default_factory=list)  # panoramas only
    selected: bool = True
    new_name: str = ""           # filled by the naming module
    dest_path: str = ""          # filled by the importer
    in_library: bool = False     # already present in the target library
    camera: str = ""             # detected camera (EXIF model or profile name)

    def detect_camera(self) -> None:
        from .profiles import camera_label, detect_profile
        profile = detect_profile(self.meta.camera_make, self.meta.camera_model,
                                 self.meta.encoder, self.src_path)
        self.camera = camera_label(self.meta.camera_make,
                                   self.meta.camera_model, profile)

    @property
    def display_name(self) -> str:
        return os.path.basename(self.src_path)

    @property
    def ext(self) -> str:
        return os.path.splitext(self.src_path)[1].lower()


@dataclass
class ScanOptions:
    include_lrf: bool = False
    include_wav: bool = False
    copy_aac_sidecars: bool = True


@dataclass
class ScanResult:
    items: List[MediaItem] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)   # human-readable log
    errors: List[str] = field(default_factory=list)


def scan_sources(sources: List[str], options: ScanOptions,
                 progress: Optional[Callable[[str], None]] = None,
                 cancelled: Optional[Callable[[], bool]] = None) -> ScanResult:
    result = ScanResult()
    for source in sources:
        if not os.path.isdir(source):
            result.errors.append(f"Source not found: {source}")
            continue
        _scan_tree(source, options, result, progress, cancelled)
    return result


def _scan_tree(root: str, options: ScanOptions, result: ScanResult,
               progress, cancelled) -> None:
    for dirpath, dirnames, filenames in os.walk(root):
        if cancelled and cancelled():
            return

        base = os.path.basename(dirpath).lower()
        # Skip MISC (thumbnails/database) entirely.
        dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_DIRS]

        # Panorama root: each subfolder is one panorama unit.
        if base == PANORAMA_DIR:
            for sub in sorted(dirnames):
                _add_panorama(os.path.join(dirpath, sub), result, progress)
            dirnames[:] = []  # handled - do not descend further
            continue

        files = sorted(filenames)
        names_lower = {f.lower() for f in files}

        for fname in files:
            if cancelled and cancelled():
                return
            fpath = os.path.join(dirpath, fname)
            ext = os.path.splitext(fname)[1].lower()

            if ext == ".lrf" and not options.include_lrf:
                result.skipped.append(f"LRF proxy skipped: {fname}")
                continue
            if ext == ".wav" and not options.include_wav:
                result.skipped.append(f"WAV audio skipped: {fname}")
                continue
            if ext == ".aac":
                # Sidecar - attached to its MP4, never a standalone item.
                continue

            if ext in VIDEO_EXTS or (ext == ".lrf" and options.include_lrf):
                if progress:
                    progress(f"Reading video metadata: {fname}")
                stem = os.path.splitext(fname)[0]
                sidecar = None
                if (stem + ".aac").lower() in names_lower:
                    for cand in files:
                        if cand.lower() == (stem + ".aac").lower():
                            sidecar = os.path.join(dirpath, cand)
                            break
                item = MediaItem(kind="video", src_path=fpath,
                                 size=_safe_size(fpath),
                                 sidecar_aac=sidecar if options.copy_aac_sidecars else None)
                item.meta = probe_video(fpath, sidecar_aac=sidecar)
                result.items.append(item)

            elif ext in PHOTO_EXTS:
                if progress:
                    progress(f"Reading photo metadata: {fname}")
                item = MediaItem(kind="photo", src_path=fpath, size=_safe_size(fpath))
                item.meta = probe_photo(fpath)
                result.items.append(item)

    # DNG files often describe only their tiny embedded preview in the main
    # IFD; borrow real dimensions/orientation from the JPG twin.
    _fix_dng_dimensions(result.items)
    for item in result.items:
        item.detect_camera()


def _add_panorama(folder: str, result: ScanResult, progress) -> None:
    files = sorted(
        os.path.join(folder, f) for f in os.listdir(folder)
        if os.path.splitext(f)[1].lower() in PHOTO_EXTS
    )
    if not files:
        return
    if progress:
        progress(f"Panorama folder: {os.path.basename(folder)} ({len(files)} frames)")
    item = MediaItem(kind="panorama", src_path=folder,
                     size=sum(_safe_size(f) for f in files),
                     pano_files=files)
    item.meta = probe_photo(files[0])
    result.items.append(item)


def _fix_dng_dimensions(items: List[MediaItem]) -> None:
    jpg_by_stem = {}
    for it in items:
        if it.kind == "photo" and it.ext in (".jpg", ".jpeg"):
            stem = os.path.splitext(it.src_path)[0].lower()
            jpg_by_stem[stem] = it
    for it in items:
        if it.kind == "photo" and it.ext == ".dng":
            twin = jpg_by_stem.get(os.path.splitext(it.src_path)[0].lower())
            if twin and max(it.meta.width, it.meta.height) < 1000:
                it.meta.width = twin.meta.width
                it.meta.height = twin.meta.height
                it.meta.orientation = twin.meta.orientation


def _safe_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0
