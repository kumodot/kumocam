"""Convert tab (V2): FFmpeg queue with downscale and D-Log LUT application.

Works on any folder - typically the already-imported library. Each video is
probed individually; the LUT checkbox only affects clips detected as D-Log.
"""

from __future__ import annotations

import os
from typing import List, Optional

from PySide6.QtCore import Qt, QSettings, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QGridLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
    QProgressBar, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from ..core.converter import (ConvertJob, ConvertOptions, ConvertWorker,
                              extract_thumbnail_png, find_ffmpeg)
from ..core.probe import probe_video
from ..core.scanner import VIDEO_EXTS

THUMB_HEIGHT = 54

RESOLUTION_CHOICES = [
    ("Keep original", 0),
    ("1080p (long edge 1920)", 1920),
    ("720p (long edge 1280)", 1280),
    ("4K (long edge 3840)", 3840),
]
CODEC_CHOICES = [("H.264 (compatible)", "libx264"), ("H.265 (smaller)", "libx265")]
QUALITY_CHOICES = [("High (CRF 17)", 17), ("Medium (CRF 20)", 20), ("Small (CRF 24)", 24)]


class ProbeWorker(QThread):
    progress = Signal(str)
    done = Signal(list)

    def __init__(self, paths: List[str], parent=None):
        super().__init__(parent)
        self.paths = paths

    def run(self):
        jobs = []
        for p in self.paths:
            self.progress.emit(f"Reading metadata: {os.path.basename(p)}")
            meta = probe_video(p)
            job = ConvertJob(src_path=p, meta=meta,
                             apply_lut=meta.gamma_label.startswith("DLOG"))
            job.thumb_png = extract_thumbnail_png(p, THUMB_HEIGHT)
            jobs.append(job)
        self.done.emit(jobs)


class ConvertTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.jobs: List[ConvertJob] = []
        self.worker: Optional[ConvertWorker] = None
        self.probe_worker: Optional[ProbeWorker] = None
        self.settings = QSettings("OsmoCompanion", "OsmoCompanion")
        self._build_ui()
        self._check_ffmpeg()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        # --- Source pickers ------------------------------------------------
        src_row = QHBoxLayout()
        btn_add_files = QPushButton("Add videos...")
        btn_add_files.clicked.connect(self.add_files)
        btn_add_folder = QPushButton("Add folder...")
        btn_add_folder.clicked.connect(self.add_folder)
        btn_clear = QPushButton("Clear list")
        btn_clear.clicked.connect(self.clear_list)
        btn_merge = QPushButton("Merge selected")
        btn_merge.setToolTip(
            "Group the highlighted rows: they will be converted into ONE "
            "concatenated video, in list order. Works best with clips of "
            "the same resolution and framerate.")
        btn_merge.clicked.connect(self.merge_selected)
        btn_unmerge = QPushButton("Unmerge")
        btn_unmerge.clicked.connect(self.unmerge_selected)
        btn_mute = QPushButton("Mute selected")
        btn_mute.setToolTip("Strip the audio track from the highlighted rows.")
        btn_mute.clicked.connect(lambda: self._set_audio_selected(False))
        btn_unmute = QPushButton("Unmute selected")
        btn_unmute.clicked.connect(lambda: self._set_audio_selected(True))
        for b in (btn_add_files, btn_add_folder, btn_clear, btn_merge,
                  btn_unmerge, btn_mute, btn_unmute):
            src_row.addWidget(b)
        src_row.addStretch(1)
        layout.addLayout(src_row)

        # --- Options -------------------------------------------------------
        opts_group = QGroupBox("Conversion options")
        og = QGridLayout(opts_group)

        og.addWidget(QLabel("Resolution:"), 0, 0)
        self.combo_res = QComboBox()
        for label, _ in RESOLUTION_CHOICES:
            self.combo_res.addItem(label)
        self.combo_res.setCurrentIndex(1)  # 1080p default
        og.addWidget(self.combo_res, 0, 1)

        og.addWidget(QLabel("Codec:"), 1, 0)
        self.combo_codec = QComboBox()
        for label, _ in CODEC_CHOICES:
            self.combo_codec.addItem(label)
        og.addWidget(self.combo_codec, 1, 1)

        og.addWidget(QLabel("Quality:"), 0, 2)
        self.combo_quality = QComboBox()
        for label, _ in QUALITY_CHOICES:
            self.combo_quality.addItem(label)
        self.combo_quality.setCurrentIndex(1)
        og.addWidget(self.combo_quality, 0, 3)

        self.chk_lut = QCheckBox("Apply LUT to D-Log clips")
        self.chk_lut.setChecked(True)
        og.addWidget(self.chk_lut, 1, 2)

        self.edit_lut = QLineEdit()
        self.edit_lut.setPlaceholderText("Pick the D-Log to Rec.709 .cube file...")
        self.edit_lut.setText(self.settings.value("lut_path", ""))
        btn_lut = QPushButton("LUT file...")
        btn_lut.clicked.connect(self.pick_lut)
        btn_get_luts = QPushButton("Get official LUTs")
        btn_get_luts.setFlat(True)
        btn_get_luts.setToolTip("Opens dji.com/lut - official LUTs must be "
                                "downloaded from the camera maker's site.")
        btn_get_luts.clicked.connect(self._open_lut_site)
        og.addWidget(self.edit_lut, 2, 0, 1, 2)
        og.addWidget(btn_lut, 2, 2)
        og.addWidget(btn_get_luts, 2, 3)
        layout.addWidget(opts_group)

        # If no LUT chosen yet, look in the default LUT folder (Settings).
        if not self.edit_lut.text().strip():
            self._autofill_lut_from_default_folder()

        # --- Job table -----------------------------------------------------
        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels(
            ["", "Thumb", "File", "Resolution", "FPS", "Gamma", "LUT",
             "Audio", "Group", "Status"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        for col, width in enumerate([36, 104, 330, 100, 65, 85, 55, 70, 65, 110]):
            self.table.setColumnWidth(col, width)
        self.table.verticalHeader().setDefaultSectionSize(THUMB_HEIGHT + 6)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self._filling = False
        self.table.itemChanged.connect(self._item_changed)
        layout.addWidget(self.table, stretch=1)

        # --- Output + run --------------------------------------------------
        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("Output folder:"))
        self.edit_out = QLineEdit()
        self.edit_out.setPlaceholderText("Empty = 'CONVERTED' subfolder beside each source file")
        btn_out = QPushButton("Browse...")
        btn_out.clicked.connect(self.pick_out)
        self.btn_convert = QPushButton("Convert")
        self.btn_convert.setProperty("accent", True)
        self.btn_convert.setEnabled(False)
        self.btn_convert.clicked.connect(self.start_convert)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.cancel_convert)
        out_row.addWidget(self.edit_out, stretch=1)
        out_row.addWidget(btn_out)
        out_row.addWidget(self.btn_convert)
        out_row.addWidget(self.btn_cancel)
        layout.addLayout(out_row)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.status = QLabel("Add videos or a folder to start.")
        layout.addWidget(self.status)

    # ---------------------------------------------------------- source ops
    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "Add videos", "", "Videos (*.mp4 *.mov *.MP4 *.MOV)")
        if files:
            self._probe([f for f in files if self._is_new(f)])

    def add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Add folder with videos")
        if not folder:
            return
        found = []
        for dirpath, dirnames, filenames in os.walk(folder):
            # Do not re-convert previous outputs.
            dirnames[:] = [d for d in dirnames if d.upper() != "CONVERTED"]
            for f in sorted(filenames):
                if os.path.splitext(f)[1].lower() in VIDEO_EXTS:
                    p = os.path.join(dirpath, f)
                    if self._is_new(p):
                        found.append(p)
        if found:
            self._probe(found)
        else:
            self.status.setText("No new videos found in that folder.")

    def _is_new(self, path: str) -> bool:
        return all(os.path.normpath(j.src_path) != os.path.normpath(path) for j in self.jobs)

    def _probe(self, paths: List[str]):
        if not paths:
            return
        self.status.setText("Reading metadata...")
        self.probe_worker = ProbeWorker(paths)
        self.probe_worker.progress.connect(self.status.setText)
        self.probe_worker.done.connect(self._probe_done)
        self.probe_worker.start()

    def _probe_done(self, jobs: List[ConvertJob]):
        self.jobs.extend(jobs)
        self._fill_table()
        self.btn_convert.setEnabled(bool(self.jobs))
        self.status.setText(f"{len(self.jobs)} videos queued.")

    def clear_list(self):
        self.jobs.clear()
        self._fill_table()
        self.btn_convert.setEnabled(False)
        self.status.setText("List cleared.")

    # ---------------------------------------------------------------- table
    def _fill_table(self):
        from PySide6.QtGui import QPixmap
        self._filling = True
        self.table.setRowCount(0)
        for job in self.jobs:
            row = self.table.rowCount()
            self.table.insertRow(row)
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            chk.setCheckState(Qt.Checked if job.selected else Qt.Unchecked)
            self.table.setItem(row, 0, chk)

            thumb = QTableWidgetItem()
            if job.thumb_png:
                pix = QPixmap()
                if pix.loadFromData(job.thumb_png):
                    thumb.setData(Qt.DecorationRole, pix)
            self.table.setItem(row, 1, thumb)

            m = job.meta
            self.table.setItem(row, 2, QTableWidgetItem(os.path.basename(job.src_path)))
            self.table.setItem(row, 3, QTableWidgetItem(f"{m.width}x{m.height}" if m.width else "?"))
            self.table.setItem(row, 4, QTableWidgetItem(m.fps_label))
            self.table.setItem(row, 5, QTableWidgetItem(m.gamma_label))
            self.table.setItem(row, 6, QTableWidgetItem("yes" if job.apply_lut else ""))

            audio = QTableWidgetItem()
            audio.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            if m.has_audio:
                audio.setCheckState(Qt.Checked if job.keep_audio else Qt.Unchecked)
                audio.setToolTip("Checked = keep audio. Uncheck to strip the audio track.")
            else:
                audio.setCheckState(Qt.Unchecked)
                audio.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                audio.setText("none")
                audio.setToolTip("This clip has no audio stream (slow motion).")
            self.table.setItem(row, 7, audio)

            self.table.setItem(row, 8, QTableWidgetItem(job.group))
            self.table.setItem(row, 9, QTableWidgetItem(job.status))
        self._filling = False

    def _item_changed(self, titem: QTableWidgetItem):
        if self._filling:
            return
        row = titem.row()
        if not (0 <= row < len(self.jobs)):
            return
        if titem.column() == 0:
            new_state = titem.checkState() == Qt.Checked
            self.jobs[row].selected = new_state
            from .table_utils import apply_check_to_selection
            apply_check_to_selection(self.table, self.jobs, row, new_state)
        elif titem.column() == 7 and self.jobs[row].meta.has_audio:
            self.jobs[row].keep_audio = titem.checkState() == Qt.Checked

    # ------------------------------------------------------ merge / audio
    def _selected_rows(self):
        sel = self.table.selectionModel()
        return sorted({i.row() for i in sel.selectedRows()}) if sel else []

    def merge_selected(self):
        rows = self._selected_rows()
        if len(rows) < 2:
            QMessageBox.information(self, "Merge", "Highlight two or more rows "
                                    "(Ctrl/Shift click) to merge them.")
            return
        self._group_counter = getattr(self, "_group_counter", 0) + 1
        group = f"M{self._group_counter}"
        for r in rows:
            self.jobs[r].group = group
        self._fill_table()
        self.status.setText(f"Group {group}: {len(rows)} clips will be merged "
                            "into one video (in list order).")

    def unmerge_selected(self):
        rows = self._selected_rows() or range(len(self.jobs))
        for r in rows:
            self.jobs[r].group = ""
        self._fill_table()
        self.status.setText("Merge group(s) removed.")

    def _set_audio_selected(self, keep: bool):
        rows = self._selected_rows()
        if not rows:
            QMessageBox.information(self, "Audio", "Highlight rows first (Ctrl/Shift click).")
            return
        for r in rows:
            if self.jobs[r].meta.has_audio:
                self.jobs[r].keep_audio = keep
        self._fill_table()

    def _set_status_cell(self, row: int, text: str):
        item = self.table.item(row, 9)
        if item:
            item.setText(text)

    # -------------------------------------------------------------- convert
    def _default_lut_folder(self) -> str:
        from .settings_tab import get_str_setting
        return get_str_setting("default_lut_folder")

    def _autofill_lut_from_default_folder(self):
        folder = self._default_lut_folder()
        if folder and os.path.isdir(folder):
            cubes = sorted(f for f in os.listdir(folder)
                           if f.lower().endswith(".cube"))
            if cubes:
                path = os.path.join(folder, cubes[0])
                self.edit_lut.setText(path)
                self.settings.setValue("lut_path", path)

    def _open_lut_site(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl("https://www.dji.com/lut"))

    def pick_lut(self):
        start_dir = os.path.dirname(self.edit_lut.text().strip()) or self._default_lut_folder()
        path, _ = QFileDialog.getOpenFileName(self, "Choose LUT", start_dir,
                                              "LUT files (*.cube)")
        if path:
            self.edit_lut.setText(path)
            self.settings.setValue("lut_path", path)

    def pick_out(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose output folder")
        if folder:
            self.edit_out.setText(folder)

    def start_convert(self):
        selected = [j for j in self.jobs if j.selected]
        if not selected:
            QMessageBox.information(self, "Nothing selected", "Tick at least one video.")
            return

        lut_wanted = self.chk_lut.isChecked()
        lut_path = self.edit_lut.text().strip()
        if lut_wanted and any(j.apply_lut for j in selected) and not os.path.exists(lut_path):
            QMessageBox.information(
                self, "LUT file missing",
                "There are D-Log clips in the queue but no valid .cube file "
                "is set. Pick the DJI D-Log to Rec.709 LUT, or untick "
                "'Apply LUT to D-Log clips'.")
            return
        if not lut_wanted:
            for j in self.jobs:
                j.apply_lut = False

        res_edge = RESOLUTION_CHOICES[self.combo_res.currentIndex()][1]
        codec = CODEC_CHOICES[self.combo_codec.currentIndex()][1]
        crf = QUALITY_CHOICES[self.combo_quality.currentIndex()][1]
        suffix_parts = []
        if res_edge:
            suffix_parts.append({1920: "_1080p", 1280: "_720p", 3840: "_4K"}.get(res_edge, ""))
        if lut_wanted:
            suffix_parts.append("_REC709")
        options = ConvertOptions(
            target_long_edge=res_edge,
            codec=codec,
            crf=crf,
            lut_path=lut_path if lut_wanted else "",
            output_folder=self.edit_out.text().strip(),
            suffix="".join(suffix_parts) or "_converted",
        )

        self.btn_convert.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.progress.setVisible(True)
        self.progress.setMaximum(100)
        self.progress.setValue(0)

        self.worker = ConvertWorker(self.jobs, options)
        self.worker.file_started.connect(self._file_started)
        self.worker.file_progress.connect(self._file_progress)
        self.worker.file_done.connect(self._file_done)
        self.worker.all_done.connect(self._all_done)
        self.worker.start()

    def cancel_convert(self):
        if self.worker:
            self.worker.cancel()
            self.status.setText("Cancelling...")

    def _file_started(self, idx: int, name: str):
        done = sum(1 for j in self.jobs if j.status in ("done", "failed", "skipped"))
        self.status.setText(f"Converting ({done + 1}/{len(self.jobs)}): {name}")
        self._set_status_cell(idx, "running")

    def _file_progress(self, idx: int, fraction: float):
        self.progress.setValue(int(fraction * 100))

    def _file_done(self, idx: int, status: str):
        self._set_status_cell(idx, status)
        self.progress.setValue(0)

    def _all_done(self, converted: int, failed: int, errors: list):
        self.progress.setVisible(False)
        self.btn_convert.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        msg = f"Conversion finished: {converted} done, {failed} failed."
        self.status.setText(msg)
        if errors:
            QMessageBox.warning(self, "Conversion finished with errors",
                                msg + "\n\n" + "\n".join(errors[:10]))
        else:
            QMessageBox.information(self, "Conversion finished", msg)

    # ------------------------------------------------------------------ misc
    def _check_ffmpeg(self):
        if not find_ffmpeg():
            self.status.setText(
                "WARNING: ffmpeg not found - install FFmpeg or place it in "
                "the app's bin folder. Conversion will not work without it.")
