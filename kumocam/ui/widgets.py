"""Small custom widgets."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget


class ToggleSwitch(QWidget):
    """Two-position rocker switch (left/right). `checked` False = left,
    True = right. Emits toggled(bool)."""

    toggled = Signal(bool)

    TRACK_W, TRACK_H, KNOB = 44, 22, 16

    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self._checked = checked
        self.setFixedSize(self.TRACK_W, self.TRACK_H)
        self.setCursor(Qt.PointingHandCursor)

    @property
    def checked(self) -> bool:
        return self._checked

    def setChecked(self, value: bool):
        value = bool(value)
        if value != self._checked:
            self._checked = value
            self.update()
            self.toggled.emit(value)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.setChecked(not self._checked)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        # Track: neutral (both positions are valid states, not on/off).
        track = QColor(127, 132, 145, 90)
        painter.setPen(Qt.NoPen)
        painter.setBrush(track)
        painter.drawRoundedRect(0, 0, self.TRACK_W, self.TRACK_H,
                                self.TRACK_H / 2, self.TRACK_H / 2)
        # Knob: accent teal.
        knob = QColor("#2dd4bf")
        margin = (self.TRACK_H - self.KNOB) / 2
        x = self.TRACK_W - self.KNOB - margin if self._checked else margin
        painter.setBrush(knob)
        painter.drawEllipse(int(x), int(margin), self.KNOB, self.KNOB)
        painter.end()


class LabeledToggle(QWidget):
    """'<left label>  [switch]  <right label>' - the active side is
    highlighted, and clicking a label selects that side.
    `checked` False = left, True = right."""

    toggled = Signal(bool)

    def __init__(self, left_text: str, right_text: str,
                 checked: bool = False, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.lbl_left = QLabel(left_text)
        self.lbl_right = QLabel(right_text)
        for lbl in (self.lbl_left, self.lbl_right):
            lbl.setCursor(Qt.PointingHandCursor)
        self.switch = ToggleSwitch(checked)
        self.switch.toggled.connect(self._on_toggle)
        layout.addWidget(self.lbl_left)
        layout.addWidget(self.switch)
        layout.addWidget(self.lbl_right)
        self.lbl_left.mouseReleaseEvent = lambda e: self.switch.setChecked(False)
        self.lbl_right.mouseReleaseEvent = lambda e: self.switch.setChecked(True)
        self._style()

    @property
    def checked(self) -> bool:
        return self.switch.checked

    def setChecked(self, value: bool):
        self.switch.setChecked(value)
        self._style()

    def _on_toggle(self, value: bool):
        self._style()
        self.toggled.emit(value)

    def _style(self):
        active = "background: transparent; color: #2dd4bf; font-weight: 700;"
        idle = "background: transparent; font-weight: 400;"
        self.lbl_left.setStyleSheet(idle if self.switch.checked else active)
        self.lbl_right.setStyleSheet(active if self.switch.checked else idle)


def dashed_vline() -> QFrame:
    """A subtle vertical dashed separator."""
    line = QFrame()
    line.setFixedWidth(1)
    line.setStyleSheet("border: none; border-left: 1px dashed rgba(127,132,145,0.55);")
    return line
