"""KumoCam - entry point.

The camera import companion, built for the DJI Osmo Pocket 4 / 4P:
Lightroom-style import that organizes photos, videos and panoramas into
date folders with metadata-driven renaming, D-Log conversion, panorama
stitching and geotagging.

Run with:  python -m kumocam.main
"""

import os
import sys

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication


def _load_bundled_fonts() -> str:
    """Load the bundled Inter font (SIL OFL licensed). Returns the family
    name to use, falling back to a sensible system stack."""
    fonts_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "assets", "fonts")
    loaded_family = ""
    if os.path.isdir(fonts_dir):
        for fname in sorted(os.listdir(fonts_dir)):
            if fname.lower().endswith((".otf", ".ttf")):
                font_id = QFontDatabase.addApplicationFont(
                    os.path.join(fonts_dir, fname))
                families = QFontDatabase.applicationFontFamilies(font_id)
                if families and not loaded_family:
                    loaded_family = families[0]
    return loaded_family


def make_app_font() -> QFont:
    family = _load_bundled_fonts()
    font = QFont()
    if family:
        font.setFamily(family)
    else:
        for fallback in ("Segoe UI", "SF Pro Text", "Helvetica Neue",
                         "Noto Sans", "Arial"):
            font.setFamily(fallback)
            if font.exactMatch():
                break
    font.setPointSize(10)
    return font


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("KumoCam")
    app.setFont(make_app_font())

    # Window/taskbar icon (Kumodot brand mark).
    from PySide6.QtGui import QIcon
    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "assets", "kumocam.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    from .ui.settings_tab import apply_theme, get_str_setting, get_theme
    apply_theme(get_theme())

    # Load camera profiles (bundled + the user's profiles folder).
    from .core.profiles import load_profiles
    load_profiles(get_str_setting("profiles_folder"))

    from .ui.main_window import MainWindow
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
