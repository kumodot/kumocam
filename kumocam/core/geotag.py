"""Geotagging engine (V4).

The Osmo Pocket has no GPS but writes a complete, zeroed GPS EXIF block
(status 'V') into every photo - so geotagging is a clean fill-in.

Coordinate sources:
- a reference photo (e.g. taken with the phone at the same spot);
- pasted coordinates, Google Maps style: "45.50123, -73.56789".

Writers:
- JPG: piexif (pure python, bundled).
- DNG / MP4 / MOV: ExifTool when installed (optional external tool, like
  FFmpeg). Without it those files are reported as skipped.

File modification times are restored after writing so the date history
stays intact.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from typing import List, Optional, Tuple

import exifread
import piexif
from PySide6.QtCore import QThread, Signal

JPG_EXTS = {".jpg", ".jpeg"}
EXIFTOOL_EXTS = {".dng", ".mp4", ".mov", ".tif", ".tiff"}

_EXIFTOOL_CACHE: Optional[str] = None


def find_exiftool() -> Optional[str]:
    global _EXIFTOOL_CACHE
    if _EXIFTOOL_CACHE and os.path.exists(_EXIFTOOL_CACHE):
        return _EXIFTOOL_CACHE
    exe = "exiftool.exe" if os.name == "nt" else "exiftool"
    app_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for candidate in (os.path.join(app_dir, "bin", exe), os.path.join(app_dir, exe)):
        if os.path.exists(candidate):
            _EXIFTOOL_CACHE = candidate
            return candidate
    found = shutil.which("exiftool")
    if found:
        _EXIFTOOL_CACHE = found
    return found


# ---------------------------------------------------------------------------
# Coordinate helpers
# ---------------------------------------------------------------------------

def parse_coordinates(text: str) -> Optional[Tuple[float, float]]:
    """Parse 'lat, lon' text as copied from Google Maps."""
    m = re.match(r"\s*(-?\d+(?:\.\d+)?)\s*[,;]\s*(-?\d+(?:\.\d+)?)\s*$", text)
    if not m:
        return None
    lat, lon = float(m.group(1)), float(m.group(2))
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


def read_gps_from_photo(path: str) -> Optional[Tuple[float, float, Optional[float]]]:
    """Read decimal (lat, lon, altitude) from a photo's EXIF, or None."""
    try:
        with open(path, "rb") as f:
            tags = exifread.process_file(f, details=False)
    except Exception:
        return None

    def dms_to_decimal(tag, ref) -> Optional[float]:
        if tag is None or ref is None:
            return None
        try:
            d, m, s = [float(Fraction(str(v))) for v in tag.values]
        except (ValueError, ZeroDivisionError, AttributeError):
            return None
        value = d + m / 60 + s / 3600
        if str(ref).strip().upper() in ("S", "W"):
            value = -value
        return value

    lat = dms_to_decimal(tags.get("GPS GPSLatitude"), tags.get("GPS GPSLatitudeRef"))
    lon = dms_to_decimal(tags.get("GPS GPSLongitude"), tags.get("GPS GPSLongitudeRef"))
    if lat is None or lon is None or (lat == 0 and lon == 0):
        # The Osmo writes a zeroed block - treat 0,0 as "no GPS".
        return None
    alt = None
    alt_tag = tags.get("GPS GPSAltitude")
    if alt_tag is not None:
        try:
            alt = float(Fraction(str(alt_tag.values[0])))
        except (ValueError, ZeroDivisionError):
            alt = None
    return lat, lon, alt


def read_current_gps_label(path: str) -> str:
    gps = read_gps_from_photo(path)
    if not gps:
        return ""
    return f"{gps[0]:.5f}, {gps[1]:.5f}"


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------

def _decimal_to_dms_rational(value: float):
    value = abs(value)
    degrees = int(value)
    minutes_f = (value - degrees) * 60
    minutes = int(minutes_f)
    seconds = round((minutes_f - minutes) * 60 * 10000)
    return ((degrees, 1), (minutes, 1), (seconds, 10000))


