"""Small shared widgets: a pipeline stage card (number, name and lamp in its heading), a status
lamp, a segmented choice, probability bars."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from .. import gestures
from .theme import ACCENT, IDLE, INK, MUTED, TEXT, TRACK, font

LEVEL_COLOR = {"ok": "#1a7f4b", "warn": "#b25e09", "error": "#b3323f", "off": "#b7c4d9", "busy": "#2459d3"}


class Lamp(QWidget):
    """A round status light."""

    def __init__(self, size: int = 12) -> None:
        super().__init__()
        self._level = "off"
        self.setFixedSize(QSize(size, size))

    def set(self, level: str) -> None:
        if level != self._level:
            self._level = level
            self.update()

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(LEVEL_COLOR.get(self._level, LEVEL_COLOR["off"])))
        p.drawEllipse(QRectF(self.rect()).adjusted(1, 1, -1, -1))
        p.end()


class Badge(QWidget):
    """The stage number in a cobalt disc."""

    def __init__(self, number: int, size: int = 24) -> None:
        super().__init__()
        self._text = str(number)
        self.setFixedSize(QSize(size, size))

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(ACCENT))
        p.drawEllipse(self.rect())
        f = QFont(self.font())
        f.setPixelSize(int(self.height() * 0.58))
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(INK))
        p.drawText(self.rect(), Qt.AlignCenter, self._text)
        p.end()


class FlowArrow(QWidget):
    """The arrow from one stage card to the next; it sits between two cards at heading height."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(QSize(16, 48))

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        y, x1 = 25.0, self.width() - 2
        p.setPen(QPen(QColor(ACCENT), 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawLine(QPointF(1, y), QPointF(x1, y))
        p.drawPolyline(QPolygonF([QPointF(x1 - 5, y - 5), QPointF(x1, y), QPointF(x1 - 5, y + 5)]))
        p.end()


class Panel(QFrame):
    """One stage of the pipeline: a card with its number, name and status lamp in the heading.
    `focus` gives the one card with an accent border (the recognised gesture)."""

    def __init__(self, number: int, title: str, focus: bool = False) -> None:
        super().__init__()
        self.setObjectName("cardFocus" if focus else "card")
        self.head = QLabel(title)
        self.head.setObjectName("section")
        self.lamp = Lamp(12)
        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(Badge(number, 22))
        top.addWidget(self.head)
        top.addStretch(1)
        top.addWidget(self.lamp)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(12, 9, 12, 9)
        self.body.setSpacing(5)
        self.body.addLayout(top)

    def set_title(self, title: str) -> None:
        self.head.setText(title)


class LedDot(QWidget):
    """The robot's RGB LED: its colour while lit, grey when off."""

    def __init__(self) -> None:
        super().__init__()
        self.rgb = (0, 0, 0)
        self.setFixedSize(QSize(14, 14))

    def set_rgb(self, rgb) -> None:
        rgb = tuple(int(v) for v in rgb)
        if rgb != self.rgb:
            self.rgb = rgb
            self.update()

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor("#dce4f1"), 1))
        p.setBrush(QColor(*self.rgb) if any(self.rgb) else QColor("#9caac0"))
        p.drawEllipse(QRectF(self.rect()).adjusted(1, 1, -1, -1))
        p.end()


def muted(text: str = "", wrap: bool = True) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("muted")
    lab.setWordWrap(wrap)
    return lab


def rule() -> QFrame:
    """A hairline between groups inside a card."""
    line = QFrame()
    line.setObjectName("rule")
    line.setFixedHeight(1)
    return line


class Segmented(QWidget):
    """A row of joined buttons, one of them chosen. The small part of QComboBox's interface the
    window uses: currentData, setCurrentIndex, findData, and a `changed` signal."""

    changed = Signal()

    def __init__(self, options: list[tuple[str, object]]) -> None:
        super().__init__()
        self._data = [d for _, d in options]
        self._index = 0
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        for i, (text, _) in enumerate(options):
            b = QPushButton(text)
            b.setObjectName("segL" if i == 0 else "segR" if i == len(options) - 1 else "segM")
            b.setCheckable(True)
            b.setFixedHeight(28)
            b.setChecked(i == 0)
            self.group.addButton(b, i)
            row.addWidget(b, 1)
        self.group.idClicked.connect(self.setCurrentIndex)

    def currentIndex(self) -> int:
        return self._index

    def currentData(self):
        return self._data[self._index]

    def findData(self, data) -> int:
        return self._data.index(data) if data in self._data else -1

    def setCurrentIndex(self, index: int) -> None:
        self.group.button(index).setChecked(True)
        if index != self._index:
            self._index = index
            self.changed.emit()

    def setToolTip(self, text: str) -> None:
        for b in self.group.buttons():
            b.setToolTip(text)


class ElideLabel(QWidget):
    """One line of text that is shortened with an ellipsis when it does not fit (full text in
    the tooltip)."""

    def __init__(self, text: str = "", align=Qt.AlignRight | Qt.AlignVCenter, mode=Qt.ElideMiddle) -> None:
        super().__init__()
        self._text, self._color, self._align, self._mode = text, TEXT, align, mode
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)

    def set(self, text: str, color: str | None = None) -> None:
        self._text, self._color = text, color or TEXT
        self.updateGeometry()
        self.update()

    def text(self) -> str:
        return self._text

    def sizeHint(self) -> QSize:
        fm = self.fontMetrics()
        return QSize(fm.horizontalAdvance(self._text) + 2, fm.height() + 2)

    def minimumSizeHint(self) -> QSize:
        return QSize(24, self.fontMetrics().height() + 2)

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        shown = self.fontMetrics().elidedText(self._text, self._mode, self.width())
        self.setToolTip(self._text if shown != self._text else "")
        p.setPen(QColor(self._color))
        p.drawText(self.rect(), self._align, shown)
        p.end()


