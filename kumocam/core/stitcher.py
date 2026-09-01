"""Panorama stitching engine (V3, detail pipeline).

The Osmo Pocket saves panoramas as segment folders (PANORAMA/001_0104/
PANO_0001.JPG...) and only the DJI Mimo app stitches them. This module does
it standalone with OpenCV's `detail` pipeline (the same building blocks as
the stitching_detailed sample), which gives control the high-level Stitcher
lacks: projection choice, horizon leveling (wave correction), block gain
exposure compensation, graph-cut seams and grid-aware matching.

Osmo panorama types and the projections that suit them (validated on real
files):
- 3x3 grid (9 frames): spherical projection (large vertical FOV).
- 180 degrees (4 frames): cylindrical projection - much less curvature,
  verticals stay straight.

Osmo 3x3 capture order (fixed firmware pattern - grid position by file
number, confirmed on real panoramas):

    6 2 7
    5 1 8
    4 3 9

1 = center, then the center column, left column, right column. The matcher
uses this to only match physically adjacent frames.

Confidence strategy: a strict threshold can drop weak frames (losing part
of the pano), a loose one can break bundle adjustment or let parallax
ghosts in. The engine sweeps thresholds and keeps the successful attempt
that uses the most frames (preferring stricter on ties), reporting
"used X/Y frames" when a pano stays partial.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from PySide6.QtCore import QThread, Signal

PHOTO_EXTS = {".jpg", ".jpeg"}

# Grid positions by file number for the 3x3 mode: {file_no: (row, col)}
GRID_3X3 = {1: (1, 1), 2: (0, 1), 3: (2, 1), 4: (2, 0), 5: (1, 0),
            6: (0, 0), 7: (0, 2), 8: (1, 2), 9: (2, 2)}

# Attempt sweep: (confidence threshold, analysis megapixels). Which pairs
# match can flip with the analysis resolution (SIFT + RANSAC), so both
# resolutions are tried before relaxing confidence.
ATTEMPT_SWEEP = ((1.0, 1.0), (1.0, 0.6), (0.7, 1.0), (0.7, 0.6),
                 (0.55, 1.0), (0.45, 0.6), (0.4, 1.0), (0.35, 0.6))


def pano_type_label(n_frames: int) -> str:
    if n_frames == 9:
        return "3x3 grid"
    if n_frames == 4:
        return "180\N{DEGREE SIGN}"
    return f"custom ({n_frames})"


def auto_projection(n_frames: int) -> str:
    return "cylindrical" if n_frames == 4 else "spherical"


@dataclass
class StitchJob:
    folder: str                       # segment folder (001_0104)
    files: List[str] = field(default_factory=list)
    selected: bool = True
    status: str = "queued"            # queued | running | done | failed | skipped
    out_path: str = ""
    message: str = ""

    @property
    def name(self) -> str:
        return os.path.basename(self.folder)

    @property
    def type_label(self) -> str:
        return pano_type_label(len(self.files))


@dataclass
class StitchOptions:
    output_root: str = ""             # '' = STITCH folder beside the segment folders
    projection: str = "auto"          # 'auto' | 'spherical' | 'cylindrical'
    max_output_width: int = 0         # 0 = full resolution
    jpeg_quality: int = 95
    # Panorama camera profile: 'dji-osmo-pocket' uses the known 3x3 grid
    # order for matching; 'generic' assumes plain sequential capture.
    pano_profile: str = "dji-osmo-pocket"


def find_panorama_folders(root: str) -> List[StitchJob]:
    """Find stitchable segment folders under root.

    Accepts either the PANORAMA folder itself, a folder containing one, or a
    direct segment folder full of PANO_*.JPG files.
    """
    jobs: List[StitchJob] = []
    seen = set()

    def add(folder: str):
        real = os.path.normpath(folder)
        if real in seen:
            return
        files = sorted(
            os.path.join(folder, f) for f in os.listdir(folder)
            if os.path.splitext(f)[1].lower() in PHOTO_EXTS
        )
        if len(files) >= 2:
            seen.add(real)
            jobs.append(StitchJob(folder=folder, files=files))

    for dirpath, dirnames, filenames in os.walk(root):
        base = os.path.basename(dirpath)
        if base.upper() == "STITCH":
            dirnames[:] = []
            continue
        has_pano_files = any(f.upper().startswith("PANO_") and
                             os.path.splitext(f)[1].lower() in PHOTO_EXTS
                             for f in filenames)
        if has_pano_files:
            add(dirpath)
            dirnames[:] = []
    return jobs


class StitchWorker(QThread):
    job_started = Signal(int, str)
    job_progress = Signal(int, int, str)      # index, percent 0-100, stage text
    job_done = Signal(int, str, str)          # index, status, message
    all_done = Signal(int, int)               # done, failed

    def __init__(self, jobs: List[StitchJob], options: StitchOptions, parent=None):
        super().__init__(parent)
        self.jobs = jobs
        self.options = options
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        import cv2

        done = failed = 0
        for idx, job in enumerate(self.jobs):
            if self._cancel:
                break
            if not job.selected:
                job.status = "skipped"
                continue
            self.job_started.emit(idx, job.name)
            job.status = "running"
            try:
                status, message, out = self._stitch_one(cv2, job)
                job.status, job.message, job.out_path = status, message, out
                if status == "done":
                    done += 1
                else:
                    failed += 1
            except Exception as exc:
                job.status, job.message = "failed", str(exc)
                failed += 1
            self.job_done.emit(idx, job.status, job.message)
        self.all_done.emit(done, failed)

    # ------------------------------------------------------------------
    def _out_dir(self, job: StitchJob) -> str:
        if self.options.output_root:
            return self.options.output_root
        return os.path.join(os.path.dirname(job.folder), "STITCH")

    def _stitch_one(self, cv2, job: StitchJob):
        images = []
        for path in job.files:
            img = _imread_unicode(cv2, path)
            if img is None:
                return "failed", f"could not read {os.path.basename(path)}", ""
            images.append(img)

        total = len(images)
        projection = self.options.projection
        if projection == "auto":
            projection = auto_projection(total)

        # Confidence sweep on the detail pipeline; keep the successful
        # attempt with the most frames (stricter wins ties).
        job_index = self.jobs.index(job)
        best: Optional[Tuple[int, object]] = None
        for attempt, (conf, work_mpx) in enumerate(ATTEMPT_SWEEP, start=1):
            if self._cancel:
                break

            def report(fraction: float, stage: str, _a=attempt):
                prefix = f"attempt {_a}: " if _a > 1 else ""
                self.job_progress.emit(job_index, int(fraction * 100), prefix + stage)

            try:
                pano, used = _detail_stitch(
                    cv2, images, projection, conf, work_mpx=work_mpx,
                    use_grid_3x3=(self.options.pano_profile == "dji-osmo-pocket"),
                    progress=report)
            except Exception:
                continue
            if best is None or used > best[0]:
                best = (used, pano)
            if used == total:
                break

        if best is None:
            # Last resort: OpenCV's high-level stitcher.
            try:
                stitcher = cv2.Stitcher_create(cv2.Stitcher_PANORAMA)
                status, pano = stitcher.stitch(images)
                if status == cv2.Stitcher_OK:
                    used = total
                    try:
                        used = len(stitcher.component())
                    except Exception:
                        pass
                    best = (used, pano)
            except cv2.error:
                pass
        if best is None:
            return "failed", "no stitch attempt succeeded (finish in PTGui/Lightroom)", ""

        used, pano = best
        partial = f", used {used}/{total} frames" if used < total else ""

        pano = _autocrop(cv2, pano)

        if self.options.max_output_width and pano.shape[1] > self.options.max_output_width:
            scale = self.options.max_output_width / pano.shape[1]
            pano = cv2.resize(pano, None, fx=scale, fy=scale,
                              interpolation=cv2.INTER_AREA)

        out_dir = self._out_dir(job)
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"{job.name}.jpg")
        ok = _imwrite_unicode(cv2, out_path, pano,
                              [cv2.IMWRITE_JPEG_QUALITY, self.options.jpeg_quality])
        if not ok:
            return "failed", "could not write output file", ""

        # Give the stitched result the capture time of the first frame so it
        # sorts naturally in date views.
        try:
            st = os.stat(job.files[0])
            os.utime(out_path, (st.st_atime, st.st_mtime))
        except OSError:
            pass
        h, w = pano.shape[:2]
        return "done", f"{w}x{h} ({projection}){partial}", out_path


# ---------------------------------------------------------------------------
# Detail pipeline
# ---------------------------------------------------------------------------

def _grid_mask_3x3(np):
    mask = np.zeros((9, 9), np.uint8)
    for i in range(1, 10):
        for j in range(1, 10):
            if i != j and max(abs(GRID_3X3[i][0] - GRID_3X3[j][0]),
                              abs(GRID_3X3[i][1] - GRID_3X3[j][1])) <= 1:
                mask[i - 1, j - 1] = 1
    return mask


def _band_mask(np, n: int, width: int = 2):
    """Sequential capture (e.g. the 4-frame 180): only match frames close in
    the shot order. Prevents far-apart frames from latching onto lookalike
    content (clouds, water) at an impossible position."""
    mask = np.zeros((n, n), np.uint8)
    for i in range(n):
        for j in range(n):
            if i != j and abs(i - j) <= width:
                mask[i, j] = 1
    return mask


def _euler_deg(np, R):
    """(yaw, pitch, roll) in degrees from a camera rotation matrix."""
    yaw = math.degrees(math.atan2(R[0, 2], R[2, 2]))
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, float(-R[1, 2])))))
    roll = math.degrees(math.atan2(R[1, 0], R[1, 1]))
    return yaw, pitch, roll


def _geometry_plausible(np, cameras) -> bool:
    """Reject solutions where a frame landed at an impossible position:
    a yaw gap between neighbors wider than one frame's FOV, an extreme
    pitch spread, or a strong residual roll after horizon leveling. This is
    what catches the 'stitched but completely warped' failure mode."""
    angles = [_euler_deg(np, cam.R) for cam in cameras]
    yaws = sorted(a[0] for a in angles)
    for a, b in zip(yaws, yaws[1:]):
        if b - a > 60:      # Osmo frames are ~40 degrees apart; >60 = no overlap
            return False
    pitches = [a[1] for a in angles]
    if max(pitches) - min(pitches) > 80:
        return False
    if any(abs(a[2]) > 25 for a in angles):
        return False
    return True


def _detail_stitch(cv2, images, projection: str, conf_thresh: float,
                   work_mpx: float = 1.0, use_grid_3x3: bool = True,
                   progress=None):
    """One stitching attempt. Returns (panorama, frames_used); raises on
    failure. Follows OpenCV's stitching_detailed pipeline.

    `progress(fraction, stage_text)` is called as the stages advance.
    Stage weights: features 0-15%, matching 15-25%, adjust 25-35%,
    seams 35-50%, compose 50-100% (full-res warping dominates the time).
    """
    import numpy as np

    def report(fraction: float, stage: str):
        if progress:
            progress(min(max(fraction, 0.0), 1.0), stage)

    # Deterministic matching: without a fixed seed, RANSAC can produce a
    # good stitch on one run and a broken one on the next.
    cv2.setRNGSeed(1234)

    full_h, full_w = images[0].shape[:2]
    # Analysis resolution matters: a pair match can fail entirely (RANSAC
    # confidence 0) at one resolution and be rock solid at another, so the
    # caller sweeps work_mpx along with the confidence threshold.
    work_scale = min(1.0, math.sqrt(work_mpx * 1e6 / (full_w * full_h)))
    seam_scale = min(1.0, math.sqrt(0.1e6 / (full_w * full_h)))
    seam_work_aspect = seam_scale / work_scale

    finder = cv2.SIFT_create()
    features = []
    for i, img in enumerate(images):
        report(0.15 * i / len(images), f"analyzing frame {i + 1}/{len(images)}")
        wimg = cv2.resize(img, None, fx=work_scale, fy=work_scale,
                          interpolation=cv2.INTER_AREA)
        features.append(cv2.detail.computeImageFeatures2(finder, wimg))

    report(0.15, "matching frames")
    matcher = cv2.detail_BestOf2NearestMatcher(False, 0.3)
    if len(images) == 9 and use_grid_3x3:
        # Osmo 3x3: only match physically adjacent frames of the known grid.
        pairwise = matcher.apply2(features, cv2.UMat(_grid_mask_3x3(np)))
    elif len(images) <= 6 or use_grid_3x3:
        # Sequential capture, left to right (the 180 mode shoots 01-02-03-04
        # side by side): each frame only matches its immediate neighbors.
        pairwise = matcher.apply2(features, cv2.UMat(_band_mask(np, len(images), width=1)))
    else:
        # Unknown layout with many frames: wider matching band.
        pairwise = matcher.apply2(features, cv2.UMat(_band_mask(np, len(images), width=2)))
    matcher.collectGarbage()

    indices = [int(i) for i in
               cv2.detail.leaveBiggestComponent(features, pairwise, conf_thresh)]
    if len(indices) < 2:
        raise RuntimeError("not enough connected frames")
    subset = [images[i] for i in indices]

    report(0.25, "estimating cameras")
    estimator = cv2.detail_HomographyBasedEstimator()
    ok, cameras = estimator.apply(features, pairwise, None)
    if not ok:
        raise RuntimeError("estimator failed")
    for cam in cameras:
        cam.R = cam.R.astype(np.float32)

    adjuster = cv2.detail_BundleAdjusterRay()
    adjuster.setConfThresh(conf_thresh)
    refine_mask = np.zeros((3, 3), np.uint8)
    refine_mask[0, 0] = 1; refine_mask[0, 1] = 1; refine_mask[0, 2] = 1
    refine_mask[1, 1] = 1; refine_mask[1, 2] = 1
    adjuster.setRefinementMask(refine_mask)
    ok, cameras = adjuster.apply(features, pairwise, cameras)
    if not ok:
        raise RuntimeError("bundle adjust failed")

    focals = sorted(cam.focal for cam in cameras)
    mid = len(focals) // 2
    warped_scale = focals[mid] if len(focals) % 2 else (focals[mid - 1] + focals[mid]) / 2

    # Horizon leveling.
    rmats = [np.copy(cam.R) for cam in cameras]
    rmats = cv2.detail.waveCorrect(rmats, cv2.detail.WAVE_CORRECT_HORIZ)
    for cam, R in zip(cameras, rmats):
        cam.R = R

    # Sanity gate BEFORE the expensive compose: a solution that placed a
    # frame at an impossible angle produces a "stitched but broken" pano.
    if not _geometry_plausible(np, cameras):
        raise RuntimeError("implausible camera geometry")

    # ---- seam pass (low resolution)
    report(0.35, "finding seams")
    seam_images = [cv2.resize(img, None, fx=seam_scale, fy=seam_scale,
                              interpolation=cv2.INTER_AREA) for img in subset]
    warper = cv2.PyRotationWarper(projection, warped_scale * seam_work_aspect)
    corners, w_imgs, w_masks = [], [], []
    for i, img in enumerate(seam_images):
        K = cameras[i].K().astype(np.float32)
        K[0, 0] *= seam_work_aspect; K[0, 2] *= seam_work_aspect
        K[1, 1] *= seam_work_aspect; K[1, 2] *= seam_work_aspect
        corner, wimg = warper.warp(img, K, cameras[i].R, cv2.INTER_LINEAR, cv2.BORDER_REFLECT)
        msk = 255 * np.ones((img.shape[0], img.shape[1]), np.uint8)
        _, wmask = warper.warp(msk, K, cameras[i].R, cv2.INTER_NEAREST, cv2.BORDER_CONSTANT)
        corners.append(corner); w_imgs.append(wimg); w_masks.append(cv2.UMat(wmask))

    compensator = cv2.detail.ExposureCompensator_createDefault(
        cv2.detail.ExposureCompensator_GAIN_BLOCKS)
    compensator.feed(corners=corners, images=w_imgs, masks=w_masks)
    seam_finder = cv2.detail_GraphCutSeamFinder("COST_COLOR")
    w_masks = seam_finder.find([im.astype(np.float32) for im in w_imgs], corners, w_masks)

    # ---- compose pass (full resolution)
    compose_work_aspect = 1.0 / work_scale
    warper = cv2.PyRotationWarper(projection, warped_scale * compose_work_aspect)
    for cam in cameras:
        cam.focal *= compose_work_aspect
        cam.ppx *= compose_work_aspect
        cam.ppy *= compose_work_aspect

    rois = []
    for i, img in enumerate(subset):
        K = cameras[i].K().astype(np.float32)
        rois.append(warper.warpRoi((img.shape[1], img.shape[0]), K, cameras[i].R))
    dst = cv2.detail.resultRoi(corners=[r[:2] for r in rois],
                               sizes=[(r[2], r[3]) for r in rois])
    blender = cv2.detail_MultiBandBlender()
    blender.setNumBands(max(1, int(np.log2(max(dst[2], dst[3]))) - 3))
    blender.prepare(dst)

    for i, img in enumerate(subset):
        report(0.5 + 0.45 * i / len(subset), f"composing frame {i + 1}/{len(subset)}")
        K = cameras[i].K().astype(np.float32)
        corner, wimg = warper.warp(img, K, cameras[i].R, cv2.INTER_LINEAR, cv2.BORDER_REFLECT)
        msk = 255 * np.ones((img.shape[0], img.shape[1]), np.uint8)
        _, wmask = warper.warp(msk, K, cameras[i].R, cv2.INTER_NEAREST, cv2.BORDER_CONSTANT)
        compensator.apply(i, corner, wimg, wmask)
        seam_mask = cv2.dilate(w_masks[i].get(), np.ones((3, 3), np.uint8))
        seam_mask = cv2.resize(seam_mask, (wmask.shape[1], wmask.shape[0]),
                               interpolation=cv2.INTER_LINEAR_EXACT)
        blender.feed(cv2.UMat(wimg.astype(np.int16)),
                     cv2.bitwise_and(seam_mask, wmask), corner)

    report(0.95, "blending")
    result, _ = blender.blend(None, None)
    result = np.clip(result, 0, 255).astype(np.uint8)
    return result, len(subset)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _imread_unicode(cv2, path: str):
    """cv2.imread fails on non-ASCII Windows paths; decode via numpy instead."""
    import numpy as np
    try:
        data = np.fromfile(path, dtype=np.uint8)
        return cv2.imdecode(data, cv2.IMREAD_COLOR)
    except Exception:
        return None


def _imwrite_unicode(cv2, path: str, image, params) -> bool:
    try:
        ok, buf = cv2.imencode(os.path.splitext(path)[1], image, params)
        if not ok:
            return False
        buf.tofile(path)
        return True
    except Exception:
        return False


def _autocrop(cv2, pano):
    """Trim the black borders left by the warp, keeping the largest clean
    rectangle (simple threshold-based crop)."""
    import numpy as np
    gray = cv2.cvtColor(pano, cv2.COLOR_BGR2GRAY)
    mask = (gray > 3).astype(np.uint8)
    coords = cv2.findNonZero(mask)
    if coords is None:
        return pano
    x, y, w, h = cv2.boundingRect(coords)

    def mostly_valid(sl) -> bool:
        return sl.mean() > 0.995

    top, bottom, left, right = y, y + h, x, x + w
    for _ in range(pano.shape[0]):
        changed = False
        if bottom - top > 10:
            if not mostly_valid(mask[top, left:right]):
                top += 1
                changed = True
            if not mostly_valid(mask[bottom - 1, left:right]):
                bottom -= 1
                changed = True
        if right - left > 10:
            if not mostly_valid(mask[top:bottom, left]):
                left += 1
                changed = True
            if not mostly_valid(mask[top:bottom, right - 1]):
                right -= 1
                changed = True
        if not changed:
            break
    return pano[top:bottom, left:right]
