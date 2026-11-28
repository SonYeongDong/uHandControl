"""The third panel: each model family's own view of its decision.

A model names its view in `GestureModel.view`; VIEWS maps that name to a widget. A view gets
`set_model(model)` once and `push(decision, gesture)` for every decision. To give a new model
its own view, add a widget here and register it in VIEWS.
"""
from __future__ import annotations

import math
import time

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QLineF, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from .. import gestures
from ..models import Decision, GestureModel
from ..models.cnn_net import KalmanDot
from .theme import BG, IDLE, MUTED, TEXT, ink

TRAIL = 12


def fit(p: QPainter, width: float, *texts: str) -> str:
    """The first of `texts` (longest first) that fits `width` in the painter's font; the last
    one shortened with an ellipsis if none does."""
    fm = p.fontMetrics()
    for t in texts:
        if fm.horizontalAdvance(t) <= width:
            return t
    return fm.elidedText(texts[-1], Qt.ElideRight, int(width))


class SignalMapView(pg.PlotWidget):
    """A t-SNE map of the model's training windows, with the live window as a moving dot.
    The outlined dot and its tail are Kalman-filtered; the faint small dot is the unfiltered position."""

    TITLE = "신호 지도 (t-SNE)"
    HINT = "학습 창들의 지도. 테두리 있는 큰 점 = 지금 신호, 흐린 점 = 필터 전 위치"

    def __init__(self) -> None:
        super().__init__()
        self.setMouseEnabled(False, False)
        self.hideButtons()
        self.setAspectLocked(True)
        self.setMenuEnabled(False)
        for ax in ("left", "bottom"):
            self.getAxis(ax).setStyle(showValues=False)
            self.getAxis(ax).setTicks([[]])
        self.ref = pg.ScatterPlotItem(size=5, pen=None, symbol="o")
        self.addItem(self.ref)
        self.tail = pg.PlotDataItem(pen=pg.mkPen(TEXT, width=1.5))
        self.addItem(self.tail)
        self.raw = pg.ScatterPlotItem(size=8, pen=None, symbol="o", brush=pg.mkBrush(15, 23, 42, 70))
        self.addItem(self.raw)
        self.dot = pg.ScatterPlotItem(size=17, symbol="o", pen=pg.mkPen(TEXT, width=2))
        self.addItem(self.dot)
        self.texts: list[pg.TextItem] = []
        self.trail: list[np.ndarray] = []
        self.kalman = KalmanDot(accel=1.0, noise=0.3)

    def set_model(self, model: GestureModel) -> None:
        for t in self.texts:
            self.removeItem(t)
        self.texts = []
        self.clear_live()
        data = model.view_data()
        xy, keys = data["xy"], np.array(data["keys"])
        brushes = []
        for k in keys:
            c = QColor(gestures.colour(k))
            brushes.append(pg.mkBrush(c.red(), c.green(), c.blue(), 120))
        self.ref.setData(xy[:, 0], xy[:, 1], brush=brushes)
        for k in dict.fromkeys(keys.tolist()):
            centre = np.median(xy[keys == k], axis=0)
            t = pg.TextItem(gestures.name(k), color=TEXT, anchor=(0.5, 0.5))
            f = QFont(self.font())
            f.setBold(True)
            t.setFont(f)
            t.setPos(float(centre[0]), float(centre[1]))
            self.addItem(t)
            self.texts.append(t)
        self.autoRange()

    def clear_live(self) -> None:
        self.trail = []
        self.kalman.reset()
        self.tail.setData([], [])
        self.dot.setData([], [])
        self.raw.setData([], [])

    def push(self, d: Decision, gesture: str | None) -> None:
        xy = d.view.get("xy")
        if xy is None:
            return
        cur = self.kalman.update(xy)
        self.trail = (self.trail + [cur])[-TRAIL:]
        tr = np.array(self.trail)
        self.tail.setData(tr[:, 0], tr[:, 1])
        self.raw.setData([xy[0]], [xy[1]])
        self.dot.setData([cur[0]], [cur[1]], brush=pg.mkBrush(gestures.colour(gesture)))


