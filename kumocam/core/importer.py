"""Import engine: copies the confirmed items into the target folder.

Layout produced:

    <target>/
        2026-08-24/
            PHOTOS/    48MP_DJI_20260826192734_0020_D.JPG (+ .DNG twin)
            VIDEOS/    4K_60fps_DLOG_DJI_20260824165237_0693_D.MP4
                       (slow-motion .AAC sidecar copied with matching name)
            PANORAMA/  001_0104/PANO_0001.JPG ...
        2026-08-26/
            ...

All copies use shutil.copy2, which preserves the original modification
timestamps - the file history stays intact. Optional portrait/landscape
subfolders can be enabled.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from typing import List

from PySide6.QtCore import QThread, Signal

from .scanner import MediaItem


@dataclass
class ImportOptions:
    target: str = ""
    split_orientation: bool = False   # PHOTOS/PORTRAIT, PHOTOS/LANDSCAPE ...
    on_conflict: str = "skip"         # 'skip' | 'rename'
    # LRF proxies are plain low-resolution MP4s; when enabled, an imported
    # X.LRF becomes X_LRF.MP4 (playable anywhere, and the _LRF suffix keeps
    # it distinct from the full-quality MP4 in duplicate detection).
    rename_lrf_to_mp4: bool = False


class ImportWorker(QThread):
    """Runs the copy in a background thread so the UI stays responsive."""

    progress = Signal(int, int, str)      # done, total, current file
    finished_ok = Signal(int, int, list)  # copied, skipped, error list

    def __init__(self, items: List[MediaItem], options: ImportOptions, parent=None):
        super().__init__(parent)
        self.items = [i for i in items if i.selected]
        self.options = options
        self._cancel = False

    def cancel(self):
        self._cancel = True

    # ------------------------------------------------------------------
    def run(self):
        copied = skipped = 0
        errors: list[str] = []
        total = sum(len(i.pano_files) if i.kind == "panorama" else 1 for i in self.items)
        done = 0

        for item in self.items:
            if self._cancel:
                break
            try:
                if item.kind == "panorama":
                    done, c, s = self._copy_panorama(item, done, total)
                    copied += c
                    skipped += s
                else:
                    done += 1
                    self.progress.emit(done, total, item.display_name)
                    outcome = self._copy_media(item)
                    if outcome == "copied":
                        copied += 1
                    else:
                        skipped += 1
            except Exception as exc:
                errors.append(f"{item.display_name}: {exc}")

        self.finished_ok.emit(copied, skipped, errors)

    # ------------------------------------------------------------------
    def _date_folder(self, item: MediaItem) -> str:
        dt = item.meta.creation
        return dt.strftime("%Y-%m-%d") if dt else "unknown-date"

    def _media_folder(self, item: MediaItem) -> str:
        parts = [self.options.target, self._date_folder(item)]
        if item.kind == "panorama":
            parts.append("PANORAMA")
        else:
            parts.append("PHOTOS" if item.kind == "photo" else "VIDEOS")
            if self.options.split_orientation and item.meta.orientation:
                parts.append(item.meta.orientation.upper())
        return os.path.join(*parts)

    def _copy_media(self, item: MediaItem) -> str:
        folder = self._media_folder(item)
        os.makedirs(folder, exist_ok=True)
        name = item.new_name or item.display_name
        if self.options.rename_lrf_to_mp4 and name.lower().endswith(".lrf"):
            name = name[:-4] + "_LRF.MP4"
        dest = os.path.join(folder, name)

        dest = self._resolve_conflict(dest)
        if dest is None:
            return "skipped"

        shutil.copy2(item.src_path, dest)
        item.dest_path = dest

        # Slow-motion / external-mic AAC sidecar follows its video, renamed
        # consistently with the new video name.
        if item.sidecar_aac and os.path.exists(item.sidecar_aac):
            new_stem = os.path.splitext(os.path.basename(dest))[0]
            aac_dest = os.path.join(folder, new_stem + ".AAC")
            aac_dest_checked = self._resolve_conflict(aac_dest)
            if aac_dest_checked:
                shutil.copy2(item.sidecar_aac, aac_dest_checked)
        return "copied"

    def _copy_panorama(self, item: MediaItem, done: int, total: int):
        folder = os.path.join(self._media_folder(item), item.display_name)
        os.makedirs(folder, exist_ok=True)
        copied = skipped = 0
        for src in item.pano_files:
            if self._cancel:
                break
            done += 1
            self.progress.emit(done, total, f"{item.display_name}/{os.path.basename(src)}")
            dest = self._resolve_conflict(os.path.join(folder, os.path.basename(src)))
            if dest is None:
                skipped += 1
                continue
            shutil.copy2(src, dest)
            copied += 1
        item.dest_path = folder
        return done, copied, skipped

    def _resolve_conflict(self, dest: str):
        if not os.path.exists(dest):
            return dest
        if self.options.on_conflict == "skip":
            return None
        stem, ext = os.path.splitext(dest)
        n = 1
        while os.path.exists(f"{stem}_{n}{ext}"):
            n += 1
        return f"{stem}_{n}{ext}"
