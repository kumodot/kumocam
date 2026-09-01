"""Settings tab: user-adjustable thresholds and options, persisted via
QSettings so they survive between runs."""

from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox,
    QVBoxLayout, QWidget,
)

DEFAULTS = {
    "tiny_video_mb": 1.0,     # video under this = red (possibly corrupted)
    "tiny_photo_kb": 100,     # photo under this = red
    "huge_video_gb": 2.0,     # video over this = orange
}

THEMES = ["dark", "light"]


def get_setting(key: str) -> float:
    settings = QSettings("OsmoCompanion", "OsmoCompanion")
    try:
        return float(settings.value(f"thresholds/{key}", DEFAULTS[key]))
    except (TypeError, ValueError):
        return DEFAULTS[key]


def get_str_setting(key: str) -> str:
    settings = QSettings("OsmoCompanion", "OsmoCompanion")
    return str(settings.value(key, "") or "")


def get_theme() -> str:
    settings = QSettings("OsmoCompanion", "OsmoCompanion")
    value = str(settings.value("theme", "dark"))
    return value if value in THEMES else "dark"


def apply_theme(variant: str) -> None:
    from .theme import get_qss
    app = QApplication.instance()
    if app is not None:
        app.setStyleSheet(get_qss(variant))


class SettingsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = QSettings("OsmoCompanion", "OsmoCompanion")
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        # --- Appearance ---------------------------------------------------
        appearance = QGroupBox("Appearance")
        af = QFormLayout(appearance)
        self.combo_theme = QComboBox()
        self.combo_theme.addItems(["Dark", "Light"])
        self.combo_theme.setCurrentIndex(THEMES.index(get_theme()))
        self.combo_theme.currentIndexChanged.connect(self._theme_changed)
        af.addRow("Theme:", self.combo_theme)
        layout.addWidget(appearance)

        # --- Default folders ----------------------------------------------
        folders = QGroupBox("Default folders")
        ff = QFormLayout(folders)
        self.edit_default_target = self._folder_row(
            ff, "Default import target:", "default_target",
            "Every import goes here unless you pick another folder. "
            "Empty = remember the last used target.")
        self.edit_default_lut = self._folder_row(
            ff, "Default LUT folder:", "default_lut_folder",
            "Where your .cube LUT files live. The Convert tab looks here "
            "first. Download official LUTs from your camera maker's site "
            "(e.g. dji.com/lut) - they cannot be bundled with this app.")
        self.edit_profiles = self._folder_row(
            ff, "Camera profiles folder:", "profiles_folder",
            "Extra camera profile .json files (they extend or override the "
            "bundled DJI Osmo / Lumix / iPhone profiles). Loaded at startup.")
        layout.addWidget(folders)

        # --- Import table columns -----------------------------------------
        cols_group = QGroupBox("Import table columns")
        cg = QHBoxLayout(cols_group)
        self._col_boxes = {}
        from PySide6.QtWidgets import QCheckBox
        for label, key in [("Type", "type"), ("Original name", "original"),
                           ("New name", "new_name"), ("Date", "date"),
                           ("Resolution", "resolution"), ("FPS", "fps"),
                           ("Gamma", "gamma"), ("Camera", "camera"),
                           ("Size", "size"), ("Library", "library")]:
            box = QCheckBox(label)
            box.setChecked(self.settings.value(f"columns/{key}", "true") in (True, "true"))
            box.toggled.connect(
                lambda checked, k=key: self.settings.setValue(f"columns/{k}", checked))
            self._col_boxes[key] = box
            cg.addWidget(box)
        layout.addWidget(cols_group)

        group = QGroupBox("File size warnings (Import scan)")
        form = QFormLayout(group)

        self.spin_tiny_video = QDoubleSpinBox()
        self.spin_tiny_video.setRange(0.01, 100.0)
        self.spin_tiny_video.setDecimals(2)
        self.spin_tiny_video.setSuffix(" MB")
        self.spin_tiny_video.setValue(get_setting("tiny_video_mb"))
        form.addRow("Flag videos SMALLER than (red, possibly corrupted):",
                    self.spin_tiny_video)

        self.spin_tiny_photo = QSpinBox()
        self.spin_tiny_photo.setRange(1, 10_000)
        self.spin_tiny_photo.setSuffix(" KB")
        self.spin_tiny_photo.setValue(int(get_setting("tiny_photo_kb")))
        form.addRow("Flag photos SMALLER than (red, possibly corrupted):",
                    self.spin_tiny_photo)

        self.spin_huge_video = QDoubleSpinBox()
        self.spin_huge_video.setRange(0.1, 500.0)
        self.spin_huge_video.setDecimals(1)
        self.spin_huge_video.setSuffix(" GB")
        self.spin_huge_video.setValue(get_setting("huge_video_gb"))
        form.addRow("Flag videos LARGER than (orange):", self.spin_huge_video)

        for w in (self.spin_tiny_video, self.spin_tiny_photo, self.spin_huge_video):
            w.valueChanged.connect(self._save)

        layout.addWidget(group)

        row = QHBoxLayout()
        btn_defaults = QPushButton("Restore defaults")
        btn_defaults.clicked.connect(self._restore_defaults)
        row.addWidget(btn_defaults)
        row.addStretch(1)
        layout.addLayout(row)

        note = QLabel("Changes are saved immediately and applied on the next scan.")
        note.setStyleSheet("color: palette(mid); font-style: italic;")
        layout.addWidget(note)
        layout.addStretch(1)

    def _save(self):
        self.settings.setValue("thresholds/tiny_video_mb", self.spin_tiny_video.value())
        self.settings.setValue("thresholds/tiny_photo_kb", self.spin_tiny_photo.value())
        self.settings.setValue("thresholds/huge_video_gb", self.spin_huge_video.value())

    def _folder_row(self, form: QFormLayout, label: str, key: str,
                    tooltip: str) -> QLineEdit:
        row = QHBoxLayout()
        edit = QLineEdit()
        edit.setText(get_str_setting(key))
        edit.setToolTip(tooltip)
        edit.editingFinished.connect(
            lambda e=edit, k=key: self.settings.setValue(k, e.text().strip()))
        btn = QPushButton("Browse...")

        def browse():
            folder = QFileDialog.getExistingDirectory(self, label, edit.text())
            if folder:
                edit.setText(folder)
                self.settings.setValue(key, folder)

        btn.clicked.connect(browse)
        row.addWidget(edit, stretch=1)
        row.addWidget(btn)
        form.addRow(label, row)
        return edit

    def _theme_changed(self, index: int):
        variant = THEMES[index]
        self.settings.setValue("theme", variant)
        apply_theme(variant)

    def _restore_defaults(self):
        self.spin_tiny_video.setValue(DEFAULTS["tiny_video_mb"])
        self.spin_tiny_photo.setValue(DEFAULTS["tiny_photo_kb"])
        self.spin_huge_video.setValue(DEFAULTS["huge_video_gb"])