class TreeVoteView(QWidget):
    """A random forest's decision as it is made: every tree is one dot, placed in the row of
    the gesture it voted for. One colour in one row = the forest agrees; dots spread over
    several rows = it is unsure (and the robot then moves more slowly)."""

    TITLE = "나무 투표"
    HINT = "점 하나 = 나무 한 그루. 한 줄로 몰리면 확실, 여러 줄로 갈라지면 헷갈리는 중"

    def __init__(self) -> None:
        super().__init__()
        self.keys: list[str] = []
        self.n_trees = 0
        self.counts = np.zeros(0, int)
        self.confirmed: str | None = None
        self.setMinimumSize(180, 190)

    def set_model(self, model: GestureModel) -> None:
        self.keys = list(model.gestures)
        self.n_trees = getattr(model, "n_trees", 0)
        self.clear_live()

    def clear_live(self) -> None:
        self.counts = np.zeros(len(self.keys), int)
        self.confirmed = None
        self.update()

    def push(self, d: Decision, gesture: str | None) -> None:
        votes = d.view.get("votes")
        if votes is None:
            return
        self.counts = np.bincount(votes, minlength=len(self.keys))
        self.n_trees = int(len(votes))
        self.confirmed = gesture
        self.update()

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        n = len(self.keys)
        if not n or not self.n_trees:
            p.setPen(QColor(MUTED))
            p.drawText(self.rect(), Qt.AlignCenter, "투표를 기다리는 중")
            p.end()
            return
        name_w, count_w, gap = 80, 42, 6
        head_h = 22
        row_h = (self.height() - head_h - gap * (n - 1)) / n
        area_w = self.width() - name_w - count_w - 8
        # the dot spacing at which the whole forest fits in one row; every row uses it, so a
        # row's filled width is its share of the vote
        pitch = math.sqrt(area_w * row_h / self.n_trees) * 0.95
        rows = max(1, int(row_h // pitch))
        pitch = min(row_h / rows, area_w / math.ceil(self.n_trees / rows))
        r = max(1.0, pitch * 0.4)
        top = int(np.argmax(self.counts)) if self.counts.sum() else -1
        f = QFont(self.font())
        f.setPointSize(9)
        p.setFont(f)
        p.setPen(QColor(MUTED))
        total = int(self.counts.sum())
        lead = f" · 1등 {100 * self.counts[top] / total:.0f}%" if total else ""
        p.drawText(QRectF(0, 0, self.width(), head_h), Qt.AlignLeft | Qt.AlignVCenter,
                   fit(p, self.width(), f"나무 {self.n_trees}그루의 이번 투표{lead}", f"{self.n_trees}그루의 투표{lead}"))
        for i, key in enumerate(self.keys):
            y = head_h + i * (row_h + gap)
            c = int(self.counts[i]) if i < len(self.counts) else 0
            lead = i == top
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(BG))
            p.drawRoundedRect(QRectF(name_w - 4, y, area_w + 8, row_h), 4, 4)
            if key == self.confirmed:                      # the gesture the screen has settled on
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(ink(gestures.colour(key)), 1.5))
                p.drawRoundedRect(QRectF(name_w - 4, y, area_w + 8, row_h), 4, 4)
            p.setPen(QColor(TEXT if lead else MUTED))
            p.drawText(QRectF(0, y, name_w - 8, row_h), Qt.AlignVCenter | Qt.AlignLeft, gestures.name(key))
            p.drawText(QRectF(name_w + area_w + 8, y, count_w - 4, row_h), Qt.AlignVCenter | Qt.AlignRight, f"{c}표")
            col = ink(gestures.colour(key))
            if not lead:
                col.setAlpha(150)
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            y0 = y + (row_h - rows * pitch) / 2 + pitch / 2
            for k in range(c):
                cx = name_w + (k // rows) * pitch + pitch / 2
                cy = y0 + (k % rows) * pitch
                p.drawEllipse(QRectF(cx - r, cy - r, 2 * r, 2 * r))
        p.end()


FADE_S = 1.2                # how long a path the signal has left keeps glowing
FLASH_S = 0.3               # the dark strike when the signal takes a new path


class DecisionTreeView(QWidget):
    """One real tree of the forest, drawn whole: every line is a question answered yes or no,
    every coloured square at the end of a branch an answer (a gesture).

    The path the current window takes from the root to its answer is lit in that gesture's
    colour. When the signal takes a different path it strikes dark like a pen stroke, and the path
    it left fades out over FADE_S, so a change can be followed even at ten decisions a second.
    """

    def __init__(self) -> None:
        super().__init__()
        self.keys: list[str] = []
        self.left = self.right = self.answer = None
        self.index = self.of = 0
        self.trails: dict[int, dict] = {}        # leaf -> {"path", "seen", "struck"}
        self.current: int | None = None
        self._geo_key = None
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._tick)
        self.setMinimumSize(180, 130)

    def set_model(self, model: GestureModel) -> None:
        tree = model.view_data().get("tree")
        self.keys = list(model.gestures)
        self.clear_live()
        if tree is None:
            self.left = None
            return
        self.left, self.right, self.answer = tree["left"], tree["right"], tree["answer"]
        self.index, self.of = tree["index"], tree["of"]
        # tidy layout: leaves evenly spaced left to right, a parent midway over its children
        n = len(self.left)
        x, depth, order = np.zeros(n), np.zeros(n, int), 0
        stack = [(0, 0, False)]
        while stack:
            node, d, children_done = stack.pop()
            depth[node] = d
            if self.left[node] == -1:
                x[node], order = order, order + 1
            elif children_done:
                x[node] = (x[self.left[node]] + x[self.right[node]]) / 2
            else:
                stack += [(node, d, True), (int(self.right[node]), d + 1, False), (int(self.left[node]), d + 1, False)]
        self.ux, self.uy = x / max(1, order - 1), depth / max(1, depth.max())
        self.n_leaves, self.depth = order, int(depth.max())
        self._geo_key = None
        self.update()

    def clear_live(self) -> None:
        self.trails, self.current = {}, None
        self.timer.stop()
        self.update()

    def push(self, d: Decision, gesture: str | None) -> None:
        path = d.view.get("path")
        if path is None or self.left is None:
            return
        leaf, now = int(path[-1]), time.monotonic()
        trail = self.trails.setdefault(leaf, {"path": path, "struck": now})
        if leaf != self.current:
            trail["struck"], self.current = now, leaf
        trail["seen"] = now
        if not self.timer.isActive():
            self.timer.start()
        self.update()

    def _tick(self) -> None:
        now = time.monotonic()
        self.trails = {leaf: t for leaf, t in self.trails.items() if leaf == self.current or now - t["seen"] < FADE_S}
        cur = self.trails.get(self.current)
        if len(self.trails) <= 1 and (cur is None or now - cur["struck"] > FLASH_S):
            self.timer.stop()                    # one steady path: nothing left to animate
        self.update()

    def _geometry(self, area: QRectF) -> None:
        key = (area.x(), area.y(), area.width(), area.height(), id(self.left))
        if key == self._geo_key:
            return
        self._geo_key = key
        self._pts = [QPointF(area.left() + ux * area.width(), area.top() + uy * area.height())
                     for ux, uy in zip(self.ux, self.uy)]
        self._lines = [QLineF(self._pts[i], self._pts[int(c)]) for i in range(len(self.left)) if self.left[i] != -1
                       for c in (self.left[i], self.right[i])]

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        if self.left is None:
            p.setPen(QColor(MUTED))
            p.drawText(self.rect(), Qt.AlignCenter, "나무를 기다리는 중")
            p.end()
            return
        f = QFont(self.font())
        f.setPointSize(9)
        p.setFont(f)
        line_h = p.fontMetrics().height() + 2
        p.setPen(QColor(MUTED))
        p.drawText(QRectF(0, 0, self.width(), line_h), Qt.AlignLeft | Qt.AlignVCenter, fit(
            p, self.width(), f"{self.of}그루 중 {self.index + 1}번 나무 · 질문 {len(self.left) - self.n_leaves}개 · 답 {self.n_leaves}개",
            f"{self.index + 1}번 나무 · 질문 {len(self.left) - self.n_leaves} · 답 {self.n_leaves}"))
        area = QRectF(6, line_h + 6, self.width() - 12, self.height() - 2 * line_h - 14)
        self._geometry(area)
        # the whole tree, dim
        p.setPen(QPen(QColor(IDLE), 1))
        p.drawLines(self._lines)
        p.setPen(Qt.NoPen)
        for i, pt in enumerate(self._pts):
            if self.left[i] == -1:
                c = ink(gestures.colour(self.keys[int(self.answer[i])]))
                c.setAlpha(190)
                p.fillRect(QRectF(pt.x() - 1.5, pt.y() - 1.5, 3, 3), c)
        # the paths: older ones first, the current one on top
        now = time.monotonic()
        p.setRenderHint(QPainter.Antialiasing)
        for leaf, t in sorted(self.trails.items(), key=lambda kv: (kv[0] == self.current, kv[1]["seen"])):
            if leaf == self.current:
                glow, flash = 1.0, max(0.0, 1 - (now - t["struck"]) / FLASH_S)
            else:
                glow, flash = max(0.0, 1 - (now - t["seen"]) / FADE_S) ** 1.5, 0.0
            if glow <= 0:
                continue
            col = ink(gestures.colour(self.keys[int(self.answer[leaf])]))
            line = QPolygonF([self._pts[int(i)] for i in t["path"]])
            for width, alpha in ((7 + 6 * flash, 55), (2.2 + 2 * flash, 235)):
                c = QColor(col)
                c.setAlpha(int(alpha * glow))
                p.setPen(QPen(c, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                p.drawPolyline(line)
            if flash > 0:
                p.setPen(QPen(QColor(15, 23, 42, int(255 * flash)), 1.2 + 1.8 * flash, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                p.drawPolyline(line)
            end = self._pts[leaf]
            c = QColor(col)
            c.setAlpha(int(255 * glow))
            p.setPen(Qt.NoPen)
            p.setBrush(c)
            p.drawEllipse(end, 5, 5)
        p.setRenderHint(QPainter.Antialiasing, False)
        if self.current is not None and self.current in self.trails:
            key = self.keys[int(self.answer[self.current])]
            p.setPen(ink(gestures.colour(key)))
            asked = len(self.trails[self.current]["path"]) - 1
            p.drawText(QRectF(0, self.height() - line_h, self.width(), line_h), Qt.AlignLeft | Qt.AlignVCenter, fit(
                p, self.width(), f"이 나무의 답 ▸ {gestures.name(key)} (질문 {asked}번)",
                f"답 ▸ {gestures.name(key)} · 질문 {asked}번"))
        p.end()


class ForestView(QWidget):
    """The random forest's view: one real tree with the live path on top, the vote of all the
    trees below."""

    TITLE = "나무 투표"
    HINT = "위: 나무 한 그루가 지금 신호를 판정하는 길 · 아래: 점 하나 = 나무 한 그루의 표"

    def __init__(self) -> None:
        super().__init__()
        self.tree, self.votes = DecisionTreeView(), TreeVoteView()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        v.addWidget(self.tree, 4)
        v.addWidget(self.votes, 5)

    def set_model(self, model: GestureModel) -> None:
        self.tree.set_model(model)
        self.votes.set_model(model)

    def clear_live(self) -> None:
        self.tree.clear_live()
        self.votes.clear_live()

    def push(self, d: Decision, gesture: str | None) -> None:
        self.tree.push(d, gesture)
        self.votes.push(d, gesture)


class SvmMarginView(QWidget):
    """An SVM's decision as the textbook draws it, one graph per gesture: that gesture against
    each of the others. The horizontal axis is a duel's decision value, so nothing is projected:
    the solid line is the boundary (0), the dashed lines are the margin (-1 and +1), and the
    support vectors of a duel sit exactly on those lines (a circle each side, larger for more).
    The outlined dot is the live signal in that duel: right of the boundary the row's gesture
    wins, and its distance from the boundary is the margin. Most wins is the answer."""

    TITLE = "동작별 1대1 대결과 마진"
    HINT = ("줄마다 그 동작 대 다른 동작들 · 실선 = 경계, 점선 = 마진, 그 위의 원 = 서포트 벡터 · "
            "테두리 있는 점 = 지금 신호(상대 동작의 색), 오른쪽이면 이김")
    SPAN = 2.5                  # decision values drawn; beyond it a dot stays at the edge

    def __init__(self) -> None:
        super().__init__()
        self.keys: list[str] = []
        self.pairs: list[tuple[int, int]] = []
        self.support = np.zeros((0, 0), int)           # [i, j]: support vectors of gesture i in its duel with j
        self.total = 0
        self.margin: np.ndarray | None = None          # [i, j] > 0: gesture i beats gesture j, by that much
        self.confirmed: str | None = None
        self.setMinimumSize(200, 190)

    def set_model(self, model: GestureModel) -> None:
        data = model.view_data()
        self.keys, self.pairs, self.total = list(model.gestures), list(data["pairs"]), int(data["total"])
        self.support = np.zeros((len(self.keys), len(self.keys)), int)
        for (i, j), (a, b) in zip(self.pairs, data["support"]):
            self.support[i, j], self.support[j, i] = a, b
        self.clear_live()

    def clear_live(self) -> None:
        self.margin = None
        self.confirmed = None
        self.update()

    def push(self, d: Decision, gesture: str | None) -> None:
        duels = d.view.get("duels")
        if duels is None:
            return
        m = np.zeros((len(self.keys), len(self.keys)))
        for (i, j), v in zip(self.pairs, duels):
            m[i, j], m[j, i] = v, -v
        self.margin, self.confirmed = m, gesture
        self.update()

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        n = len(self.keys)
        if n < 2 or self.margin is None:
            p.setPen(QColor(MUTED))
            p.drawText(self.rect(), Qt.AlignCenter, "판정을 기다리는 중")
            p.end()
            return
        f = QFont(self.font())
        f.setPointSize(9)
        small = QFont(f)
        small.setPointSize(8)
        p.setFont(f)
        chip, name_w, count_w, gap, head_h, axis_h = 12, 92, 40, 6, 20, 14
        row_h = (self.height() - head_h - axis_h - gap * (n - 1)) / n
        x0, width = name_w, self.width() - name_w - count_w - 6

        def at(value: float) -> float:
            return x0 + width * (float(np.clip(value, -self.SPAN, self.SPAN)) + self.SPAN) / (2 * self.SPAN)

        wins = (self.margin > 0).sum(axis=1)
        top = int(np.argmax(wins))
        p.setPen(QColor(MUTED))
        p.drawText(QRectF(0, 0, self.width(), head_h), Qt.AlignLeft | Qt.AlignVCenter, fit(
            p, self.width(), f"1대1 대결 {len(self.pairs)}개 · 서포트 벡터 {self.total:,}개 · 1등 {wins[top]}승",
            f"대결 {len(self.pairs)}개 · 서포트 벡터 {self.total:,}개", f"대결 {len(self.pairs)}개"))
        p.setFont(small)
        for value, text in ((-1, "−1"), (0, "경계"), (1, "+1")):
            p.drawText(QRectF(at(value) - 20, head_h, 40, axis_h), Qt.AlignCenter, text)
        p.drawText(QRectF(x0, head_h, 30, axis_h), Qt.AlignLeft | Qt.AlignVCenter, "◂ 짐")
        p.drawText(QRectF(x0 + width - 36, head_h, 36, axis_h), Qt.AlignRight | Qt.AlignVCenter, "이김 ▸")
        most = max(1, int(self.support.max()))
        lane = (row_h - 6) / (n - 1)
        dot = float(np.clip(lane * 0.42, 2.0, 3.6))
        for i, key in enumerate(self.keys):
            y = head_h + axis_h + i * (row_h + gap)
            lead = i == top
            col = ink(gestures.colour(key))
            # the name, with the colour this gesture has in the other rows
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            p.drawRoundedRect(QRectF(0, y + (row_h - 8) / 2, 8, 8), 2, 2)
            p.setFont(f)
            p.setPen(QColor(TEXT if lead else MUTED))
            p.drawText(QRectF(chip, y, name_w - chip - 6, row_h), Qt.AlignVCenter | Qt.AlignLeft, gestures.name(key))
            # the graph: a well, the margin as a white band, its two lines dashed, the boundary solid
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(BG))
            p.drawRoundedRect(QRectF(x0 - 4, y, width + 8, row_h), 4, 4)
            p.setBrush(QColor("#ffffff"))
            p.drawRect(QRectF(at(-1), y + 1, at(1) - at(-1), row_h - 2))
            if key == self.confirmed:                        # the gesture the screen has settled on
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(col, 1.5))
                p.drawRoundedRect(QRectF(x0 - 4, y, width + 8, row_h), 4, 4)
            p.setPen(QPen(QColor(IDLE), 1, Qt.DashLine))
            for value in (-1, 1):
                p.drawLine(QLineF(at(value), y + 2, at(value), y + row_h - 2))
            p.setPen(QPen(QColor(TEXT), 1.2))
            p.drawLine(QLineF(at(0), y + 1, at(0), y + row_h - 1))
            worst = None
            for k, j in enumerate(j for j in range(n) if j != i):
                cy = y + 3 + lane * (k + 0.5)
                other = ink(gestures.colour(self.keys[j]))
                # the duel's support vectors, on the margin lines: this gesture's right, the other's left
                p.setPen(Qt.NoPen)
                for value, colour, count in ((1, col, self.support[i, j]), (-1, other, self.support[j, i])):
                    r = float(np.clip(math.sqrt(count / most) * lane * 0.5, 1.2, lane * 0.5))
                    c = QColor(colour)
                    c.setAlpha(105)
                    p.setBrush(c)
                    p.drawEllipse(QPointF(at(value), cy), r, r)
                # the live signal: a stem from the boundary as long as the margin, and the dot
                m = float(self.margin[i, j])
                worst = m if worst is None else min(worst, m)
                p.setPen(QPen(col if m > 0 else other, 1.6))
                p.drawLine(QLineF(at(0), cy, at(m), cy))
                p.setPen(QPen(QColor(TEXT), 0.9))
                p.setBrush(other)
                p.drawEllipse(QPointF(at(m), cy), dot, dot)
            # wins, and the decision value of this gesture's worst duel (positive: it wins them all)
            right = QRectF(self.width() - count_w, y, count_w, row_h)
            p.setFont(f)
            p.setPen(QColor(TEXT if lead else MUTED))
            p.drawText(right.adjusted(0, 0, 0, -row_h / 2), Qt.AlignBottom | Qt.AlignRight, f"{wins[i]}승")
            p.setFont(small)
            p.setPen(QColor(MUTED))
            p.drawText(right.adjusted(0, row_h / 2, 0, 0), Qt.AlignTop | Qt.AlignRight, f"{worst:+.1f}".replace("-", "−"))
        p.end()


class PlainView(QLabel):
    """For a model without a view of its own."""

    TITLE = "모델 뷰"
    HINT = ""

    def __init__(self) -> None:
        super().__init__("이 모델에는 전용 뷰가 없습니다.\n동작별 확률은 오른쪽 칸에 표시됩니다.")
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(f"color: {MUTED};")

    def set_model(self, model: GestureModel) -> None:
        pass

    def clear_live(self) -> None:
        pass

    def push(self, d: Decision, gesture: str | None) -> None:
        pass


VIEWS = {"map": SignalMapView, "votes": ForestView, "duels": SvmMarginView, "bars": PlainView}
