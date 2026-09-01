"""Filename builder: assembles the metadata tokens the user enabled into a
prefix or suffix, without ever touching the original name or file dates.

Example (prefix mode, all tokens on):
    4K_60fps_DLOG_DJI_20260824165237_0693_D.MP4
Example (suffix mode - keeps the serial ordering intact):
    DJI_20260824165237_0693_D_4K_60fps_DLOG.MP4
Slow motion:
    4K_SLOW100_REC709_DJI_20260824165159_0692_D.MP4
"""

from __future__ import annotations

from dataclasses import dataclass

from .scanner import MediaItem


@dataclass
class NamingOptions:
    use_resolution: bool = True
    use_fps: bool = True
    use_gamma: bool = True
    use_slow_motion: bool = True
    use_orientation: bool = False
    as_suffix: bool = False          # False = prefix (default)
    separator: str = "_"


def build_tokens(item: MediaItem, opts: NamingOptions) -> list[str]:
    meta = item.meta
    tokens: list[str] = []

    if opts.use_resolution:
        if item.kind == "video":
            if meta.resolution_label:
                tokens.append(meta.resolution_label)
        else:
            # Photos read better as megapixels (48MP, 8MP...)
            label = meta.megapixel_label or meta.resolution_label
            if label:
                tokens.append(label)

    if item.kind == "video":
        if opts.use_slow_motion and meta.is_slow_motion and meta.capture_fps:
            tokens.append(f"SLOW{int(meta.capture_fps)}")
        elif opts.use_fps and meta.fps_label:
            tokens.append(meta.fps_label)

        if opts.use_gamma and meta.gamma_label:
            tokens.append(meta.gamma_label)

    if opts.use_orientation and meta.orientation:
        tokens.append({"landscape": "LAND", "portrait": "PORT", "square": "SQR"}[meta.orientation])

    return tokens


def build_new_name(item: MediaItem, opts: NamingOptions) -> str:
    """New filename for a media file (panoramas are named by the importer)."""
    import os
    base = os.path.basename(item.src_path)
    stem, ext = os.path.splitext(base)
    tokens = build_tokens(item, opts)
    if not tokens:
        return base
    tag = opts.separator.join(tokens)
    if opts.as_suffix:
        return f"{stem}{opts.separator}{tag}{ext}"
    return f"{tag}{opts.separator}{stem}{ext}"


def apply_naming(items: list[MediaItem], opts: NamingOptions) -> None:
    for item in items:
        if item.kind == "panorama":
            item.new_name = item.display_name  # folder name is kept
        else:
            item.new_name = build_new_name(item, opts)
