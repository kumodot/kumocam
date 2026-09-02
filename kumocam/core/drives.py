"""Source volume detection.

When the Osmo Pocket is plugged in over USB it mounts two volumes:
the internal memory (label 'Pocket4P' on the Pocket 4P) and the SD card.
This module lists candidate volumes so the user can tick both for scanning.
"""

from __future__ import annotations

import os
import string
import sys
from dataclasses import dataclass
from typing import List

DJI_LABEL_HINTS = ("pocket", "osmo", "dji")


@dataclass
class Volume:
    path: str
    label: str
    looks_like_osmo: bool = False

    @property
    def display(self) -> str:
        return f"{self.label or 'Untitled'} ({self.path})"


def list_volumes() -> List[Volume]:
    if os.name == "nt":
        return _windows_volumes()
    if sys.platform == "darwin":
        return _mac_volumes()
    return _linux_volumes()


def _windows_volumes() -> List[Volume]:
    import ctypes

    volumes: List[Volume] = []
    kernel32 = ctypes.windll.kernel32
    bitmask = kernel32.GetLogicalDrives()
    for i, letter in enumerate(string.ascii_uppercase):
        if not bitmask & (1 << i):
            continue
        root = f"{letter}:\\"
        drive_type = kernel32.GetDriveTypeW(ctypes.c_wchar_p(root))
        # 2 = removable, 3 = fixed. The Osmo internal drive mounts as removable.
        if drive_type not in (2, 3):
            continue
        label_buf = ctypes.create_unicode_buffer(261)
        fs_buf = ctypes.create_unicode_buffer(261)
        ok = kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(root), label_buf, 260, None, None, None, fs_buf, 260)
        label = label_buf.value if ok else ""
        vol = Volume(path=root, label=label)
        vol.looks_like_osmo = _looks_like_osmo(vol)
        # Only auto-list removable drives and any fixed drive that looks
        # like a camera; the user can add other folders manually.
        if drive_type == 2 or vol.looks_like_osmo:
            volumes.append(vol)
    return volumes


def _mac_volumes() -> List[Volume]:
    volumes = []
    base = "/Volumes"
    if os.path.isdir(base):
        for name in sorted(os.listdir(base)):
            path = os.path.join(base, name)
            if os.path.ismount(path):
                vol = Volume(path=path, label=name)
                vol.looks_like_osmo = _looks_like_osmo(vol)
                volumes.append(vol)
    return volumes


def _linux_volumes() -> List[Volume]:
    volumes = []
    user = os.environ.get("USER", "")
    for base in (f"/media/{user}", "/media", "/mnt"):
        if os.path.isdir(base):
            for name in sorted(os.listdir(base)):
                path = os.path.join(base, name)
                if os.path.isdir(path):
                    vol = Volume(path=path, label=name)
                    vol.looks_like_osmo = _looks_like_osmo(vol)
                    volumes.append(vol)
            break
    return volumes


def eject_volume(path: str) -> tuple:
    """Safely eject a removable volume ('H:\\' or '/Volumes/X').
    Returns (ok, message). Fails cleanly when files are still open."""
    if os.name == "nt":
        return _windows_eject(path)
    if sys.platform == "darwin":
        return _run_eject(["diskutil", "eject", path], path)
    return _run_eject(["umount", path], path)


def _run_eject(cmd, path: str) -> tuple:
    import subprocess
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"Eject failed for {path}: {exc}"
    if proc.returncode == 0:
        return True, f"Ejected {path}"
    detail = (proc.stderr or proc.stdout or "").strip().splitlines()
    return False, f"Eject failed for {path}: {detail[-1] if detail else 'unknown error'}"


def _windows_eject(path: str) -> tuple:
    """Lock, dismount and eject via DeviceIoControl (no admin required for
    removable drives, as long as no program holds files open on it)."""
    import ctypes
    import time

    letter = path.rstrip("\\/").rstrip(":")
    device = f"\\\\.\\{letter}:"
    kernel32 = ctypes.windll.kernel32

    GENERIC_READ, GENERIC_WRITE = 0x80000000, 0x40000000
    FILE_SHARE_READ, FILE_SHARE_WRITE = 0x1, 0x2
    OPEN_EXISTING = 3
    INVALID_HANDLE = ctypes.c_void_p(-1).value
    FSCTL_LOCK_VOLUME = 0x00090018
    FSCTL_DISMOUNT_VOLUME = 0x00090020
    IOCTL_STORAGE_MEDIA_REMOVAL = 0x002D4804
    IOCTL_STORAGE_EJECT_MEDIA = 0x002D4808

    handle = kernel32.CreateFileW(device, GENERIC_READ | GENERIC_WRITE,
                                  FILE_SHARE_READ | FILE_SHARE_WRITE,
                                  None, OPEN_EXISTING, 0, None)
    if handle == INVALID_HANDLE:
        return False, f"Eject failed for {path}: cannot open the drive"

    def ioctl(code, inbuf=None, insize=0):
        returned = ctypes.c_ulong(0)
        return bool(kernel32.DeviceIoControl(
            handle, code, inbuf, insize, None, 0,
            ctypes.byref(returned), None))

    try:
        locked = False
        for _ in range(5):  # a just-finished copy may hold the lock briefly
            if ioctl(FSCTL_LOCK_VOLUME):
                locked = True
                break
            time.sleep(0.5)
        if not locked:
            return False, (f"Eject failed for {path}: the drive is in use "
                           "(close Explorer windows or players using it)")
        ioctl(FSCTL_DISMOUNT_VOLUME)
        allow_removal = ctypes.c_ubyte(0)  # PreventMediaRemoval = FALSE
        ioctl(IOCTL_STORAGE_MEDIA_REMOVAL, ctypes.byref(allow_removal), 1)
        if not ioctl(IOCTL_STORAGE_EJECT_MEDIA):
            return False, f"Eject failed for {path}: device refused to eject"
        return True, f"Ejected {path} - safe to unplug"
    finally:
        kernel32.CloseHandle(handle)


def _looks_like_osmo(vol: Volume) -> bool:
    label = vol.label.lower()
    if any(h in label for h in DJI_LABEL_HINTS):
        return True
    # A DCIM folder full of DJI_* files is a strong hint for the SD card.
    dcim = os.path.join(vol.path, "DCIM")
    try:
        if os.path.isdir(dcim):
            for entry in os.listdir(dcim)[:20]:
                if "dji" in entry.lower() or "osmo" in entry.lower():
                    return True
    except OSError:
        pass
    return False
