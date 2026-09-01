"""Library index: duplicate detection against a previously used target.

The importer never touches the original DJI name - it only adds a prefix or
suffix - and `DJI_<YYYYMMDDHHMMSS>_<serial>_D` is unique per capture. So the
"core identity" of any file in the library can be recovered from its
filename regardless of which rename tags were used at import time. This
makes duplicate detection manifest-free: the target is walked live, so it
never goes stale when files are moved or deleted outside the app.

Identities:
- media file: DJI core name + extension (JPG and DNG twins are distinct)
- panorama: the segment folder name (e.g. 001_0104), which the importer
  preserves under .../PANORAMA/<folder>/
"""

from __future__ import annotations

import os
import re
from typing import Set

# DJI_20260824165237_0693_D  (camera core name inside any renamed file)
_DJI_CORE_RE = re.compile(r"(DJI_\d{14}_\d{4}[A-Za-z0-9]*)", re.IGNORECASE)
_PANO_DIR_RE = re.compile(r"^\d{3}_\d{4}$")

# Rename tags this app can add (resolution, fps, gamma, slow, orientation).
# Needed for files whose ORIGINAL name is not DJI_* (e.g. $R6E6711.JPG):
# their identity is the original stem with any tags stripped from the ends.
_TAG_RE = re.compile(
    r"^(?:\d+(?:\.\d+)?K|FHD|HD|\d+MP|\d+px|\d+fps|SLOW\d+|DLOG2?|REC709|HLG|"
    r"LAND|PORT|SQR)$", re.IGNORECASE)

SKIP_DIRS = {"CONVERTED", "STITCH"}


def _strip_tags(stem: str) -> str:
    """Remove leading/trailing rename tags: '21MP_$R6E6711' -> '$R6E6711',
    '$R6E6711_21MP_PORT' -> '$R6E6711'."""
    parts = stem.split("_")
    while len(parts) > 1 and _TAG_RE.match(parts[0]):
        parts.pop(0)
    while len(parts) > 1 and _TAG_RE.match(parts[-1]):
        parts.pop()
    return "_".join(parts)


def file_key(filename: str) -> str:
    """Core identity of a media file name, ignoring rename tags."""
    stem, ext = os.path.splitext(os.path.basename(filename))
    m = _DJI_CORE_RE.search(stem)
    core = m.group(1).upper() if m else _strip_tags(stem).upper()
    return f"{core}{ext.lower()}"


def pano_key(folder_name: str) -> str:
    return f"PANO::{folder_name.upper()}"


def build_library_index(target: str) -> Set[str]:
    """Walk the target library and collect the identity keys of everything
    already imported. Fast: only reads directory names, never file content."""
    index: Set[str] = set()
    if not target or not os.path.isdir(target):
        return index
    for dirpath, dirnames, filenames in os.walk(target):
        dirnames[:] = [d for d in dirnames if d.upper() not in SKIP_DIRS]
        base = os.path.basename(dirpath)
        if _PANO_DIR_RE.match(base):
            index.add(pano_key(base))
        for fname in filenames:
            index.add(file_key(fname))
    return index
