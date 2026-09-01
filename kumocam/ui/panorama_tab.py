"""Panorama tab (V3): standalone stitching of Osmo segment folders."""

from __future__ import annotations

import os
from typing import List, Optional

from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFileDialog, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..core.stitcher import StitchJob, StitchOptions, StitchWorker, find_panorama_folders

SIZE_CHOICES = [("Full resolution", 0), ("Max width 8000 px", 8000), ("Max width 4000 px", 4000)]
PANO_PROFILES = [("DJI Osmo Pocket (default)", "dji-osmo-pocket"),
                 ("Generic camera (sequential)", "generic")]
WARN_BG = QColor(220, 60, 60, 70)   # translucent red, theme-safe


class PanoramaTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.jobs: List[StitchJob] = []
        self.worker: Optional[StitchWorker] = None
        self.settings = QSettings("OsmoCompanion", "OsmoCompanion")
        self._build_ui()
        saved = str(self.settings.value("pano_profile", "dji-osmo-pocket"))
        for i, (_, pid) in enumerate(PANO_PROFILES):
            if pid == saved:
                self.combo_profile.setCurrentIndex(i)
                break

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        info = QLabel(
            "Stitches Osmo panorama segment folders (PANORAMA/001_0104/PANO_0001.JPG...) "
            "into single images, named after each folder, inside a STITCH folder. "
            "Works with 3x3 and 180° panoramas.")
        info.setWordWrap(True)
        layout.addWidget(info)

        # Prominent warning, shown only when 3x3 panoramas are in the list.
        self.warn_3x3 = QLabel()
        self.warn_3x3.setWordWrap(True)
        self.warn_3x3.setStyleSheet(
            "background: rgba(220,60,60,0.16); color: palette(text);"
            "border: 1px solid rgba(220,60,60,0.55); border-radius: 6px;"
            "padding: 8px 12px; font-weight: 600;")
        self.warn_3x3.setVisible(False)
        layout.addWidget(self.warn_3x3)

        src_row = QHBoxLayout()
        btn_add = QPushButton("Add PANORAMA folder...")
        btn_add.clicked.connect(self.add_root)
        btn_clear = QPushButton("Clear list")
        btn_clear.clicked.connect(self.clear_list)
        src_row.addWidget(btn_add)
        src_row.addWidget(btn_clear)
        src_row.addStretch(1)
        layout.addLayout(src_row)

        opts_group = QGroupBox("Options")
        og = QHBoxLayout(opts_group)
        og.addWidget(QLabel("Camera profile:"))
        self.combo_profile = QComboBox()
        for label, _ in PANO_PROFILES:
            self.combo_profile.addItem(label)
        self.combo_profile.setToolTip(
            "The 3x3 grid order is specific to the Osmo Pocket. Pick "
            "'Generic' for panoramas shot with another camera (plain "
            "left-to-right matching).")
        self.combo_profile.currentIndexChanged.connect(self._profile_changed)
        og.addWidget(self.combo_profile)
        og.addWidget(QLabel("Projection:"))
        self.combo_projection = QComboBox()
        self.combo_projection.addItems([
            "Auto (3x3 spherical / 180\N{DEGREE SIGN} cylindrical)",
            "Spherical", "Cylindrical"])
        og.addWidget(self.combo_projection)
        og.addWidget(QLabel("Output size:"))
        self.combo_size = QComboBox()
        for label, _ in SIZE_CHOICES:
            self.combo_size.addItem(label)
        og.addWidget(self.combo_size)
        og.addWidget(QLabel("Output folder:"))
        self.edit_out = QLineEdit()
        self.edit_out.setPlaceholderText("Empty = STITCH folder beside the segment folders")
        og.addWidget(self.edit_out, stretch=1)
        btn_out = QPushButton("Browse...")
        btn_out.clicked.connect(self.pick_out)
        og.addWidget(btn_out)
        layout.addWidget(opts_group)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["", "Panorama", "Type", "Frames", "Status", "Result"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        for col, width in enumerate([36, 220, 110, 80, 130, 420]):
            self.table.setColumnWidth(col, width)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self._filling = False
        self.table.itemChanged.connect(self._item_changed)
        layout.addWidget(self.table, stretch=1)

        run_row = QHBoxLayout()
        self.btn_stitch = QPushButton("Stitch")
        self.btn_stitch.setProperty("accent", True)
        self.btn_stitch.setEnabled(False)
        self.btn_stitch.clicked.connect(self.start_stitch)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.cancel_stitch)
        run_row.addStretch(1)
        run_row.addWidget(self.btn_stitch)
        run_row.addWidget(self.btn_cancel)
        layout.addLayout(run_row)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.status = QLabel("Add a PANORAMA folder (or any folder containing panorama subfolders).")
        layout.addWidget(self.status)

    # ---------------------------------------------------------------- jobs
    def add_root(self):
        folder = QFileDialog.getExistingDirectory(self, "Add PANORAMA folder")
        if not folder:
            return
        existing = {os.path.normpath(j.folder) for j in self.jobs}
        found = [j for j in find_panorama_folders(folder)
                 if os.path.normpath(j.folder) not in existing]
        if not found:
            self.status.setText("No panorama segment folders found there.")
            return
        self.jobs.extend(found)
        self._fill_table()
        self._update_3x3_warning()
        self.btn_stitch.setEnabled(True)
        n_grid = sum(1 for j in self.jobs if len(j.files) == 9)
        n_180 = sum(1 for j in self.jobs if len(j.files) == 4)
        n_other = len(self.jobs) - n_grid - n_180
        parts = []
        if n_grid:
            parts.append(f"{n_grid} x 3x3 grid")
        if n_180:
            parts.append(f"{n_180} x 180\N{DEGREE SIGN}")
        if n_other:
            parts.append(f"{n_other} custom")
        self.status.setText(f"{len(self.jobs)} panoramas detected: " + ", ".join(parts))

    def clear_list(self):
        self.jobs.clear()
        self._fill_table()
        self._update_3x3_warning()
        self.btn_stitch.setEnabled(False)
        self.status.setText("List cleared.")

    def pick_out(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose output folder")
        if folder:
            self.edit_out.setText(folder)

    def _is_osmo_profile(self) -> bool:
        return PANO_PROFILES[self.combo_profile.currentIndex()][1] == "dji-osmo-pocket"

    def _profile_changed(self, index: int):
        self.settings.setValue("pano_profile", PANO_PROFILES[index][1])
        self._fill_table()
        self._update_3x3_warning()

    def _update_3x3_warning(self):
        n_3x3 = sum(1 for j in self.jobs if len(j.files) == 9)
        if n_3x3 and self._is_osmo_profile():
            self.warn_3x3.setText(
                f"\N{WARNING SIGN} {n_3x3} panorama(s) detected as Osmo 3x3 grid "
                "(marked red below). For 3x3, the native DJI Mimo app gives a "
                "noticeably better stitch - it knows the exact gimbal angles. "
                "This app handles 180\N{DEGREE SIGN} panoramas well; use it for "
                "3x3 only for batch convenience.")
            self.warn_3x3.setVisible(True)
        else:
            self.warn_3x3.setVisible(False)

    def _fill_table(self):
        self._filling = True
        self.table.setRowCount(0)
        osmo = self._is_osmo_profile()
        for job in self.jobs:
            row = self.table.rowCount()
            self.table.insertRow(row)
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            chk.setCheckState(Qt.Checked if job.selected else Qt.Unchecked)
            self.table.setItem(row, 0, chk)
            is_3x3 = osmo and len(job.files) == 9
            type_txt = job.type_label + ("  \N{WARNING SIGN} better in DJI Mimo" if is_3x3 else "")
            cells = [job.name, type_txt, str(len(job.files)), job.status, job.message]
            for col, val in enumerate(cells, start=1):
                cell = QTableWidgetItem(val)
                if is_3x3:
                    cell.setBackground(WARN_BG)
                    cell.setToolTip(
                        "Osmo 3x3 panorama: the native DJI Mimo app stitches "
                        "these better (it knows the exact gimbal angles).")
                self.table.setItem(row, col, cell)
        self._filling = False

    def _item_changed(self, titem: QTableWidgetItem):
        if self._filling:
            return
        if titem.column() != 0 or not (0 <= titem.row() < len(self.jobs)):
            return
        new_state = titem.checkState() == Qt.Checked
        self.jobs[titem.row()].selected = new_state
        from .table_utils import apply_check_to_selection
        apply_check_to_selection(self.table, self.jobs, titem.row(), new_state)

    # -------------------------------------------------------------- stitch
    def start_stitch(self):
        selected = [j for j in self.jobs if j.selected]
        if not selected:
            QMessageBox.information(self, "Nothing selected", "Tick at least one panorama.")
            return
        try:
            import cv2  # noqa: F401
        except ImportError:
            QMessageBox.warning(
                self, "OpenCV missing",
                "The stitcher needs OpenCV. Run:\n\npip install opencv-python-headless")
            return

        options = StitchOptions(
            output_root=self.edit_out.text().strip(),
            projection=["auto", "spherical", "cylindrical"][self.combo_projection.currentIndex()],
            max_output_width=SIZE_CHOICES[self.combo_size.currentIndex()][1],
            pano_profile=PANO_PROFILES[self.combo_profile.currentIndex()][1],
        )
        self.btn_stitch.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.progress.setVisible(True)
        self.progress.setMaximum(100)   # per-panorama stage progress
        self.progress.setValue(0)
        self._n_selected = len(selected)
        self._n_finished = 0

        self.worker = StitchWorker(self.jobs, options)
        self.worker.job_started.connect(self._job_started)
        self.worker.job_progress.connect(self._job_progress)
        self.worker.job_done.connect(self._job_done)
        self.worker.all_done.connect(self._all_done)
        self.worker.start()

    def cancel_stitch(self):
        if self.worker:
            self.worker.cancel()
            self.status.setText("Cancelling after the current panorama...")

    def _job_started(self, idx: int, name: str):
        self._current_name = name
        self.progress.setValue(0)
        self.status.setText(
            f"Stitching {name} ({self._n_finished + 1}/{self._n_selected})...")
        self._set_cells(idx, "running", "")

    def _job_progress(self, idx: int, percent: int, stage: str):
        self.progress.setValue(percent)
        self.status.setText(
            f"Stitching {self._current_name} "
            f"({self._n_finished + 1}/{self._n_selected}): {stage}")

    def _job_done(self, idx: int, status: str, message: str):
        self._set_cells(idx, status, message)
        self._n_finished += 1
        self.progress.setValue(100)

    def _set_cells(self, row: int, status: str, message: str):
        if self.table.item(row, 4):
            self.table.item(row, 4).setText(status)
        if self.table.item(row, 5):
            self.table.item(row, 5).setText(message)
        # Keep the red tint on 3x3 rows through status updates.
        if self._is_osmo_profile() and 0 <= row < len(self.jobs) and len(self.jobs[row].files) == 9:
            for col in (4, 5):
                if self.table.item(row, col):
                    self.table.item(row, col).setBackground(WARN_BG)

    def _all_done(self, done: int, failed: int):
        self.progress.setVisible(False)
        self.btn_stitch.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        msg = f"Stitching finished: {done} done, {failed} failed."
        if failed:
            msg += " Failed panoramas can be finished in PTGui or Lightroom."
        self.status.setText(msg)
        QMessageBox.information(self, "Stitching finished", msg)
