"""Import tab: source selection, scan preview, naming options, import."""

from __future__ import annotations

import os
from typing import List, Optional

from PySide6.QtCore import Qt, QSettings, QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QGridLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QRadioButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from ..core.drives import list_volumes
from ..core.importer import ImportOptions, ImportWorker
from ..core.library import build_library_index, file_key, pano_key
from ..core.naming import NamingOptions, apply_naming
from ..core.probe import find_ffprobe
from ..core.scanner import MediaItem, ScanOptions, ScanResult, scan_sources

SIZE_UNITS = ["B", "KB", "MB", "GB", "TB"]

from .settings_tab import get_setting
from .table_utils import apply_check_to_selection

TINY_BG = QColor(220, 60, 60, 70)   # translucent red (works in both themes)
HUGE_BG = QColor(255, 150, 40, 60)  # translucent orange


def size_flag(item: MediaItem) -> str:
    """'' | 'tiny' (possibly corrupted) | 'huge' (unusually large video).
    Thresholds are user-adjustable in the Settings tab."""
    tiny_video = get_setting("tiny_video_mb") * 1_000_000
    tiny_photo = get_setting("tiny_photo_kb") * 1_000
    huge_video = get_setting("huge_video_gb") * 1_000_000_000
    if item.kind == "video":
        if item.size < tiny_video:
            return "tiny"
        if item.size > huge_video:
            return "huge"
    elif item.kind == "photo" and item.size < tiny_photo:
        return "tiny"
    elif item.kind == "panorama" and item.size < tiny_photo * 2:
        return "tiny"
    return ""


def human_size(n: float) -> str:
    for unit in SIZE_UNITS:
        if n < 1024 or unit == SIZE_UNITS[-1]:
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} TB"


class ScanWorker(QThread):
    progress = Signal(str)
    done = Signal(object)

    def __init__(self, sources: List[str], options: ScanOptions, parent=None):
        super().__init__(parent)
        self.sources = sources
        self.options = options
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        result = scan_sources(
            self.sources, self.options,
            progress=lambda msg: self.progress.emit(msg),
            cancelled=lambda: self._cancel,
        )
        self.done.emit(result)


class ImportTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.items: List[MediaItem] = []
        self.scan_worker: Optional[ScanWorker] = None
        self.import_worker: Optional[ImportWorker] = None
        self.settings = QSettings("OsmoCompanion", "OsmoCompanion")
        self._build_ui()
        # Target priority: default from Settings, else last used.
        from .settings_tab import get_str_setting
        target = get_str_setting("default_target") or self.settings.value("last_target", "")
        if target:
            self.edit_target.setText(target)
        # Remember the skip-red preference (default: on).
        self.chk_skip_red.blockSignals(True)
        self.chk_skip_red.setChecked(self.settings.value("skip_red", "true") in (True, "true"))
        self.chk_skip_red.blockSignals(False)
        self.edit_target.editingFinished.connect(self._recheck_library)
        self.refresh_volumes()
        self._check_ffprobe()
        self.apply_column_visibility()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        # --- Sources -------------------------------------------------------
        src_group = QGroupBox("Sources")
        src_layout = QHBoxLayout(src_group)
        self.volume_list = QListWidget()
        self.volume_list.setMaximumHeight(110)
        src_layout.addWidget(self.volume_list, stretch=1)

        src_buttons = QVBoxLayout()
        self.btn_refresh = QPushButton("Refresh drives")
        self.btn_refresh.clicked.connect(self.refresh_volumes)
        self.btn_add_folder = QPushButton("Add folder...")
        self.btn_add_folder.clicked.connect(self.add_folder)
        self.btn_scan = QPushButton("Scan")
        self.btn_scan.setProperty("accent", True)
        self._scanning = False
        self.btn_scan.clicked.connect(self._scan_or_stop)
        src_buttons.addWidget(self.btn_refresh)
        src_buttons.addWidget(self.btn_add_folder)
        src_buttons.addWidget(self.btn_scan)
        src_buttons.addStretch(1)
        src_layout.addLayout(src_buttons)
        layout.addWidget(src_group)

        # --- Options (grid layouts keep the minimum window width small) ----
        opts_row = QHBoxLayout()

        naming_group = QGroupBox("Filename tags (original name and file dates are never touched)")
        ng_outer = QHBoxLayout(naming_group)
        ng = QGridLayout()
        self.chk_resolution = QCheckBox("Resolution")
        self.chk_resolution.setToolTip("Adds 4K / FHD / 48MP to the filename")
        self.chk_fps = QCheckBox("Framerate")
        self.chk_fps.setToolTip("Adds 24fps / 60fps to the filename")
        self.chk_gamma = QCheckBox("Gamma")
        self.chk_gamma.setToolTip("Adds DLOG / REC709 to the filename")
        self.chk_slow = QCheckBox("Slow motion")
        self.chk_slow.setToolTip("Adds SLOW100 / SLOW200 to slow-motion clips")
        self.chk_orient = QCheckBox("Orientation")
        self.chk_orient.setToolTip("Adds LAND / PORT to the filename")
        for c in (self.chk_resolution, self.chk_fps, self.chk_gamma, self.chk_slow):
            c.setChecked(True)
        widgets = [self.chk_resolution, self.chk_fps, self.chk_gamma,
                   self.chk_slow, self.chk_orient]
        for i, w in enumerate(widgets):
            ng.addWidget(w, i % 2, i // 2)
            w.toggled.connect(self.refresh_names)
        ng_outer.addLayout(ng, stretch=1)

        # Prefix/Suffix rocker switch, visually separated from the tags.
        from .widgets import LabeledToggle, dashed_vline
        ng_outer.addWidget(dashed_vline())
        self.toggle_fix = LabeledToggle("Prefix", "Suffix", checked=False)
        self.toggle_fix.setToolTip("Where the tags go in the filename. "
                                   "Suffix keeps the serial number ordering intact.")
        self.toggle_fix.toggled.connect(lambda _: self.refresh_names())
        ng_outer.addWidget(self.toggle_fix)
        opts_row.addWidget(naming_group, stretch=3)

        import_group = QGroupBox("Import options")
        ig = QGridLayout(import_group)
        self.chk_aac = QCheckBox("Copy AAC sidecars")
        self.chk_aac.setChecked(True)
        self.chk_aac.setToolTip("Real-time audio of slow-motion clips / external mic recordings")
        self.chk_lrf = QCheckBox("Include proxies (LRF)")
        self.chk_lrf.setToolTip(
            "LRF files are the Osmo's low-resolution preview copies of each "
            "video. Skipped by default.")
        self.chk_lrf_mp4 = QCheckBox("LRF > MP4")
        self.chk_lrf_mp4.setEnabled(False)
        self.chk_lrf_mp4.setToolTip(
            "An LRF is just a low-resolution MP4. When enabled, imported "
            "proxies are renamed to <name>_LRF.MP4 so they play anywhere "
            "and never collide with the full-quality video.")
        self.chk_lrf.toggled.connect(self._lrf_toggled)
        self.chk_wav = QCheckBox("Include WAV audio")
        self.chk_split_orient = QCheckBox("Portrait/Landscape subfolders")
        self.combo_conflict = QComboBox()
        self.combo_conflict.addItems(["Skip existing files", "Rename duplicates (_1, _2)"])
        self.chk_skip_red = QCheckBox("Skip warning files (red)")
        self.chk_skip_red.setToolTip(
            "Automatically uncheck files flagged red (suspiciously small, "
            "possibly corrupted) after every scan.")
        self.chk_skip_red.toggled.connect(self._skip_red_toggled)
        ig.addWidget(self.chk_aac, 0, 0)
        ig.addWidget(self.chk_lrf, 1, 0)
        ig.addWidget(self.chk_lrf_mp4, 2, 0)
        ig.addWidget(self.chk_wav, 0, 1)
        ig.addWidget(self.chk_split_orient, 1, 1)
        ig.addWidget(self.combo_conflict, 0, 2)
        ig.addWidget(self.chk_skip_red, 1, 2)
        opts_row.addWidget(import_group, stretch=2)
        layout.addLayout(opts_row)

        # --- Results table -------------------------------------------------
        splitter = QSplitter(Qt.Vertical)

        # Column order; keys after index 0 are hideable via Settings.
        self.COLUMNS = [
            ("", 36, ""), ("Type", 120, "type"),
            ("Original name", 230, "original"), ("New name", 270, "new_name"),
            ("Date", 125, "date"), ("Resolution", 95, "resolution"),
            ("FPS", 65, "fps"), ("Gamma", 85, "gamma"),
            ("Camera", 140, "camera"), ("Size", 85, "size"),
            ("Library", 120, "library"),
        ]
        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels([c[0] for c in self.COLUMNS])
        header = self.table.horizontalHeader()
        # Interactive: the user can drag every column divider.
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(False)
        for col, (_, width, _key) in enumerate(self.COLUMNS):
            self.table.setColumnWidth(col, width)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self._filling_table = False
        self.table.itemChanged.connect(self._table_item_changed)
        splitter.addWidget(self.table)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Scan log: skipped files (LRF, WAV, MISC) and warnings appear here.")
        self.log.setMaximumHeight(140)
        splitter.addWidget(self.log)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, stretch=1)

        # --- Selection helpers --------------------------------------------
        sel_row = QHBoxLayout()
        self.btn_select_all = QPushButton("Select all")
        self.btn_select_none = QPushButton("Select none")
        self.btn_select_all.clicked.connect(lambda: self._set_all_selected(True))
        self.btn_select_none.clicked.connect(lambda: self._set_all_selected(False))
        self.lbl_summary = QLabel("")
        sel_row.addWidget(self.btn_select_all)
        sel_row.addWidget(self.btn_select_none)
        sel_row.addWidget(self.lbl_summary)
        sel_row.addStretch(1)
        layout.addLayout(sel_row)

        # --- Target + import ----------------------------------------------
        target_row = QHBoxLayout()
        target_row.addWidget(QLabel("Target folder:"))
        self.edit_target = QLineEdit()
        self.edit_target.setPlaceholderText("Choose where the organized files will be created...")
        btn_browse = QPushButton("Browse...")
        btn_browse.clicked.connect(self.pick_target)
        self.btn_import = QPushButton("Import")
        self.btn_import.setProperty("accent", True)
        self.btn_import.setEnabled(False)
        self.btn_import.clicked.connect(self.start_import)
        self.btn_cancel_import = QPushButton("Cancel")
        self.btn_cancel_import.setEnabled(False)
        self.btn_cancel_import.clicked.connect(self._cancel_import)
        target_row.addWidget(self.edit_target, stretch=1)
        target_row.addWidget(btn_browse)
        target_row.addWidget(self.btn_import)
        target_row.addWidget(self.btn_cancel_import)
        layout.addLayout(target_row)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.status = QLabel("Ready.")
        layout.addWidget(self.status)

    # ------------------------------------------------------------ sources
    def refresh_volumes(self):
        self.volume_list.clear()
        for vol in list_volumes():
            item = QListWidgetItem(vol.display)
            item.setData(Qt.UserRole, vol.path)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if vol.looks_like_osmo else Qt.Unchecked)
            if vol.looks_like_osmo:
                item.setText(vol.display + "   [Osmo detected]")
            self.volume_list.addItem(item)

    def add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Add source folder")
        if folder:
            item = QListWidgetItem(folder)
            item.setData(Qt.UserRole, folder)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.volume_list.addItem(item)

    def _checked_sources(self) -> List[str]:
        out = []
        for i in range(self.volume_list.count()):
            it = self.volume_list.item(i)
            if it.checkState() == Qt.Checked:
                out.append(it.data(Qt.UserRole))
        return out

    # --------------------------------------------------------------- scan
    def _scan_or_stop(self):
        if self._scanning:
            if self.scan_worker:
                self.scan_worker.cancel()
            self.btn_scan.setEnabled(False)
            self.status.setText("Stopping scan...")
        else:
            self.start_scan()

    def start_scan(self):
        sources = self._checked_sources()
        if not sources:
            QMessageBox.information(self, "No sources", "Tick at least one drive or folder to scan.")
            return
        self._scanning = True
        self.btn_scan.setText("Stop")
        self.btn_import.setEnabled(False)
        self.log.clear()
        self.status.setText("Scanning...")

        options = ScanOptions(
            include_lrf=self.chk_lrf.isChecked(),
            include_wav=self.chk_wav.isChecked(),
            copy_aac_sidecars=self.chk_aac.isChecked(),
        )
        self.scan_worker = ScanWorker(sources, options)
        self.scan_worker.progress.connect(self.status.setText)
        self.scan_worker.done.connect(self.scan_finished)
        self.scan_worker.start()

    def scan_finished(self, result: ScanResult):
        was_stopped = bool(self.scan_worker and self.scan_worker._cancel)
        self._scanning = False
        self.btn_scan.setText("Scan")
        self.btn_scan.setEnabled(True)
        self.items = result.items
        for line in result.skipped:
            self.log.appendPlainText(line)
        for line in result.errors:
            self.log.appendPlainText("ERROR: " + line)
        for item in result.items:
            for err in item.meta.errors:
                self.log.appendPlainText(f"WARN {item.display_name}: {err}")

        self._recheck_library(refresh_table=False)
        self._apply_skip_red()
        self.refresh_names()
        n_photo = sum(1 for i in self.items if i.kind == "photo")
        n_video = sum(1 for i in self.items if i.kind == "video")
        n_pano = sum(1 for i in self.items if i.kind == "panorama")
        n_dup = sum(1 for i in self.items if i.in_library)
        n_tiny = sum(1 for i in self.items if size_flag(i) == "tiny")
        n_huge = sum(1 for i in self.items if size_flag(i) == "huge")
        for i in self.items:
            if size_flag(i) == "tiny":
                self.log.appendPlainText(
                    f"WARN possibly corrupted (only {human_size(i.size)}): {i.display_name}")
        msg = ("Scan STOPPED (partial results): " if was_stopped else "Scan complete: ")
        msg += f"{n_photo} photos, {n_video} videos, {n_pano} panoramas."
        if n_dup:
            msg += f" {n_dup} already in the library (unchecked)."
        if n_tiny:
            msg += f" {n_tiny} possibly corrupted (red"
            msg += ", unchecked)." if self.chk_skip_red.isChecked() else ")."
        if n_huge:
            msg += f" {n_huge} very large (orange)."
        self.status.setText(msg)
        self.btn_import.setEnabled(bool(self.items))

    # ------------------------------------------------------- library check
    def _recheck_library(self, refresh_table: bool = True):
        """Match scanned items against what the target library already has,
        by core DJI name (rename tags are ignored)."""
        target = self.edit_target.text().strip()
        index = build_library_index(target)
        for item in self.items:
            if item.kind == "panorama":
                item.in_library = pano_key(item.display_name) in index
            else:
                item.in_library = file_key(item.src_path) in index
            if item.in_library:
                item.selected = False
        if refresh_table and self.items:
            self._fill_table()

    # ------------------------------------------------------------- naming
    def _naming_options(self) -> NamingOptions:
        return NamingOptions(
            use_resolution=self.chk_resolution.isChecked(),
            use_fps=self.chk_fps.isChecked(),
            use_gamma=self.chk_gamma.isChecked(),
            use_slow_motion=self.chk_slow.isChecked(),
            use_orientation=self.chk_orient.isChecked(),
            as_suffix=self.toggle_fix.checked,
        )

    def refresh_names(self):
        apply_naming(self.items, self._naming_options())
        self._fill_table()

    def _fill_table(self):
        self._filling_table = True
        self.table.setRowCount(0)
        total_size = 0
        for item in self.items:
            row = self.table.rowCount()
            self.table.insertRow(row)

            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            chk.setCheckState(Qt.Checked if item.selected else Qt.Unchecked)
            self.table.setItem(row, 0, chk)

            kind = {"photo": "Photo", "video": "Video", "panorama": "Panorama"}[item.kind]
            if item.kind == "video" and item.meta.is_slow_motion:
                kind = "Video (slow-mo)"
            if item.kind == "panorama":
                kind = f"Panorama ({len(item.pano_files)} frames)"
            meta = item.meta
            date_txt = meta.creation.strftime("%Y-%m-%d %H:%M") if meta.creation else "?"
            res_txt = f"{meta.width}x{meta.height}" if meta.width else "?"
            values = [kind, item.display_name, item.new_name, date_txt, res_txt,
                      meta.fps_label if item.kind == "video" else "",
                      meta.gamma_label if item.kind == "video" else "",
                      item.camera,
                      human_size(item.size),
                      "already imported" if item.in_library else "new"]
            flag = size_flag(item)
            for col, val in enumerate(values, start=1):
                cell = QTableWidgetItem(val)
                if item.in_library:
                    cell.setForeground(QColor(150, 150, 150))
                if flag == "tiny":
                    cell.setBackground(TINY_BG)
                    cell.setToolTip(
                        f"Suspiciously small file ({human_size(item.size)}) - "
                        "possibly corrupted or an interrupted recording.")
                elif flag == "huge":
                    cell.setBackground(HUGE_BG)
                    cell.setToolTip(
                        f"Very large video ({human_size(item.size)}).")
                self.table.setItem(row, col, cell)
            total_size += item.size

        self.lbl_summary.setText(f"{len(self.items)} items, {human_size(total_size)} total")
        self._filling_table = False
        self.apply_column_visibility()

    def apply_column_visibility(self):
        """Hide/show columns per the Settings checkboxes."""
        for col, (_, _w, key) in enumerate(self.COLUMNS):
            if not key:
                continue
            visible = self.settings.value(f"columns/{key}", "true") in (True, "true")
            self.table.setColumnHidden(col, not visible)

    def _table_item_changed(self, titem: QTableWidgetItem):
        if self._filling_table:
            return
        if titem.column() != 0 or not (0 <= titem.row() < len(self.items)):
            return
        new_state = titem.checkState() == Qt.Checked
        self.items[titem.row()].selected = new_state
        # Ctrl/Shift multi-selection: apply the toggle to every selected row.
        apply_check_to_selection(self.table, self.items, titem.row(), new_state,
                                 guard=self)

    def _set_all_selected(self, value: bool):
        for item in self.items:
            item.selected = value
        self._fill_table()

    def _lrf_toggled(self, checked: bool):
        self.chk_lrf_mp4.setEnabled(checked)
        if not checked:
            self.chk_lrf_mp4.setChecked(False)

    def _skip_red_toggled(self, checked: bool):
        self.settings.setValue("skip_red", checked)
        changed = 0
        for item in self.items:
            if size_flag(item) == "tiny":
                new_state = (not checked) and not item.in_library
                if item.selected != new_state:
                    item.selected = new_state
                    changed += 1
        if changed:
            self._fill_table()

    def _apply_skip_red(self):
        if self.chk_skip_red.isChecked():
            for item in self.items:
                if size_flag(item) == "tiny":
                    item.selected = False

    # ------------------------------------------------------------- import
    def pick_target(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose target folder",
                                                  self.edit_target.text().strip())
        if folder:
            self.edit_target.setText(folder)
            self.settings.setValue("last_target", folder)
            self._recheck_library()

    def start_import(self):
        target = self.edit_target.text().strip()
        if not target:
            QMessageBox.information(self, "No target", "Choose a target folder first.")
            return
        os.makedirs(target, exist_ok=True)

        selected = [i for i in self.items if i.selected]
        if not selected:
            QMessageBox.information(self, "Nothing selected", "Tick at least one item to import.")
            return

        # Warn before re-importing files the library already has.
        dup_selected = [i for i in selected if i.in_library]
        if dup_selected:
            answer = QMessageBox.question(
                self, "Already in library",
                f"{len(dup_selected)} of the selected items appear to already "
                "exist in the target library (matched by their original DJI "
                "name, ignoring rename tags).\n\nImport them anyway?")
            if answer != QMessageBox.Yes:
                return

        self.settings.setValue("last_target", target)
        options = ImportOptions(
            target=target,
            split_orientation=self.chk_split_orient.isChecked(),
            on_conflict="skip" if self.combo_conflict.currentIndex() == 0 else "rename",
            rename_lrf_to_mp4=self.chk_lrf_mp4.isChecked(),
        )
        self.btn_import.setEnabled(False)
        self.btn_scan.setEnabled(False)
        self.btn_cancel_import.setEnabled(True)
        self.progress.setVisible(True)
        self.progress.setValue(0)

        self.import_worker = ImportWorker(self.items, options)
        self.import_worker.progress.connect(self._import_progress)
        self.import_worker.finished_ok.connect(self._import_finished)
        self.import_worker.start()

    def _import_progress(self, done: int, total: int, name: str):
        self.progress.setMaximum(total)
        self.progress.setValue(done)
        self.status.setText(f"Copying {done}/{total}: {name}")

    def _cancel_import(self):
        if self.import_worker:
            self.import_worker.cancel()
            self.btn_cancel_import.setEnabled(False)
            self.status.setText("Cancelling import after the current file...")

    def _import_finished(self, copied: int, skipped: int, errors: list):
        self.progress.setVisible(False)
        self.btn_import.setEnabled(True)
        self.btn_scan.setEnabled(True)
        self.btn_cancel_import.setEnabled(False)
        for err in errors:
            self.log.appendPlainText("IMPORT ERROR: " + err)
        msg = f"Import finished: {copied} files copied, {skipped} skipped."
        if errors:
            msg += f" {len(errors)} errors (see log)."
        self.status.setText(msg)
        QMessageBox.information(self, "Import finished", msg)

    # -------------------------------------------------------------- misc
    def _check_ffprobe(self):
        if not find_ffprobe():
            self.log.appendPlainText(
                "WARNING: ffprobe (FFmpeg) was not found. Video metadata "
                "(fps, gamma, slow-motion) will be unavailable.\n"
                "Install FFmpeg and make sure ffprobe is in PATH, or place "
                "ffprobe.exe in a 'bin' folder next to the app.")
