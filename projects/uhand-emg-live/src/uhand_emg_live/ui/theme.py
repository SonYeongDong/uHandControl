"""The look: uHandControl's Light Studio, shared with uHandMotionCreator and uHandVirtualServer.
A pale blue-grey window, white cards with round corners, one blue accent. Colour is used only
where it carries meaning (status, the leading gesture, the live path)."""
from __future__ import annotations

import os

os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")

import pyqtgraph as pg  # noqa: E402
from PySide6.QtGui import QColor, QFont, QPalette  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

LOGO_COLOR = "#12936b"    # this program's mark (the editor is blue, the virtual server red)

BG = "#f3f6fc"            # window; also the well behind gauges and vote rows
PANEL = "#ffffff"         # cards, plots
TEXT = "#182a45"
TITLE = "#122644"
MUTED = "#687992"
GRID = "#dce4f1"          # card borders and hairlines
TRACK = "#dde5f3"         # the empty part of a bar
ACCENT = "#245df5"        # selection, bars, the signal trace
ACCENT_TEXT = "#2459d3"   # accent as text on white or on the badge tint
TINT = "#edf3ff"          # badge background
INK = "#ffffff"           # text on an accent or coloured field
IDLE = "#b7c4d9"          # a bar or a branch that is not the leading one
DANGER = "#cc3344"        # the robot stop button

FAMILIES = ["Segoe UI", "Malgun Gothic", "Apple SD Gothic Neo"]

FINGER_COLORS = [ACCENT] * 5                                        # thumb .. little
CH_COLORS = [ACCENT] * 8

STYLE = f"""
QMainWindow, QWidget#root {{ background: {BG}; color: {TEXT}; }}
QWidget {{ font-family: 'Segoe UI', 'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif; font-size: 13px; color: {TEXT}; }}
QToolTip {{ color: {TEXT}; background: {PANEL}; border: 1px solid {GRID}; padding: 4px; }}
QFrame#card {{ background: white; border: 1px solid {GRID}; border-radius: 12px; }}
QFrame#cardFocus {{ background: white; border: 2px solid {ACCENT}; border-radius: 12px; }}
QFrame#rule {{ background: {GRID}; border: none; }}
QLabel {{ background: transparent; border: none; }}
QLabel#title {{ font-size: 23px; font-weight: 700; color: {TITLE}; }}
QLabel#section {{ font-size: 15px; font-weight: 650; }}
QLabel#muted {{ color: {MUTED}; font-size: 12px; }}
QLabel#badge {{ color: {ACCENT_TEXT}; background: {TINT}; border-radius: 7px; padding: 6px 10px; font-weight: 600; }}
QPushButton, QToolButton {{ background: #fff; border: 1px solid #d7e1ef; border-radius: 7px; padding: 4px 10px; }}
QToolButton {{ padding: 5px 7px; }}
QPushButton:hover:enabled, QToolButton:hover:enabled {{ background: #eaf1ff; border-color: #98b5ed; }}
QPushButton:checked:enabled {{ background: #d5e5ff; border-color: #2d62ee; color: #154ccc; font-weight: 600; }}
QPushButton:pressed:enabled, QToolButton:pressed:enabled {{ background: #3867bd; border-color: #254c92; color: white; }}
QPushButton:disabled {{ background: #f3f5f9; color: #a2aec1; border-color: #e5eaf1; }}
QPushButton#primary {{ background: {ACCENT}; color: white; border-color: {ACCENT}; font-weight: 600; }}
QPushButton#primary:hover:enabled {{ background: #194dd9; border-color: #194dd9; }}
QPushButton#primary:pressed:enabled {{ background: #10318f; border-color: #0d2876; color: white; }}
QPushButton#segL, QPushButton#segM, QPushButton#segR {{ border-radius: 0; padding: 4px 4px; }}
QPushButton#segL {{ border-top-left-radius: 7px; border-bottom-left-radius: 7px; }}
QPushButton#segR {{ border-top-right-radius: 7px; border-bottom-right-radius: 7px; }}
QPushButton#stop {{ background: {DANGER}; color: white; border: 2px solid {DANGER}; font-weight: 700; padding: 6px 16px; }}
QPushButton#stop:hover:enabled {{ background: #b02a3a; border-color: #b02a3a; }}
QPushButton#stop:checked:enabled {{ background: white; color: {DANGER}; border-color: {DANGER}; }}
QComboBox {{ background: #f8faff; border: 1px solid #d7e1ef; border-radius: 5px; padding: 2px 8px; }}
QComboBox:hover, QComboBox:on {{ border-color: #2962ef; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox::down-arrow {{ image: none; width: 0; height: 0; border-left: 4px solid #f8faff;
                        border-right: 4px solid #f8faff; border-top: 6px solid {MUTED}; }}
QComboBox QAbstractItemView {{ background: white; color: {TEXT}; border: 1px solid #d7e1ef; outline: 0;
                              selection-background-color: #eaf1ff; selection-color: #16419f; }}
QProgressBar {{ background: {TRACK}; border: none; border-radius: 3px; }}
QProgressBar::chunk {{ background: #2f63f5; border-radius: 3px; }}
QSlider::groove:horizontal {{ height: 5px; background: {TRACK}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: #2f63f5; border-radius: 2px; }}
QSlider::handle:horizontal {{ width: 14px; margin: -5px 0; background: white; border: 2px solid #366bf6; border-radius: 8px; }}
QMenuBar {{ background: {BG}; }} QMenu {{ background: white; border: 1px solid #d7e1ef; }}
QMenu::item:selected, QMenuBar::item:selected {{ background: #eaf1ff; }}
QScrollBar:vertical {{ background: #f6f8fc; width: 8px; }}
QScrollBar::handle:vertical {{ background: #cbd6e7; border-radius: 4px; min-height: 22px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
"""


def font(point_size: int = 10, bold: bool = False) -> QFont:
    f = QFont()
    f.setFamilies(FAMILIES)
    f.setPointSize(point_size)
    f.setStyleHint(QFont.SansSerif)
    f.setBold(bold)
    return f


def ink(colour: str) -> QColor:
    """A gesture colour deepened so it reads on a white card."""
    return QColor(colour).darker(125)


def apply(app: QApplication) -> None:
    app.setStyle("Fusion")
    p = QPalette()
    for role, c in [
        (QPalette.Window, BG), (QPalette.WindowText, TEXT), (QPalette.Base, PANEL),
        (QPalette.AlternateBase, BG), (QPalette.Text, TEXT), (QPalette.Button, PANEL),
        (QPalette.ButtonText, TEXT), (QPalette.ToolTipBase, PANEL), (QPalette.ToolTipText, TEXT),
        (QPalette.Highlight, ACCENT), (QPalette.HighlightedText, INK),
        (QPalette.PlaceholderText, MUTED),
    ]:
        p.setColor(role, QColor(c))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor(IDLE))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(IDLE))
    app.setPalette(p)
    app.setFont(font(10))
    app.setStyleSheet(STYLE)
    pg.setConfigOptions(background=PANEL, foreground=MUTED, antialias=False)
