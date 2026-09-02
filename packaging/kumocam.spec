# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for KumoCam (one-folder build).

Build from the repo root with:
    pyinstaller packaging/kumocam.spec --noconfirm

Before building, place ffmpeg.exe and ffprobe.exe (LGPL build) in
packaging/ffmpeg_bin/ - they ship in the app's bin/ folder, where
KumoCam already looks first. If the folder is missing, the app still
builds and falls back to FFmpeg from PATH.
"""

import os

ROOT = os.path.dirname(SPECPATH)  # repo root (spec lives in packaging/)

datas = [
    (os.path.join(ROOT, "kumocam", "assets"), os.path.join("kumocam", "assets")),
    (os.path.join(ROOT, "kumocam", "profiles"), os.path.join("kumocam", "profiles")),
]

# Ship everything in packaging/ffmpeg_bin (exes + shared DLLs + license)
# into the app's bin/ folder, where KumoCam already looks first.
# Shipped as datas, NOT binaries: PyInstaller's dependency analysis would
# otherwise copy every FFmpeg DLL a second time into the app root.
binaries = []
_ffdir = os.path.join(SPECPATH, "ffmpeg_bin")
if os.path.isdir(_ffdir):
    for _name in sorted(os.listdir(_ffdir)):
        _p = os.path.join(_ffdir, _name)
        if os.path.isfile(_p):
            datas.append((_p, "bin"))

a = Analysis(
    [os.path.join(SPECPATH, "run_kumocam.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "tkinter",
        # The map picker opens in the system browser - no embedded Chromium.
        "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineQuick", "PySide6.QtWebChannel",
        "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtQuickWidgets",
        "PySide6.QtPositioning", "PySide6.QtPdf", "PySide6.QtPdfWidgets",
    ],
    noarchive=False,
)
# Trim dead weight: Chromium devtools debug resources (72 MB, unused).
a.datas = [d for d in a.datas
           if "qtwebengine_devtools_resources.debug.pak" not in d[0]]

# PyInstaller re-analyzes the FFmpeg exes and copies their DLLs a second
# time into the app root. Drop those root-level duplicates - the copies in
# bin/ are the ones KumoCam uses (subprocess loads them from its own dir).
_in_bin = {os.path.basename(n).lower() for n, _s, _k in a.binaries
           if n.replace("\\", "/").lower().startswith("bin/")}
a.binaries = [b for b in a.binaries
              if not (os.path.dirname(b[0]) == ""
                      and os.path.basename(b[0]).lower() in _in_bin)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="KumoCam",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=os.path.join(ROOT, "kumocam", "assets", "kumocam.ico"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="KumoCam",
)
