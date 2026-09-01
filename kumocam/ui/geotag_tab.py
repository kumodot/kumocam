"""Geotag tab (V4): batch GPS writing from a reference photo or pasted
coordinates."""

from __future__ import annotations

import os
from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QFileDialog, QGroupBox, QGridLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..core.geotag import (
    EXIFTOOL_EXTS, JPG_EXTS, GeotagJob, GeotagWorker, find_exiftool,
    parse_coordinates, read_current_gps_label, read_gps_from_photo,
)

MEDIA_EXTS = JPG_EXTS | EXIFTOOL_EXTS


class GeotagTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.jobs: List[GeotagJob] = []
        self.worker: Optional[GeotagWorker] = None
        self.coords: Optional[tuple] = None      # (lat, lon, alt|None)
        self._build_ui()
        self._check_exiftool()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        info = QLabel(
            "The Osmo Pocket has no GPS. Pick the location from a reference "
            "photo (e.g. taken with your phone at the same spot) or paste "
            "coordinates from Google Maps (right-click the map, copy the "
            "numbers), then write them to all selected files. "
            "Original file dates are preserved.")
        info.setWordWrap(True)
        layout.addWidget(info)

        # --- Location source ----------------------------------------------
        loc_group = QGroupBox("Location")
        lg = QGridLayout(loc_group)
        btn_ref = QPushButton("From reference photo...")
        btn_ref.clicked.connect(self.pick_reference)
        lg.addWidget(btn_ref, 0, 0)
        self.btn_map = QPushButton("Pick on map...")
        self.btn_map.clicked.connect(self.pick_on_map)
        lg.addWidget(self.btn_map, 0, 1)
        lg.addWidget(QLabel("or paste coordinates:"), 0, 2)
        self.edit_coords = QLineEdit()
        self.edit_coords.setPlaceholderText("e.g. 43.65348, -79.38393")
        self.edit_coords.textChanged.connect(self._coords_typed)
        lg.addWidget(self.edit_coords, 0, 3)
        self.lbl_coords = QLabel("No location set.")
        self.lbl_coords.setStyleSheet("font-weight: 600;")
        lg.addWidget(self.lbl_coords, 1, 0, 1, 4)
        layout.addWidget(loc_group)

        # --- File pickers --------------------------------------------------
        src_row = QHBoxLayout()
        btn_files = QPushButton("Add files...")
        btn_files.clicked.connect(self.add_files)
        btn_folder = QPushButton("Add folder...")
        btn_folder.clicked.connect(self.add_folder)
        btn_clear = QPushButton("Clear list")
        btn_clear.clicked.connect(self.clear_list)
        src_row.addWidget(btn_files)
        src_row.addWidget(btn_folder)
        src_row.addWidget(btn_clear)
        src_row.addStretch(1)
        layout.addLayout(src_row)

        # --- Table ---------------------------------------------------------
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["", "File", "Type", "Current GPS", "Status"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        for col, width in enumerate([36, 420, 80, 180, 140]):
            self.table.setColumnWidth(col, width)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self._filling = False
        self.table.itemChanged.connect(self._item_changed)
        layout.addWidget(self.table, stretch=1)

        # --- Run -----------------------------------------------------------
        run_row = QHBoxLayout()
        self.btn_apply = QPushButton("Write GPS to selected files")
        self.btn_apply.setProperty("accent", True)
        self.btn_apply.setEnabled(False)
        self.btn_apply.clicked.connect(self.start_write)
        run_row.addStretch(1)
        run_row.addWidget(self.btn_apply)
        layout.addLayout(run_row)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.status = QLabel("Set a location and add files.")
        layout.addWidget(self.status)

    # ------------------------------------------------------------ location
    def pick_reference(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Reference photo with GPS", "", "Photos (*.jpg *.jpeg *.JPG *.JPEG)")
        if not path:
            return
        gps = read_gps_from_photo(path)
        if not gps:
            QMessageBox.information(
                self, "No GPS found",
                "That photo has no GPS coordinates in its EXIF "
                "(or they are zeroed). Try a photo taken with your phone.")
            return
        self.coords = gps
        self.edit_coords.blockSignals(True)
        self.edit_coords.setText(f"{gps[0]:.6f}, {gps[1]:.6f}")
        self.edit_coords.blockSignals(False)
        alt_txt = f", altitude {gps[2]:.0f} m" if gps[2] is not None else ""
        self.lbl_coords.setText(
            f"Location set: {gps[0]:.6f}, {gps[1]:.6f}{alt_txt} "
            f"(from {os.path.basename(path)})")
        self._update_apply()

    def pick_on_map(self):
        from .map_dialog import WEBENGINE_AVAILABLE, MapPickerDialog
        if not WEBENGINE_AVAILABLE:
            QMessageBox.information(
                self, "Map unavailable",
                "Qt WebEngine is not installed in this environment. "
                "Paste coordinates from Google Maps instead.")
            return
        initial = (self.coords[0], self.coords[1]) if self.coords else None
        dialog = MapPickerDialog(initial, self)
        if dialog.exec() and dialog.coords:
            lat, lon = dialog.coords
            self.coords = (lat, lon, None)
            self.edit_coords.blockSignals(True)
            self.edit_coords.setText(f"{lat:.6f}, {lon:.6f}")
            self.edit_coords.blockSignals(False)
            self.lbl_coords.setText(f"Location set: {lat:.6f}, {lon:.6f} (from map)")
            self._update_apply()

    def _coords_typed(self, text: str):
        parsed = parse_coordinates(text)
        if parsed:
            self.coords = (parsed[0], parsed[1], None)
            self.lbl_coords.setText(f"Location set: {parsed[0]:.6f}, {parsed[1]:.6f}")
        else:
            self.coords = None
            self.lbl_coords.setText(
                "No location set." if not text.strip()
                else "Could not parse - expected 'latitude, longitude'.")
        self._update_apply()

    # ---------------------------------------------------------------- files
    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Add photos/videos", "",
            "Media (*.jpg *.jpeg *.dng *.mp4 *.mov *.JPG *.JPEG *.DNG *.MP4 *.MOV)")
        self._add_paths(files)

    def add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Add folder")
        if not folder:
            return
        found = []
        for dirpath, _, filenames in os.walk(folder):
            for f in sorted(filenames):
                if os.path.splitext(f)[1].lower() in MEDIA_EXTS:
                    found.append(os.path.join(dirpath, f))
        self._add_paths(found)

    def _add_paths(self, paths: List[str]):
        existing = {os.path.normpath(j.path) for j in self.jobs}
        added = 0
        for p in paths:
            if os.path.normpath(p) in existing:
                continue
            job = GeotagJob(path=p)
            if os.path.splitext(p)[1].lower() in JPG_EXTS:
                job.current_gps = read_current_gps_label(p)
            self.jobs.append(job)
            added += 1
        if added:
            self._fill_table()
        self.status.setText(f"{len(self.jobs)} files listed.")
        self._update_apply()

    def clear_list(self):
        self.jobs.clear()
        self._fill_table()
        self.status.setText("List cleared.")
        self._update_apply()

    def _fill_table(self):
        exiftool = find_exiftool()
        self._filling = True
        self.table.setRowCount(0)
        for job in self.jobs:
            row = self.table.rowCount()
            self.table.insertRow(row)
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            chk.setCheckState(Qt.Checked if job.selected else Qt.Unchecked)
            self.table.setItem(row, 0, chk)
            ext = os.path.splitext(job.path)[1].upper().lstrip(".")
            status = job.status
            if ext.lower() not in ("jpg", "jpeg") and not exiftool and status == "queued":
                status = "needs ExifTool"
            for col, val in enumerate([os.path.basename(job.path), ext,
                                       job.current_gps or "-", status], start=1):
                self.table.setItem(row, col, QTableWidgetItem(val))
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

    def _update_apply(self):
        self.btn_apply.setEnabled(bool(self.coords) and bool(self.jobs))

    # ----------------------------------------------------------------- run
    def start_write(self):
        if not self.coords:
            return
        selected = [j for j in self.jobs if j.selected]
        if not selected:
            QMessageBox.information(self, "Nothing selected", "Tick at least one file.")
            return
        lat, lon, alt = self.coords
        answer = QMessageBox.question(
            self, "Write GPS",
            f"Write {lat:.6f}, {lon:.6f} into {len(selected)} file(s)?\n"
            "The files are modified in place (dates preserved).")
        if answer != QMessageBox.Yes:
            return

        self.btn_apply.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setMaximum(len(self.jobs))
        self.progress.setValue(0)

        self.worker = GeotagWorker(self.jobs, lat, lon, alt)
        self.worker.progress.connect(self._on_progress)
        self.worker.job_done.connect(self._on_job_done)
        self.worker.all_done.connect(self._on_all_done)
        self.worker.start()

    def _on_progress(self, done: int, total: int, name: str):
        self.progress.setValue(done)
        self.status.setText(f"Writing GPS {done}/{total}: {name}")

    def _on_job_done(self, idx: int, status: str):
        if self.table.item(idx, 4):
            self.table.item(idx, 4).setText(status)
        if status == "done" and idx < len(self.jobs):
            job = self.jobs[idx]
            if os.path.splitext(job.path)[1].lower() in JPG_EXTS:
                label = read_current_gps_label(job.path)
                if self.table.item(idx, 3):
                    self.table.item(idx, 3).setText(label or "-")

    def _on_all_done(self, written: int, skipped: int, errors: list):
        self.progress.setVisible(False)
        self._update_apply()
        msg = f"Geotagging finished: {written} written, {skipped} skipped."
        self.status.setText(msg)
        if errors:
            QMessageBox.warning(self, "Geotagging finished with notes",
                                msg + "\n\n" + "\n".join(errors[:10]))
        else:
            QMessageBox.information(self, "Geotagging finished", msg)

    # ------------------------------------------------------------------ misc
    def _check_exiftool(self):
        if not find_exiftool():
            self.status.setText(
                "Note: ExifTool not found - JPGs work, but DNG/MP4 need it. "
                "Install ExifTool or place exiftool.exe in the app's bin folder.")
