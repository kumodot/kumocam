"""Kumodot theme for KumoCam: custom dark/light QSS with a
teal accent. Applied app-wide; the variant is chosen in the Settings tab."""

from __future__ import annotations

import os

_ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "assets").replace("\\", "/")

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------

ACCENT = "#2dd4bf"          # Kumodot teal
ACCENT_HOVER = "#5eead4"
ACCENT_PRESSED = "#14b8a6"
ACCENT_TEXT_ON = "#06322c"  # dark text over the teal accent

DARK = {
    "bg":          "#17181c",   # window background
    "surface":     "#1f2127",   # cards / group boxes
    "surface2":    "#262932",   # inputs, headers
    "border":      "#32363f",
    "text":        "#e6e8ee",
    "text_dim":    "#9aa0ad",
    "row_alt":     "#22242b",
    "selection":   "#134e48",
    "accent":      ACCENT,
    "accent_hover": ACCENT_HOVER,
    "accent_pressed": ACCENT_PRESSED,
    "accent_text": ACCENT_TEXT_ON,
    "check_svg":   f"{_ASSETS}/check_dark.svg",
}

LIGHT = {
    "bg":          "#f4f5f7",
    "surface":     "#ffffff",
    "surface2":    "#eceef2",
    "border":      "#d5d9e0",
    "text":        "#1c1e24",
    "text_dim":    "#6b7280",
    "row_alt":     "#f7f8fa",
    "selection":   "#b5ece4",
    "accent":      "#0d9488",   # deeper teal for contrast on light
    "accent_hover": "#14b8a6",
    "accent_pressed": "#0f766e",
    "accent_text": "#ffffff",
    "check_svg":   f"{_ASSETS}/check_light.svg",
}


def build_qss(palette: dict) -> str:
    p = palette
    return f"""
* {{
    outline: none;
}}
QWidget {{
    background: {p['bg']};
    color: {p['text']};
    font-size: 13px;
}}
QMainWindow, QDialog {{
    background: {p['bg']};
}}

/* ---------- Tabs ---------- */
QTabWidget::pane {{
    border: none;
    background: {p['bg']};
    top: -1px;
}}
QTabBar {{
    background: transparent;
}}
QTabBar::tab {{
    background: transparent;
    color: {p['text_dim']};
    padding: 9px 22px;
    margin-right: 2px;
    border: none;
    border-bottom: 2px solid transparent;
    font-weight: 600;
}}
QTabBar::tab:hover {{
    color: {p['text']};
}}
QTabBar::tab:selected {{
    color: {p['accent']};
    border-bottom: 2px solid {p['accent']};
}}

/* ---------- Group boxes as cards ---------- */
QGroupBox {{
    background: {p['surface']};
    border: 1px solid {p['border']};
    border-radius: 8px;
    margin-top: 22px;   /* room for the title fully ABOVE the border */
    padding: 10px 8px 8px 8px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 2px;
    top: 1px;
    padding: 0 2px;
    color: {p['text_dim']};
    background: transparent;
    font-size: 12px;
    letter-spacing: 0.5px;
}}

/* ---------- Buttons ---------- */
QPushButton {{
    background: {p['surface2']};
    color: {p['text']};
    border: 1px solid {p['border']};
    border-radius: 6px;
    padding: 7px 16px;
}}
QPushButton:hover {{
    border-color: {p['accent']};
    color: {p['accent']};
}}
QPushButton:pressed {{
    background: {p['border']};
}}
QPushButton:disabled {{
    color: {p['text_dim']};
    border-color: {p['border']};
    background: transparent;
}}
QPushButton[accent="true"] {{
    background: {p['accent']};
    color: {p['accent_text']};
    border: none;
    font-weight: 700;
    padding: 8px 26px;
}}
QPushButton[accent="true"]:hover {{
    background: {p['accent_hover']};
    color: {p['accent_text']};
}}
QPushButton[accent="true"]:pressed {{
    background: {p['accent_pressed']};
}}
QPushButton[accent="true"]:disabled {{
    background: {p['surface2']};
    color: {p['text_dim']};
}}
QPushButton:flat {{
    background: transparent;
    border: none;
    color: {p['text_dim']};
}}
QPushButton:flat:hover {{
    color: {p['accent']};
}}

/* ---------- Inputs ---------- */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: {p['surface2']};
    border: 1px solid {p['border']};
    border-radius: 6px;
    padding: 6px 10px;
    selection-background-color: {p['selection']};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {p['accent']};
}}
QComboBox::drop-down {{
    border: none;
    width: 24px;
}}
QComboBox QAbstractItemView {{
    background: {p['surface']};
    border: 1px solid {p['border']};
    selection-background-color: {p['selection']};
    selection-color: {p['text']};
}}

/* ---------- Labels ---------- */
QLabel {{
    background: transparent;
}}

/* ---------- Checkboxes / radios ---------- */
QCheckBox, QRadioButton {{
    spacing: 7px;
    background: transparent;
}}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border: 1.5px solid {p['border']};
    background: {p['surface2']};
}}
QCheckBox::indicator {{
    border-radius: 4px;
}}
QRadioButton::indicator {{
    border-radius: 9px;
}}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
    border-color: {p['accent']};
}}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background: {p['accent']};
    border-color: {p['accent']};
}}
QCheckBox::indicator:checked {{
    image: url("{p['check_svg']}");
}}

/* ---------- Tables ---------- */
QTableWidget {{
    background: {p['surface']};
    alternate-background-color: {p['row_alt']};
    border: 1px solid {p['border']};
    border-radius: 8px;
    gridline-color: transparent;
    selection-background-color: {p['selection']};
    selection-color: {p['text']};
}}
QTableWidget::item {{
    padding: 4px 6px;
    border: none;
}}
QHeaderView::section {{
    background: {p['surface2']};
    color: {p['text_dim']};
    border: none;
    border-bottom: 1px solid {p['border']};
    border-right: 1px solid {p['border']};
    padding: 7px 8px;
    font-weight: 600;
    font-size: 12px;
}}
QTableCornerButton::section {{
    background: {p['surface2']};
    border: none;
}}

/* ---------- Lists / logs ---------- */
QListWidget, QPlainTextEdit {{
    background: {p['surface']};
    border: 1px solid {p['border']};
    border-radius: 8px;
    padding: 4px;
}}

/* ---------- Progress bar ---------- */
QProgressBar {{
    background: {p['surface2']};
    border: none;
    border-radius: 5px;
    height: 10px;
    text-align: center;
    color: {p['text_dim']};
    font-size: 10px;
}}
QProgressBar::chunk {{
    background: {p['accent']};
    border-radius: 5px;
}}

/* ---------- Scrollbars ---------- */
QScrollBar:vertical {{
    background: transparent;
    width: 12px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {p['border']};
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {p['accent']};
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 12px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {p['border']};
    border-radius: 4px;
    min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {p['accent']};
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    width: 0; height: 0;
}}

/* ---------- Splitter ---------- */
QSplitter::handle {{
    background: {p['border']};
    height: 2px;
}}

QToolTip {{
    background: {p['surface']};
    color: {p['text']};
    border: 1px solid {p['accent']};
    border-radius: 4px;
    padding: 5px 8px;
}}
"""


def get_qss(variant: str) -> str:
    """variant: 'dark' | 'light'."""
    return build_qss(DARK if variant == "dark" else LIGHT)