def write_gps_jpg(path: str, lat: float, lon: float, alt: Optional[float]) -> None:
    try:
        exif_dict = piexif.load(path)
    except Exception:
        exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}

    gps = {
        piexif.GPSIFD.GPSVersionID: (2, 3, 0, 0),
        piexif.GPSIFD.GPSLatitudeRef: b"N" if lat >= 0 else b"S",
        piexif.GPSIFD.GPSLatitude: _decimal_to_dms_rational(lat),
        piexif.GPSIFD.GPSLongitudeRef: b"E" if lon >= 0 else b"W",
        piexif.GPSIFD.GPSLongitude: _decimal_to_dms_rational(lon),
        piexif.GPSIFD.GPSStatus: b"A",   # 'A' = measurement active/valid
        piexif.GPSIFD.GPSMapDatum: b"WGS-84",
    }
    if alt is not None:
        gps[piexif.GPSIFD.GPSAltitudeRef] = 0 if alt >= 0 else 1
        gps[piexif.GPSIFD.GPSAltitude] = (abs(int(alt * 100)), 100)
    exif_dict["GPS"] = gps
    piexif.insert(piexif.dump(exif_dict), path)


def write_gps_exiftool(exiftool: str, path: str, lat: float, lon: float,
                       alt: Optional[float]) -> None:
    cmd = [exiftool, "-overwrite_original", "-m",
           f"-GPSLatitude={abs(lat)}", f"-GPSLatitudeRef={'N' if lat >= 0 else 'S'}",
           f"-GPSLongitude={abs(lon)}", f"-GPSLongitudeRef={'E' if lon >= 0 else 'W'}",
           "-GPSStatus=A", "-GPSMapDatum=WGS-84"]
    if alt is not None:
        cmd += [f"-GPSAltitude={abs(alt)}", f"-GPSAltitudeRef={0 if alt >= 0 else 1}"]
    ext = os.path.splitext(path)[1].lower()
    if ext in (".mp4", ".mov"):
        # QuickTime files also carry a composite location key many players use.
        cmd += [f"-Keys:GPSCoordinates={lat}, {lon}" + (f", {alt}" if alt is not None else "")]
    cmd.append(path)
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    out = subprocess.run(cmd, capture_output=True, timeout=120, **kwargs)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.decode("utf-8", "replace").strip() or "exiftool error")


# ---------------------------------------------------------------------------
# Batch worker
# ---------------------------------------------------------------------------

@dataclass
class GeotagJob:
    path: str
    selected: bool = True
    current_gps: str = ""
    status: str = "queued"     # queued | done | failed | skipped


class GeotagWorker(QThread):
    progress = Signal(int, int, str)     # done, total, name
    job_done = Signal(int, str)          # index, status
    all_done = Signal(int, int, list)    # written, skipped, errors

    def __init__(self, jobs: List[GeotagJob], lat: float, lon: float,
                 alt: Optional[float], parent=None):
        super().__init__(parent)
        self.jobs = jobs
        self.lat, self.lon, self.alt = lat, lon, alt
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        exiftool = find_exiftool()
        written = skipped = 0
        errors: list[str] = []
        total = len(self.jobs)

        for idx, job in enumerate(self.jobs):
            if self._cancel:
                break
            name = os.path.basename(job.path)
            self.progress.emit(idx + 1, total, name)
            if not job.selected:
                job.status = "skipped"
                skipped += 1
                self.job_done.emit(idx, job.status)
                continue

            ext = os.path.splitext(job.path)[1].lower()
            try:
                st = os.stat(job.path)
                if ext in JPG_EXTS:
                    write_gps_jpg(job.path, self.lat, self.lon, self.alt)
                elif ext in EXIFTOOL_EXTS:
                    if not exiftool:
                        job.status = "skipped"
                        skipped += 1
                        errors.append(f"{name}: needs ExifTool (not installed)")
                        self.job_done.emit(idx, job.status)
                        continue
                    write_gps_exiftool(exiftool, job.path, self.lat, self.lon, self.alt)
                else:
                    job.status = "skipped"
                    skipped += 1
                    self.job_done.emit(idx, job.status)
                    continue
                # Restore the original modification time - history intact.
                os.utime(job.path, (st.st_atime, st.st_mtime))
                job.status = "done"
                written += 1
            except Exception as exc:
                job.status = "failed"
                errors.append(f"{name}: {exc}")
            self.job_done.emit(idx, job.status)

        self.all_done.emit(written, skipped, errors)
