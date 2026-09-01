"""Video conversion engine (V2): FFmpeg queue with optional downscale and
D-Log -> Rec.709 LUT application.

- Works on any folder, including an already-imported library.
- The LUT (.cube) is applied only to clips detected as D-Log (per-clip
  detection via the DJI ColorGammaSxS tag), unless forced.
- Output modification time is copied from the source so the file history
  stays consistent.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from typing import List, Optional

from PySide6.QtCore import QThread, Signal

from .probe import MediaMeta, find_ffprobe


def find_ffmpeg() -> Optional[str]:
    """ffmpeg normally lives next to ffprobe."""
    ffprobe = find_ffprobe()
    if not ffprobe:
        return None
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    candidate = os.path.join(os.path.dirname(ffprobe), exe)
    if os.path.exists(candidate):
        return candidate
    import shutil
    return shutil.which("ffmpeg")


@dataclass
class ConvertJob:
    src_path: str
    meta: MediaMeta
    apply_lut: bool = False
    selected: bool = True
    keep_audio: bool = True    # False = strip the audio track (-an)
    group: str = ""            # merge group id ('' = standalone)
    thumb_png: bytes = b""     # small preview frame (PNG) for the UI
    out_path: str = ""
    status: str = "queued"     # queued | running | done | failed | skipped


@dataclass
class ConvertOptions:
    target_long_edge: int = 1920        # 0 = keep original resolution
    codec: str = "libx264"              # libx264 | libx265
    crf: int = 20
    preset: str = "medium"
    lut_path: str = ""                  # .cube file ('' = no LUT)
    output_folder: str = ""             # '' = CONVERTED subfolder beside source
    suffix: str = "_converted"          # appended before the extension


class ConvertWorker(QThread):
    file_started = Signal(int, str)          # job index, name
    file_progress = Signal(int, float)       # job index, 0..1
    file_done = Signal(int, str)             # job index, status
    all_done = Signal(int, int, list)        # converted, failed, errors

    def __init__(self, jobs: List[ConvertJob], options: ConvertOptions, parent=None):
        super().__init__(parent)
        self.jobs = jobs
        self.options = options
        self._cancel = False
        self._proc: Optional[subprocess.Popen] = None

    def cancel(self):
        self._cancel = True
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()

    # ------------------------------------------------------------------
    def run(self):
        ffmpeg = find_ffmpeg()
        errors: list[str] = []
        converted = failed = 0

        if not ffmpeg:
            self.all_done.emit(0, 0, ["ffmpeg not found - install FFmpeg or place it in the app's bin folder"])
            return

        # Build work units: standalone jobs, and merge groups (all selected
        # members of the same group become ONE concatenated output).
        units: list[list[int]] = []
        seen_groups: dict[str, int] = {}
        for idx, job in enumerate(self.jobs):
            if not job.selected:
                job.status = "skipped"
                continue
            if job.group:
                if job.group in seen_groups:
                    units[seen_groups[job.group]].append(idx)
                else:
                    seen_groups[job.group] = len(units)
                    units.append([idx])
            else:
                units.append([idx])

        for unit in units:
            if self._cancel:
                break
            jobs = [self.jobs[i] for i in unit]
            first = jobs[0]
            first.out_path = self._output_path(first, merged=len(jobs) > 1)
            os.makedirs(os.path.dirname(first.out_path), exist_ok=True)
            label = os.path.basename(first.out_path)
            self.file_started.emit(unit[0], label)
            for j in jobs:
                j.status = "running"
            try:
                if len(jobs) == 1:
                    ok = self._convert_one(ffmpeg, unit[0], first)
                else:
                    ok = self._convert_merged(ffmpeg, unit, jobs)
                status = "done" if ok else "failed"
                if ok:
                    converted += 1
                    try:
                        st = os.stat(first.src_path)
                        os.utime(first.out_path, (st.st_atime, st.st_mtime))
                    except OSError:
                        pass
                else:
                    failed += 1
                    errors.append(f"{label}: ffmpeg error")
            except Exception as exc:
                status = "failed"
                failed += 1
                errors.append(f"{label}: {exc}")
            for i, j in zip(unit, jobs):
                j.status = status
                j.out_path = first.out_path
                self.file_done.emit(i, status)

        self.all_done.emit(converted, failed, errors)

    # ------------------------------------------------------------------
    def _output_path(self, job: ConvertJob, merged: bool = False) -> str:
        src_dir = os.path.dirname(job.src_path)
        out_dir = self.options.output_folder or os.path.join(src_dir, "CONVERTED")
        stem, _ = os.path.splitext(os.path.basename(job.src_path))
        merged_tag = "_MERGED" if merged else ""
        return os.path.join(out_dir, f"{stem}{merged_tag}{self.options.suffix}.mp4")

    def _build_filters(self, job: ConvertJob) -> str:
        filters = []
        if job.apply_lut and self.options.lut_path:
            filters.append(f"lut3d='{_escape_filter_path(self.options.lut_path)}'")
        edge = self.options.target_long_edge
        if edge and max(job.meta.width, job.meta.height) > edge:
            # Scale the LONG edge to the target, works for portrait too.
            filters.append(
                f"scale=w='if(gt(iw,ih),{edge},-2)':h='if(gt(iw,ih),-2,{edge})'")
        return ",".join(filters)

    def _convert_one(self, ffmpeg: str, idx: int, job: ConvertJob) -> bool:
        cmd = [ffmpeg, "-y", "-i", job.src_path]
        vf = self._build_filters(job)
        if vf:
            cmd += ["-vf", vf]
        cmd += ["-c:v", self.options.codec,
                "-crf", str(self.options.crf),
                "-preset", self.options.preset,
                "-pix_fmt", "yuv420p"]
        if job.keep_audio:
            cmd += ["-c:a", "copy"]
        else:
            cmd += ["-an"]
        cmd += ["-movflags", "+faststart", job.out_path]

        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        self._proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            universal_newlines=True, errors="replace", **kwargs)

        duration = job.meta.duration or 0
        time_re = re.compile(r"time=(\d+):(\d+):(\d+\.?\d*)")
        for line in self._proc.stderr:
            if self._cancel:
                self._proc.terminate()
                break
            if duration:
                m = time_re.search(line)
                if m:
                    h, mnt, s = float(m.group(1)), float(m.group(2)), float(m.group(3))
                    self.file_progress.emit(idx, min((h * 3600 + mnt * 60 + s) / duration, 1.0))
        self._proc.wait()
        return self._proc.returncode == 0 and os.path.exists(job.out_path)


    def _convert_merged(self, ffmpeg: str, unit: list, jobs: list) -> bool:
        """Concatenate the group's videos into one output (re-encoded).
        Per-input handling: LUT applied only to D-Log members, everything
        scaled to the same target size. The merged output keeps audio only
        when EVERY member keeps audio and actually has an audio stream -
        mixing silent and audible segments cannot be concatenated cleanly.
        """
        first = jobs[0]
        with_audio = all(j.keep_audio and j.meta.has_audio for j in jobs)

        cmd = [ffmpeg, "-y"]
        for j in jobs:
            cmd += ["-i", j.src_path]

        edge = self.options.target_long_edge
        # Common canvas: target long edge, or the first clip's size.
        chains = []
        for i, j in enumerate(jobs):
            steps = []
            if j.apply_lut and self.options.lut_path:
                steps.append(f"lut3d='{_escape_filter_path(self.options.lut_path)}'")
            if edge:
                steps.append(f"scale=w='if(gt(iw,ih),{edge},-2)':h='if(gt(iw,ih),-2,{edge})'")
            else:
                steps.append(f"scale={first.meta.width}:{first.meta.height}")
            steps.append("setsar=1")
            chains.append(f"[{i}:v]{','.join(steps)}[v{i}]")
        if with_audio:
            concat_in = "".join(f"[v{i}][{i}:a]" for i in range(len(jobs)))
            chains.append(f"{concat_in}concat=n={len(jobs)}:v=1:a=1[outv][outa]")
        else:
            concat_in = "".join(f"[v{i}]" for i in range(len(jobs)))
            chains.append(f"{concat_in}concat=n={len(jobs)}:v=1:a=0[outv]")

        cmd += ["-filter_complex", ";".join(chains), "-map", "[outv]"]
        if with_audio:
            cmd += ["-map", "[outa]", "-c:a", "aac", "-b:a", "192k"]
        cmd += ["-c:v", self.options.codec,
                "-crf", str(self.options.crf),
                "-preset", self.options.preset,
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                first.out_path]

        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = 0x08000000
        self._proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            universal_newlines=True, errors="replace", **kwargs)

        total_dur = sum(j.meta.duration or 0 for j in jobs)
        time_re = re.compile(r"time=(\d+):(\d+):(\d+\.?\d*)")
        for line in self._proc.stderr:
            if self._cancel:
                self._proc.terminate()
                break
            if total_dur:
                m = time_re.search(line)
                if m:
                    h, mnt, s = float(m.group(1)), float(m.group(2)), float(m.group(3))
                    self.file_progress.emit(unit[0], min((h * 3600 + mnt * 60 + s) / total_dur, 1.0))
        self._proc.wait()
        return self._proc.returncode == 0 and os.path.exists(first.out_path)


def extract_thumbnail_png(path: str, height: int = 54) -> bytes:
    """One small preview frame as PNG bytes ('' on failure). Fast: seeks
    one second in and decodes a single downscaled frame."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return b""
    cmd = [ffmpeg, "-ss", "1", "-i", path, "-frames:v", "1",
           "-vf", f"scale=-2:{height}", "-f", "image2pipe",
           "-vcodec", "png", "-"]
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = 0x08000000
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=30, **kwargs)
        if out.returncode == 0 and out.stdout:
            return out.stdout
        # Very short clips: retry from the start.
        cmd[2] = "0"
        out = subprocess.run(cmd, capture_output=True, timeout=30, **kwargs)
        return out.stdout if out.returncode == 0 else b""
    except Exception:
        return b""


def _escape_filter_path(path: str) -> str:
    """FFmpeg filter args need forward slashes and escaped drive colons."""
    p = path.replace("\\", "/")
    return p.replace(":", "\\:")
