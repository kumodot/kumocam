"""Camera profiles: per-camera behavior and detection, defined in JSON.

Profiles live in two places, merged at load time:
- bundled defaults:   kumocam/profiles/*.json  (shipped with the app)
- user profiles:      <profiles folder from Settings, or ./camera_profiles>
  User files with the same "id" override bundled ones, so any camera can be
  added or tweaked without touching code.

A profile file looks like:

{
  "id": "dji-osmo-pocket",
  "name": "DJI Osmo Pocket",
  "match": {
    "exif_make":   "DJI",                 // regex, case-insensitive
    "exif_model":  "PP-\\d+|OsmoPocket",
    "encoder":     "DJI Osmo",            // video container 'encoder' tag
    "filename":    "^DJI_\\d{14}_\\d{4}"  // fallback when no metadata
  },
  "timestamp_in_filename": "DJI_(\\d{14})",   // local-time capture stamp
  "gamma_tags": ["com.dji.camera.ColorGammaSxS"],
  "skip_extensions": [".lrf"],
  "notes": "..."
}

Every field except id/name is optional. Detection per file: exif_make +
exif_model win, then encoder, then filename pattern; ties broken by rule
specificity. Files matching nothing use the 'generic' profile, which is
plain standards-based behavior (EXIF dates, container metadata).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

_BUNDLED_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "profiles")


@dataclass
class CameraProfile:
    id: str
    name: str
    match: Dict[str, str] = field(default_factory=dict)
    timestamp_in_filename: str = ""
    gamma_tags: List[str] = field(default_factory=list)
    skip_extensions: List[str] = field(default_factory=list)
    panorama: Dict = field(default_factory=dict)
    notes: str = ""

    def _rx(self, key: str) -> Optional[re.Pattern]:
        pattern = self.match.get(key)
        if not pattern:
            return None
        try:
            return re.compile(pattern, re.IGNORECASE)
        except re.error:
            return None

    def score(self, make: str, model: str, encoder: str, filename: str) -> int:
        """Higher = better match; 0 = no match."""
        score = 0
        rx = self._rx("exif_make")
        if rx and make:
            if not rx.search(make):
                return 0
            score += 4
        rx = self._rx("exif_model")
        if rx and model:
            if rx.search(model):
                score += 4
        rx = self._rx("encoder")
        if rx and encoder and rx.search(encoder):
            score += 3
        rx = self._rx("filename")
        if rx and rx.search(filename):
            score += 1
        return score


GENERIC = CameraProfile(id="generic", name="Generic camera")


def _load_dir(folder: str, out: Dict[str, CameraProfile]) -> None:
    if not folder or not os.path.isdir(folder):
        return
    for fname in sorted(os.listdir(folder)):
        if not fname.lower().endswith(".json"):
            continue
        try:
            with open(os.path.join(folder, fname), "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and data.get("id") and data.get("name"):
                out[data["id"]] = CameraProfile(
                    id=data["id"],
                    name=data["name"],
                    match=data.get("match", {}) or {},
                    timestamp_in_filename=data.get("timestamp_in_filename", ""),
                    gamma_tags=list(data.get("gamma_tags", []) or []),
                    skip_extensions=[e.lower() for e in data.get("skip_extensions", []) or []],
                    panorama=data.get("panorama", {}) or {},
                    notes=data.get("notes", ""),
                )
        except (OSError, json.JSONDecodeError):
            continue  # a broken profile file never breaks the app


_cache: Optional[List[CameraProfile]] = None


def load_profiles(user_folder: str = "") -> List[CameraProfile]:
    """Bundled profiles, overridden/extended by the user folder."""
    global _cache
    profiles: Dict[str, CameraProfile] = {}
    _load_dir(_BUNDLED_DIR, profiles)
    _load_dir(user_folder, profiles)
    _cache = list(profiles.values())
    return _cache


def get_profiles() -> List[CameraProfile]:
    return _cache if _cache is not None else load_profiles()


def detect_profile(make: str = "", model: str = "", encoder: str = "",
                   filename: str = "") -> CameraProfile:
    best, best_score = GENERIC, 0
    for profile in get_profiles():
        s = profile.score(make or "", model or "", encoder or "",
                          os.path.basename(filename or ""))
        if s > best_score:
            best, best_score = profile, s
    return best


def camera_label(make: str, model: str, profile: CameraProfile) -> str:
    """What the Camera column shows: real EXIF model when we have it,
    else the profile name, else '?'."""
    model = (model or "").strip()
    make = (make or "").strip()
    if model:
        if make and make.lower() not in model.lower():
            return f"{make} {model}"
        return model
    if profile.id != "generic":
        return profile.name
    return "?"
