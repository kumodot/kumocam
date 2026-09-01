"""About dialog: app credits and acknowledgments."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout

from .. import __version__

LOGO_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "assets", "logo.png")

ABOUT_HTML = f"""
<div style="text-align: center;">
  <h2 style="margin-bottom: 2px;">KumoCam</h2>
  <p style="margin-top: 0;">Version {__version__}<br>
  <span style="color: gray;">Built for the DJI Osmo Pocket &mdash; works with any camera.</span></p>
  <p style="font-size: 15px; margin: 18px 0 4px 0;">
    Created by <b>Marcelo Souza</b> /
    <a href="https://kumodot.art">Kumodot.art</a> &mdash; 2026
  </p>
  <p style="margin-top: 2px;">
    <a href="https://www.instagram.com/msouza3d/">@Msouza3d</a> (Instagram)
  </p>
  <p style="margin-top: 20px;">
    Import &amp; organize, convert with LUTs, stitch panoramas, geotag.
  </p>
  <p style="font-size: 13px; margin-top: 20px; font-weight: 600;">
    Unofficial app: this is an independent tool created by a fan,<br>
    NOT affiliated with, endorsed or supported by DJI.
  </p>
  <p style="color: gray; font-size: 12px; margin-top: 14px;">
    DJI, Osmo and Mimo are trademarks of DJI.<br>
    Built with Python, PySide6 (Qt), FFmpeg, OpenCV, exifread, Pillow,
    piexif and optionally ExifTool. UI font: Inter (SIL OFL).<br>
    License: GPL-3.0 with Commons Clause (non-commercial).
  </p>
</div>
"""


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About KumoCam")
        self.setFixedWidth(440)

        layout = QVBoxLayout(self)

        # Kumodot logo, small and centered.
        if os.path.exists(LOGO_PATH):
            logo = QLabel()
            pix = QPixmap(LOGO_PATH)
            if not pix.isNull():
                logo.setPixmap(pix.scaled(72, 72, Qt.KeepAspectRatio,
                                          Qt.SmoothTransformation))
                logo.setAlignment(Qt.AlignCenter)
                layout.addWidget(logo)

        label = QLabel(ABOUT_HTML)
        label.setWordWrap(True)
        label.setOpenExternalLinks(True)
        label.setTextInteractionFlags(Qt.TextBrowserInteraction)
        layout.addWidget(label)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.clicked.connect(self.accept)
        layout.addWidget(buttons)
