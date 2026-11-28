"""The fifth panel's gauges: the six servos, where each one is and where it is being sent.
The hand itself is drawn in 3D by hand3d.HandViewport."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..motion.poses import AXES, HI, LO
from .theme import ACCENT, MUTED, TEXT, TRACK


class AxisBars(QWidget):
    """The six servos as gauges: bar = where the servo is, dark tick = the pose being sent."""

    def __init__(self) -> None:
        super().__init__()
        self.pos = np.full(6, 1500.0)
        self.target: np.ndarray | None = None
        self.setMinimumSize(140, 6 * 15 + 4)

    def set(self, position: np.ndarray, target: np.ndarray | None) -> None:
        self.pos, self.target = np.asarray(position, float), target
        self.update()

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        f = QFont(self.font())
        f.setPointSize(9)
        p.setFont(f)
        name_w, num_w, h = 36, 40, 15
        w = max(40, self.width() - name_w - num_w - 6)
        for i in range(6):
            y = 2 + i * h
            p.setPen(QColor(MUTED))
            p.drawText(QRectF(0, y, name_w, h - 3), Qt.AlignVCenter | Qt.AlignLeft, AXES[i])
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(TRACK))
            p.drawRoundedRect(QRectF(name_w, y + 4, w, h - 8), 3, 3)
            k = (self.pos[i] - LO[i]) / (HI[i] - LO[i])
            p.setBrush(QColor(ACCENT))
            p.drawRoundedRect(QRectF(name_w, y + 4, max(4.0, w * k), h - 8), 3, 3)
            if self.target is not None:
                kt = (self.target[i] - LO[i]) / (HI[i] - LO[i])
                p.setPen(QPen(QColor(TEXT), 2))
                x = name_w + w * float(np.clip(kt, 0, 1))
                p.drawLine(QPointF(x, y + 1), QPointF(x, y + h - 4))
            p.setPen(QColor(TEXT))
            p.drawText(QRectF(name_w + w + 4, y, num_w, h - 3), Qt.AlignVCenter | Qt.AlignRight, f"{self.pos[i]:.0f}")
        p.end()
