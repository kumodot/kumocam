"""Main window: hosts the feature tabs (Import, Convert; Panorama and
Geotag are next on the roadmap)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMainWindow, QPushButton, QTabWidget

from .. import __version__
from .about_dialog import AboutDialog
from .convert_tab import ConvertTab
from .geotag_tab import GeotagTab
from .import_tab import ImportTab
from .panorama_tab import PanoramaTab


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        # Version always visible so it's clear which build is running.
        self.setWindowTitle(f"KumoCam  v{__version__}")
        self.resize(1240, 820)
        # Allow shrinking well below the layout hints on any axis.
        self.setMinimumSize(760, 520)

        tabs = QTabWidget()
        self.import_tab = ImportTab()
        tabs.addTab(self.import_tab, "Import")
        tabs.addTab(ConvertTab(), "Convert")
        tabs.addTab(PanoramaTab(), "Panorama")
        tabs.addTab(GeotagTab(), "Geotag")
        from .settings_tab import SettingsTab
        tabs.addTab(SettingsTab(), "Settings")
        # Re-apply column visibility when returning to Import (the user may
        # have changed the column checkboxes in Settings meanwhile).
        tabs.currentChanged.connect(
            lambda idx: self.import_tab.apply_column_visibility() if idx == 0 else None)

        # About button in the tab-bar corner (credits dialog).
        btn_about = QPushButton("About")
        btn_about.setFlat(True)
        btn_about.setCursor(Qt.PointingHandCursor)
        btn_about.clicked.connect(self._show_about)
        tabs.setCornerWidget(btn_about, Qt.TopRightCorner)

        self.setCentralWidget(tabs)

    def _show_about(self):
        AboutDialog(self).exec()