class FitLabel(QWidget):
    """One line of large text; the font shrinks until the text fits the width."""

    def __init__(self, point_size: int = 22, bold: bool = True, align=Qt.AlignCenter, color: str = TEXT) -> None:
        super().__init__()
        self._text, self._color, self._pt, self._align, self._base = "–", color, point_size, align, color
        self._font = font(point_size, bold)
        self.setFixedHeight(QFontMetrics(self._font).height() + 4)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)

    def set(self, text: str, color: str | None = None) -> None:
        if (text, color or self._base) != (self._text, self._color):
            self._text, self._color = text, color or self._base
            self.update()

    def text(self) -> str:
        return self._text

    def fitted_size(self) -> float:
        """The point size at which the text fits the current width."""
        f = QFont(self._font)
        size = float(self._pt)
        while size > 8 and QFontMetrics(f).horizontalAdvance(self._text) > self.width() - 4:
            size -= 1
            f.setPointSizeF(size)
        return size

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        f = QFont(self._font)
        f.setPointSizeF(self.fitted_size())
        p.setFont(f)
        p.setPen(QColor(self._color))
        p.drawText(self.rect(), self._align, self._text)
        p.end()


class KeyValues(QWidget):
    """Rows of 'name   value'."""

    def __init__(self, names: list[str]) -> None:
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(3)
        self.values: dict[str, ElideLabel] = {}
        for n in names:
            row = QHBoxLayout()
            row.addWidget(muted(n, wrap=False))
            row.addSpacing(8)
            val = ElideLabel("–")
            row.addWidget(val, 1)
            self.values[n] = val
            v.addLayout(row)

    def set(self, name: str, text: str, color: str | None = None) -> None:
        self.values[name].set(text, color)


class ProbBars(QWidget):
    """One bar per gesture, the likeliest one highlighted."""

    ROW = 16

    def __init__(self) -> None:
        super().__init__()
        self.keys: list[str] = []
        self.p = np.zeros(0)
        self.setMinimumWidth(160)

    def set(self, keys: list[str], p: np.ndarray | None) -> None:
        self.keys, self.p = list(keys), (np.zeros(len(keys)) if p is None else p)
        self.setMinimumHeight(self.ROW * max(1, len(keys)) + 4)
        self.update()

    def paintEvent(self, ev) -> None:
        q = QPainter(self)
        q.setRenderHint(QPainter.Antialiasing)
        if not self.keys:
            q.end()
            return
        top = int(np.argmax(self.p)) if len(self.p) and self.p.max() > 0 else -1
        f = QFont(self.font())
        f.setPointSize(9)
        q.setFont(f)
        name_w, pct_w, h = 84, 38, self.ROW
        bar_w = max(30, self.width() - name_w - pct_w - 8)
        for i, key in enumerate(self.keys):
            y = 2 + i * h
            v = float(self.p[i]) if i < len(self.p) else 0.0
            q.setPen(QColor(TEXT if i == top else MUTED))
            q.drawText(QRectF(0, y, name_w, h - 2), Qt.AlignVCenter | Qt.AlignLeft, gestures.name(key))
            q.setPen(Qt.NoPen)
            q.setBrush(QColor(TRACK))
            q.drawRoundedRect(QRectF(name_w, y + 5, bar_w, h - 10), 3, 3)
            q.setBrush(QColor(ACCENT if i == top else IDLE))
            q.drawRoundedRect(QRectF(name_w, y + 5, max(3.0, bar_w * v), h - 10), 3, 3)
            q.setPen(QColor(TEXT if i == top else MUTED))
            q.drawText(QRectF(name_w + bar_w + 4, y, pct_w, h - 2), Qt.AlignVCenter | Qt.AlignRight, f"{100 * v:.0f}%")
        q.end()


class SceneGrid(QWidget):
    """The puppet-show scene files, two columns: number and gesture on the left of a cell, the
    file's state on the right; the scene that is playing in cobalt with a marker."""

    ROW = 18

    def __init__(self) -> None:
        super().__init__()
        self.cells: list[tuple[str, str, str, bool]] = []       # (name, state, state colour, playing)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setFixedHeight(4 * self.ROW)

    def set(self, cells: list[tuple[str, str, str, bool]]) -> None:
        if cells != self.cells:
            self.cells = cells
            self.setFixedHeight(max(1, (len(cells) + 1) // 2) * self.ROW)
            self.update()

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        f = QFont(self.font())
        f.setPointSize(9)
        half, col_w = (len(self.cells) + 1) // 2, self.width() / 2
        for i, (name, state, colour, playing) in enumerate(self.cells):
            x, y = (i // half) * col_w, (i % half) * self.ROW
            f.setBold(playing)
            p.setFont(f)
            fm = p.fontMetrics()
            state_w = fm.horizontalAdvance(state) + 10
            p.setPen(QColor(colour))
            p.drawText(QRectF(x + col_w - state_w, y, state_w - 6, self.ROW), Qt.AlignVCenter | Qt.AlignRight, state)
            p.setPen(QColor(ACCENT if playing else TEXT))
            text = ("▸ " if playing else "") + name
            p.drawText(QRectF(x, y, col_w - state_w - 2, self.ROW), Qt.AlignVCenter | Qt.AlignLeft,
                       fm.elidedText(text, Qt.ElideRight, int(col_w - state_w - 2)))
        p.end()


__all__ = ["SceneGrid", "LEVEL_COLOR", "Lamp", "Badge", "FlowArrow", "LedDot", "Panel", "muted", "rule", "Segmented", "ElideLabel",
           "FitLabel", "KeyValues", "ProbBars", "IDLE", "TRACK"]
