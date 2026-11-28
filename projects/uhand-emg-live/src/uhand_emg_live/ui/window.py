"""The demo screen: the pipeline left to right, one numbered stage per card.

  1 암밴드 → 2 EMG 신호 → 3 모델 → 4 인식된 동작 → 5 로봇손

Each stage carries its own controls (input in 1, model in 3, robot, mode and scene files in 5),
so setting the program up follows the data. The window only reads the engine's state about 30
times a second and draws it; everything that decides or sends lives in app.engine and runs the
same without a screen.
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFontMetrics, QIcon
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QMainWindow, QProgressBar, QPushButton, QScrollArea, QSlider, QStackedWidget,
                               QToolButton, QVBoxLayout, QWidget)

from uhand_about import add_about_action, product_logo

from .. import __version__, gestures
from ..engine import Engine
from ..models import ModelSpec
from ..robot import sender as rs
from ..sensor.sources import find_ch340, list_ports
from .hand_pic import HandPicture
from .hand3d import HandViewport
from .robot_view import AxisBars
from .theme import ACCENT, ACCENT_TEXT, GRID, LOGO_COLOR, MUTED, TEXT, TRACK, font
from .views import VIEWS
from .widgets import (LEVEL_COLOR, ElideLabel, FitLabel, FlowArrow, KeyValues, Lamp, LedDot, Panel, ProbBars,
                      Segmented, muted, rule)

RAW_SECONDS = 3
ACTIVITY_SAMPLES = 100      # the activity meter looks at the last 0.2 s
ACTIVITY_FULL = 25.0        # standard deviation (ADC counts) that fills the meter
UNSURE = 0.5
ADD_FILE = "<add>"          # the last entry of a scene list: browse for a file
SUBTITLE = "근전도 손동작으로 로봇손 움직이기"
STATE_TEXT = {"disconnected": "연결 안 됨", "connecting": "연결 중", "connected": "연결됨", "error": "오류"}
ROBOT_TEXT = {rs.OFF: "전송 끔 · 화면 시뮬만", rs.CONNECTING: "연결 중", rs.CONNECTED: "연결됨 · 전송 중",
              rs.RETRY: "연결 실패 · 재시도 중"}
ROBOT_LEVEL = {rs.OFF: "off", rs.CONNECTING: "busy", rs.CONNECTED: "ok", rs.RETRY: "error"}


def two_lines(label: QLabel) -> int:
    """Height of two lines of the label's text."""
    return 2 * label.fontMetrics().lineSpacing() + 2


class MainWindow(QMainWindow):
    def __init__(self, engine: Engine, specs: list[ModelSpec], problems: list[str] | None = None) -> None:
        super().__init__()
        self.engine, self.specs = engine, specs
        self.setWindowTitle("uHandEmgLive")
        self.seq = 0
        self.view_live = False             # the model view is showing a current decision
        self.view: QWidget | None = None
        self.views: dict[str, QWidget] = {}
        # Status-line notes by where they come from, so one source never erases another's.
        self.notes = {"start": "; ".join(problems or []), "model": "", "scene": "", "file": ""}
        self.scene_rows: dict[str, tuple[Lamp, QLabel, QComboBox]] = {}

        self.setWindowIcon(QIcon(str(Path(__file__).parent.with_name("uHandEmgLive.ico"))))
        add_about_action(self, "uHandEmgLive", SUBTITLE, __version__, LOGO_COLOR)
        root = QWidget()
        root.setObjectName("root")
        v = QVBoxLayout(root)
        v.setContentsMargins(16, 8, 16, 8)
        v.setSpacing(8)
        v.addLayout(self._top_bar())
        row = QHBoxLayout()
        row.setSpacing(3)
        panels = [self._panel_link(), self._panel_raw(), self._panel_view(), self._panel_decision(),
                  self._panel_robot()]
        for i, (panel, stretch) in enumerate(zip(panels, (4, 7, 8, 5, 6))):
            if i:
                row.addWidget(FlowArrow(), 0, Qt.AlignTop)       # the data flows left to right
            row.addWidget(panel, stretch)
        v.addLayout(row, 1)
        foot = QHBoxLayout()
        foot.setSpacing(16)
        version = QLabel(f"v{__version__}")
        version.setObjectName("muted")
        foot.addWidget(version)
        self.status = ElideLabel("", Qt.AlignLeft | Qt.AlignVCenter, Qt.ElideRight)    # never widens the window
        foot.addWidget(self.status, 1)
        v.addLayout(foot)
        self.setCentralWidget(root)
        # as large as is useful, but never larger than the screen it opens on
        area = QApplication.primaryScreen().availableGeometry()
        self.resize(min(1700, area.width() - 16), min(840, area.height() - 48))
        self.move(area.x() + (area.width() - self.width()) // 2, area.y() + 4)

        self._list_inputs()
        self._set_ahead(self.ahead.value())
        self._show_mode("follow")
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(33)

    # ------------------------------------------------------------ top bar
    def _top_bar(self) -> QHBoxLayout:
        """Logo, name and subtitle as in the other uHand programs; overall status and the stop
        button on the right."""
        bar = QHBoxLayout()
        bar.setSpacing(14)
        bar.addWidget(product_logo(self, 44, "appLogo"))
        titles = QVBoxLayout()
        titles.setSpacing(1)
        name = QLabel("uHandEmgLive")
        name.setObjectName("title")
        titles.addWidget(name)
        titles.addWidget(muted(SUBTITLE, wrap=False))
        bar.addLayout(titles)
        bar.setAlignment(titles, Qt.AlignVCenter)
        bar.addStretch(1)
        self.live_text = QLabel("●  입력 대기")
        self.live_text.setObjectName("badge")
        self.live_text.setFixedHeight(32)
        self.live_text.setMinimumWidth(140)
        self.live_text.setAlignment(Qt.AlignCenter)
        bar.addWidget(self.live_text)
        self.stop_btn = QPushButton("■  로봇 정지")
        self.stop_btn.setObjectName("stop")
        self.stop_btn.setCheckable(True)
        self.stop_btn.setMinimumWidth(128)
        self.stop_btn.setFixedHeight(34)
        self.stop_btn.setToolTip("로봇을 준비 자세로 돌려보내고 멈춥니다. 다시 누르면 재개합니다")
        self.stop_btn.toggled.connect(self._set_hold)
        bar.addWidget(self.stop_btn)
        return bar

    def _set_hold(self, on: bool) -> None:
        self.engine.set_hold(on)
        self.stop_btn.setText("▶  로봇 재개" if on else "■  로봇 정지")

    def _list_inputs(self) -> None:
        cur = self.inputs.currentData()
        self.inputs.clear()
        try:
            dongles = set(find_ch340())
            ports = list_ports()
        except Exception:                                    # noqa: BLE001 - no serial support: other inputs still work
            dongles, ports = set(), []
        for dev, desc in sorted(ports, key=lambda p: p[0] not in dongles):
            self.inputs.addItem(f"암밴드 {dev}" + (" (수신기)" if dev in dongles else f" · {desc[:24]}"), ("serial", dev))
        self.inputs.addItem("녹화 세션 재생…", ("replay", None))
        self.inputs.addItem("데모 신호 (장치 없음)", ("demo", None))
        self.inputs.setCurrentIndex(max(0, self._find_input(cur)))

    def _find_input(self, data) -> int:
        """Index of the input whose data equals `data` (findData does not match tuples)."""
        return next((i for i in range(self.inputs.count()) if self.inputs.itemData(i) == data), -1)

    def select_input(self, kind: str, value: str | None = None) -> None:
        """Pick an input as if chosen from the list and connect (used by the command line)."""
        if kind == "replay":
            self._open_replay(value)
            return
        i = self._find_input((kind, value))
        if i < 0:
            self.inputs.insertItem(0, f"암밴드 {value}", (kind, value))
            i = 0
        self.inputs.setCurrentIndex(i)
        self._toggle_link(force_open=True)

    def _open_replay(self, folder: str | None) -> None:
        if not folder:
            folder = QFileDialog.getExistingDirectory(self, "재생할 녹화 세션 폴더 (emg_bytes.bin 이 있는 폴더)")
        if not folder:
            return
        self.engine.open_input("replay", folder)
        self.inputs.setCurrentIndex(self._find_input(("replay", None)))

    def _toggle_link(self, checked: bool = False, force_open: bool = False) -> None:
        if not force_open and self.engine.input_open:
            self.engine.close_input()
            return
        kind, value = self.inputs.currentData()
        if kind == "replay":
            self._open_replay(None)                  # asks for the session folder
        else:
            self.engine.open_input(kind, value)

    def _load_model(self) -> None:
        spec = self.models.currentData()
        if spec is None:
            self.engine.set_model(None)
            self._show_view(None)
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            model = spec.load()
        except Exception as e:                               # noqa: BLE001 - show any load failure on screen
            self.notes["model"] = f"모델을 읽지 못했습니다 ({spec.title}): {e}"
            self.models.setCurrentIndex(0)
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.notes["model"] = ""
        missing = self.engine.unposed(model)
        if missing:
            self.notes["model"] = "로봇 자세가 없는 동작(준비 자세로 대신함): " + ", ".join(gestures.name(g) for g in missing)
        self.engine.set_model(model)
        self.seq = 0
        self._show_view(model)

    def select_model(self, text: str) -> bool:
        for i in range(1, self.models.count()):
            if text.lower() in self.models.itemText(i).lower():
                self.models.setCurrentIndex(i)
                return True
        return False

    def _set_robot(self) -> None:
        self.engine.set_robot(self.robots.currentData())

    def select_robot(self, which: str) -> None:
        self.robots.setCurrentIndex({"off": 0, "virtual": 1, "real": 2}[which])

    def _set_mode(self) -> None:
        mode = self.modes.currentData()
        self.engine.set_mode(mode)
        self._show_mode(mode)

    def _show_mode(self, mode: str) -> None:
        """Show the controls of this mode: prediction and servo gauges for following the hand,
        the scene file of each gesture for the puppet show."""
        theater = mode == "theater"
        for w in (self.ahead_label, self.ahead, self.ahead_text, self.axes):
            w.setVisible(not theater)
        self.scene_head.setVisible(theater)
        self.scene_box.setVisible(theater)
        if theater:
            self._fill_scene_rows()
        self.hand.setToolTip("오른쪽 드래그로 회전 · 휠로 확대\n" + (
            "공연 파일의 카드대로 움직입니다. 장면은 카드와 카드 사이에서 바뀝니다") if theater else "오른쪽 드래그로 회전 · 휠로 확대\n"
                             "3D 손 = 지금 서보 위치(시뮬) · 아래 막대의 검은 눈금 = 다음에 보낼 예측 자세")
        self._note_scenes(theater)

    def _note_scenes(self, theater: bool) -> None:
        bad = [s for s in self.engine.scene_report() if s.state == "damaged"] if theater else []
        self.notes["scene"] = "읽지 못한 공연 파일: " + ", ".join(f"{s.file} ({s.problem})" for s in bad) if bad else ""

    def select_mode(self, mode: str) -> None:
        self.modes.setCurrentIndex(self.modes.findData(mode))

    def _set_ahead(self, ms: int) -> None:
        self.engine.predict_ms = int(ms)
        self.ahead_text.setText(f"{ms} ms" if ms else "없음")

    # ------------------------------------------------------------ scene file of each gesture
    def _fill_scene_rows(self) -> None:
        """One row per gesture: status light, gesture name, the list of scene files to pick from.
        Called on entering the puppet show, so files added meanwhile appear."""
        report = self.engine.scene_report()
        library = self.engine.scene_library()
        if not self.scene_rows:
            bold = QFontMetrics(font(10, bold=True))
            widest = max(bold.horizontalAdvance('▸ ' + gestures.name(s.key)) for s in report) + 4
            for r, key in enumerate(s.key for s in report):
                lamp, name, pick = Lamp(10), QLabel(gestures.name(key)), QComboBox()
                name.setMinimumWidth(widest)
                pick.setMinimumWidth(80)
                pick.setFixedHeight(24)
                pick.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
                pick.activated.connect(lambda _i, k=key: self._pick_scene(k))
                self.scene_grid.addWidget(lamp, r, 0)
                self.scene_grid.addWidget(name, r, 1)
                self.scene_grid.addWidget(pick, r, 2)
                self.scene_rows[key] = (lamp, name, pick)
        for info in report:
            pick = self.scene_rows[info.key][2]
            pick.blockSignals(True)
            pick.clear()
            pick.addItem(f"기본 · action_{info.number:02d}", None)
            for label, path in library:
                pick.addItem(label, path)
            if info.picked and all(path != info.picked for _, path in library):
                pick.addItem(info.file, info.picked)             # picked earlier, no longer listed: still what plays
            pick.addItem("＋ 파일 추가…", ADD_FILE)
            at = next((i for i in range(1, pick.count()) if pick.itemData(i) == info.picked), 0)
            pick.setCurrentIndex(at)
            pick.blockSignals(False)

    def _pick_scene(self, key: str) -> None:
        path = self.scene_rows[key][2].currentData()
        problem = ""
        if path == ADD_FILE:
            path, problem = self._add_scene_file()
            if path == ADD_FILE:                     # cancelled or unusable: leave the gesture as it was
                self._fill_scene_rows()
                self.notes["file"] = problem
                return
        self.notes["file"] = ""
        self.engine.set_scene_file(key, path)
        self._fill_scene_rows()                      # a file just added appears in every gesture's list
        self._note_scenes(True)

    def _add_scene_file(self) -> tuple[str, str]:
        """Ask for a scene file and add it. -> (path to pick, "") or (ADD_FILE, what went wrong)."""
        chosen, _ = QFileDialog.getOpenFileName(self, "추가할 공연 파일 (uHandMotionCreator로 저장한 .uhjson)", "",
                                                "공연 파일 (*.uhjson)")
        if not chosen:
            return ADD_FILE, ""
        try:
            return self.engine.add_scene_file(chosen), ""
        except (OSError, ValueError, RecursionError) as e:
            return ADD_FILE, f"공연 파일을 추가하지 못했습니다 ({os.path.basename(chosen)}): {e}"

    # ------------------------------------------------------------ panels
    def _panel_link(self) -> Panel:
        self.p_link = p = Panel(1, "암밴드")
        p.setMinimumWidth(198)
        p.setMaximumWidth(260)
        row = QHBoxLayout()
        row.setSpacing(4)
        self.inputs = QComboBox()
        self.inputs.setMinimumWidth(90)
        self.inputs.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        row.addWidget(self.inputs, 1)
        again = QToolButton()
        again.setText("⟳")
        again.setToolTip("포트 목록 새로고침")
        again.clicked.connect(self._list_inputs)
        row.addWidget(again)
        p.body.addLayout(row)
        self.connect_btn = QPushButton("연결")
        self.connect_btn.setObjectName("primary")
        self.connect_btn.clicked.connect(self._toggle_link)
        p.body.addWidget(self.connect_btn)
        for w in (self.inputs, again, self.connect_btn):
            w.setFixedHeight(30)
        p.body.addWidget(rule())
        self.link_state = FitLabel(15, align=Qt.AlignLeft | Qt.AlignVCenter)
        self.link_state.set("연결 안 됨")
        p.body.addWidget(self.link_state)
        self.link_kv = KeyValues(["입력", "모드", "수신", "배터리", "손실 프레임"])
        p.body.addWidget(self.link_kv)
        self.battery = QProgressBar()
        self.battery.setRange(0, 100)
        self.battery.setTextVisible(False)
        self.battery.setFixedHeight(6)
        p.body.addWidget(self.battery)
        p.body.addWidget(rule())
        p.body.addWidget(muted("채널 상태", wrap=False))
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(4)
        self.ch_lamps = []
        for i in range(8):
            cell = QHBoxLayout()
            cell.setSpacing(6)
            lamp = Lamp(10)
            cell.addWidget(lamp)
            cell.addWidget(QLabel(f"CH{i + 1}"))
            cell.addStretch(1)
            grid.addLayout(cell, i // 2, i % 2)
            self.ch_lamps.append(lamp)
        p.body.addLayout(grid)
        p.body.addWidget(rule())
        self.issues = QLabel()
        self.issues.setWordWrap(True)
        self.issues.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.issues.setTextFormat(Qt.RichText)
        p.body.addWidget(self.issues, 1)
        return p

    def _panel_raw(self) -> Panel:
        self.p_raw = p = Panel(2, "EMG 신호")
        p.setMinimumWidth(190)
        self.gl = pg.GraphicsLayoutWidget()
        self.gl.ci.layout.setSpacing(0)
        self.gl.ci.layout.setContentsMargins(0, 0, 0, 0)
        self.gl.ci.layout.setColumnFixedWidth(1, 46)
        self.curves, self.meters, plots = [], [], []
        for c in range(8):
            plot = self.gl.addPlot(row=c, col=0)
            plot.setMouseEnabled(x=False, y=False)
            plot.hideButtons()
            plot.setMenuEnabled(False)
            plot.setYRange(0, 255, padding=0.02)
            plot.setXRange(-RAW_SECONDS, 0, padding=0)
            plot.showGrid(x=False, y=True, alpha=0.18)
            left = plot.getAxis("left")
            left.setWidth(38)
            left.setTicks([[(127, f"CH{c + 1}")]])
            left.setTextPen(pg.mkPen(TEXT))
            left.setPen(pg.mkPen(GRID))
            bottom = plot.getAxis("bottom")
            bottom.setPen(pg.mkPen(GRID))
            bottom.setTextPen(pg.mkPen(MUTED))
            if c < 7:
                bottom.setStyle(showValues=False)
                bottom.setHeight(4)
            else:
                bottom.setLabel("시간 (초)")
            if plots:
                plot.setXLink(plots[0])
            plot.setClipToView(True)
            self.curves.append(plot.plot(pen=pg.mkPen(ACCENT, width=1)))
            plots.append(plot)
            # the activity meter of this channel, in the same row so the two stay aligned
            meter = self.gl.addPlot(row=c, col=1)
            meter.setMouseEnabled(x=False, y=False)
            meter.hideButtons()
            meter.setMenuEnabled(False)
            meter.hideAxis("left")
            meter.hideAxis("bottom")
            meter.setXRange(-0.12, 1, padding=0)
            meter.setYRange(0, 1, padding=0)
            meter.addItem(pg.BarGraphItem(x0=[0], x1=[1], y=[0.5], height=0.22, brush=TRACK, pen=None))
            bar = pg.BarGraphItem(x0=[0], x1=[0], y=[0.5], height=0.22, brush=ACCENT, pen=None)
            meter.addItem(bar)
            self.meters.append(bar)
        p.body.addWidget(self.gl, 1)
        p.body.addWidget(muted("받은 값 그대로 (0~255, 필터 없음), 최근 3초 · 오른쪽 막대 = 지금 신호 세기"))
        return p

    def _panel_view(self) -> Panel:
        self.p_view = p = Panel(3, "모델")
        p.setMinimumWidth(250)
        self.models = QComboBox()
        self.models.setMinimumWidth(120)
        self.models.setFixedHeight(30)
        self.models.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.models.addItem("(모델을 고르세요)", None)
        for s in self.specs:
            self.models.addItem(f"[{s.kind}] {s.title}", s)
        self.models.currentIndexChanged.connect(self._load_model)
        p.body.addWidget(self.models)
        self.view_title = ElideLabel("", Qt.AlignLeft | Qt.AlignVCenter, Qt.ElideRight)
        self.view_title.setStyleSheet("font-size: 15px; font-weight: 650;")
        p.body.addWidget(self.view_title)
        self.stack = QStackedWidget()
        self.no_model = muted("모델을 고르면 그 모델이 신호를 판정하는 모습이 여기에 나옵니다")
        self.no_model.setAlignment(Qt.AlignCenter)
        self.stack.addWidget(self.no_model)
        p.body.addWidget(self.stack, 1)
        self.view_hint = muted()
        p.body.addWidget(self.view_hint)
        return p

    def _show_view(self, model) -> None:
        if model is None:
            self.view = None
            self.stack.setCurrentWidget(self.no_model)
            self.view_title.set("")
            self.view_hint.setText("")
            return
        name = model.view if model.view in VIEWS else "bars"
        if name not in self.views:
            self.views[name] = VIEWS[name]()
            self.stack.addWidget(self.views[name])
        self.view = self.views[name]
        self.view.set_model(model)
        self.stack.setCurrentWidget(self.view)
        self.view_title.set(self.view.TITLE)
        self.view_hint.setText(self.view.HINT)

    def _panel_decision(self) -> Panel:
        self.p_dec = p = Panel(4, "인식된 동작", focus=True)
        p.setMinimumWidth(236)
        p.setMaximumWidth(330)
        self.pic = HandPicture(caption=False)
        self.pic.setMinimumHeight(80)
        p.body.addWidget(self.pic, 1)
        self.big = FitLabel(30, color=TEXT)
        p.body.addWidget(self.big)
        self.conf = FitLabel(16)
        p.body.addWidget(self.conf)
        self.conf_bar = QProgressBar()
        self.conf_bar.setRange(0, 100)
        self.conf_bar.setTextVisible(False)
        self.conf_bar.setFixedHeight(8)
        p.body.addWidget(self.conf_bar)
        self.sub = ElideLabel("", Qt.AlignCenter, Qt.ElideRight)
        p.body.addWidget(self.sub)
        self.truth = ElideLabel("", Qt.AlignCenter, Qt.ElideRight)
        p.body.addWidget(self.truth)
        self.bars = ProbBars()
        p.body.addWidget(self.bars)
        self.model_info = ElideLabel("", Qt.AlignLeft | Qt.AlignVCenter, Qt.ElideRight)
        p.body.addWidget(self.model_info)
        self.cal_btn = QPushButton("착용 보정 시작 (약 40초)")
        self.cal_btn.setMinimumHeight(30)
        self.cal_btn.clicked.connect(self._calibrate)
        p.body.addWidget(self.cal_btn)
        self.cal_bar = QProgressBar()
        self.cal_bar.setRange(0, 1000)
        self.cal_bar.setTextVisible(False)
        self.cal_bar.setFixedHeight(8)
        p.body.addWidget(self.cal_bar)
        self.cal_note = QLabel()
        self.cal_note.setWordWrap(True)
        self.cal_note.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.cal_note.setFixedHeight(two_lines(self.cal_note))
        p.body.addWidget(self.cal_note)
        return p

    def _calibrate(self) -> None:
        if self.engine.state().calib is not None:
            self.engine.cancel_calibration()
        else:
            self.engine.start_calibration()

    def _panel_robot(self) -> Panel:
        self.p_robot = p = Panel(5, "로봇손")
        p.setMinimumWidth(254)
        p.setMaximumWidth(340)
        self.hand = HandViewport()
        p.body.addWidget(self.hand, 3)
        out = QHBoxLayout()
        out.setSpacing(6)
        self.led = LedDot()
        out.addWidget(self.led)
        out.addWidget(muted("LED", wrap=False))
        out.addStretch(1)
        self.tone = QLabel("♪ –")
        self.tone.setObjectName("muted")
        self.tone.setMinimumWidth(76)
        self.tone.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        out.addWidget(self.tone)
        p.body.addLayout(out)
        self.robot_state = ElideLabel("", Qt.AlignCenter, Qt.ElideRight)
        p.body.addWidget(self.robot_state)
        r = self.engine.robot_addresses
        self.robots = Segmented([("끄기", None), ("가상", "virtual"), ("실물", "real")])
        self.robots.setToolTip(f"끄기: 화면 시뮬만 · 가상: uHandVirtualServer {r['virtual']} · 실물: 로봇손 {r['real']}")
        self.robots.changed.connect(self._set_robot)
        p.body.addWidget(self.robots)
        self.modes = Segmented([("따라 하기", "follow"), ("인형극", "theater")])
        self.modes.setToolTip("따라 하기: 예측한 자세로 손을 따라 움직임 · 인형극: 확정된 동작의 공연 파일을 재생")
        self.modes.changed.connect(self._set_mode)
        p.body.addWidget(self.modes)
        ahead = QHBoxLayout()
        self.ahead_label = muted("예측", wrap=False)
        ahead.addWidget(self.ahead_label)
        self.ahead = QSlider(Qt.Horizontal)
        self.ahead.setRange(0, 500)
        self.ahead.setSingleStep(50)
        self.ahead.setPageStep(50)
        self.ahead.setValue(self.engine.predict_ms)
        self.ahead.setToolTip("몇 ms 뒤의 자세를 미리 보낼지. 클수록 새 자세에 일찍 닿지만 더 떨립니다. 0 = 예측 없음")
        self.ahead.valueChanged.connect(self._set_ahead)
        ahead.addWidget(self.ahead, 1)
        self.ahead_text = QLabel()
        self.ahead_text.setMinimumWidth(52)
        self.ahead_text.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        ahead.addWidget(self.ahead_text)
        p.body.addLayout(ahead)
        self.axes = AxisBars()
        p.body.addWidget(self.axes)
        # puppet show: which scene file each gesture plays (scrolls when the window is short)
        self.scene_head = muted("동작마다 재생할 공연 파일", wrap=False)
        p.body.addWidget(self.scene_head)
        inner = QWidget()
        self.scene_grid = QGridLayout(inner)
        self.scene_grid.setContentsMargins(0, 0, 4, 0)
        self.scene_grid.setHorizontalSpacing(6)
        self.scene_grid.setVerticalSpacing(2)
        self.scene_grid.setColumnStretch(2, 1)
        self.scene_box = QScrollArea()
        self.scene_box.setWidgetResizable(True)
        self.scene_box.setFrameShape(QFrame.NoFrame)
        self.scene_box.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scene_box.setStyleSheet("QScrollArea { background: transparent; }")
        self.scene_box.viewport().setAutoFillBackground(False)
        inner.setAutoFillBackground(False)
        self.scene_box.setWidget(inner)
        self.scene_box.setMinimumHeight(3 * 27)
        p.body.addWidget(self.scene_box, 12)
        p.body.addWidget(rule())
        self.send_state = ElideLabel("", Qt.AlignLeft | Qt.AlignVCenter, Qt.ElideRight)
        self.send_state.setStyleSheet("font-size: 15px; font-weight: 650;")
        p.body.addWidget(self.send_state)
        self.send_kv = KeyValues(["주소", "전송", "응답", "실패"])
        p.body.addWidget(self.send_kv)
        self.send_error = ElideLabel("", Qt.AlignLeft | Qt.AlignVCenter, Qt.ElideRight)
        p.body.addWidget(self.send_error)
        return p

    # ------------------------------------------------------------ drawing
    def refresh(self) -> None:
        st = self.engine.state()
        self._draw_link(st)
        self._draw_raw()
        self._draw_view(st)
        self._draw_decision(st)
        self._draw_robot(st)
        send = self._draw_send()
        h = st.health
        parts = []
        if h.state == "connected":
            parts.append(f"수집 {h.rate:.0f} Hz")
            if h.mode == "hex":
                parts.append(f"채널 {sum(c == 'ok' for c in h.channels)}/{len(h.channels)}")
        m = self.engine.model
        if m is not None:
            parts += [f"모델이 보는 신호 {m.delay_s * 1000:.0f} ms", f"판정 {st.rate:.0f}회/초", f"계산 {st.cost_ms:.0f} ms"]
        if send.state == rs.CONNECTED and send.rtt_ms is not None:
            parts.append(f"로봇 응답 {send.rtt_ms:.0f} ms")
        if st.error:
            parts.append(f"내부 오류: {st.error}")
        parts += [note for note in self.notes.values() if note]
        self.status.set("     |     ".join(parts), MUTED)

    def _draw_link(self, st) -> None:
        h = st.health
        level = "busy" if h.state == "connecting" else ("off" if h.state == "disconnected" else h.level)
        self.p_link.lamp.set(level)
        if h.state != "connected":
            text = STATE_TEXT.get(h.state, h.state)
            live = "연결 중" if h.state == "connecting" else "입력 대기"
        else:
            text = {"ok": "정상", "warn": "주의", "error": "신호 이상"}[h.level]
            live = {"ok": "실시간 수집 중", "warn": "수집 중 · 주의", "error": "신호 이상"}[h.level]
        self.link_state.set(text, LEVEL_COLOR[level] if level != "off" else MUTED)
        self.live_text.setText("●  " + live)
        colour = ACCENT_TEXT if level in ("off", "busy") else LEVEL_COLOR[level]
        self.live_text.setStyleSheet(f"color: {colour};")
        self.connect_btn.setText("연결" if h.state == "disconnected" else "연결 끊기")
        on = h.state == "connected"
        self.link_kv.set("입력", h.source or "–")
        self.link_kv.set("모드", {"hex": "HEX 500 Hz", "ascii": "ASCII 67 Hz"}.get(h.mode, "–") if on else "–",
                         LEVEL_COLOR["error"] if on and h.mode == "ascii" else None)
        self.link_kv.set("수신", f"{h.rate:.0f} Hz" if on else "–")
        self.link_kv.set("배터리", f"{h.battery}%" if on and h.battery is not None else "–")
        self.battery.setValue(int(h.battery) if on and h.battery is not None else 0)
        self.link_kv.set("손실 프레임", str(h.lost_frames) if on else "–")
        for lamp, c in zip(self.ch_lamps, h.channels):
            lamp.set("off" if not on or h.mode != "hex" else ("ok" if c == "ok" else "warn"))
        lines = [f"<span style='color:{LEVEL_COLOR[i.level]}'>{'■' if i.level == 'error' else '▲'} {i.text}</span>"
                 for i in h.issues]
        self.issues.setText("<br><br>".join(lines) if lines else f"<span style='color:{MUTED}'>이상 없음</span>")

    def _draw_raw(self) -> None:
        data = self.engine.raw_last(RAW_SECONDS * 500)
        n = len(data)
        self.p_raw.lamp.set("ok" if n else "off")
        if not n:
            for cv, bar in zip(self.curves, self.meters):
                cv.setData([], [])
                bar.setOpts(x1=[0])
            return
        x = (np.arange(n) - n) / 500.0
        level = np.clip(np.std(data[-ACTIVITY_SAMPLES:], axis=0) / ACTIVITY_FULL, 0.0, 1.0)
        for c, cv in enumerate(self.curves):
            cv.setData(x, data[:, c])
            self.meters[c].setOpts(x1=[float(level[c])])

    def _draw_view(self, st) -> None:
        new = self.engine.decisions_since(self.seq)
        live = self.view is not None and st.calib is None and not st.stale
        if new:
            self.seq = new[-1][0]
            if live:
                for _, d, confirmed in new[-5:]:
                    top = st.gestures[int(np.argmax(d.proba))] if st.gestures else None
                    self.view.push(d, confirmed or top)
        if self.view is not None and self.view_live and not live:
            self.view.clear_live()               # no current decision: do not leave the last one standing
        self.view_live = live
        self.p_view.lamp.set("off" if self.view is None else ("warn" if st.stale else "ok"))

    def _no_decision(self, text: str) -> None:
        self.big.set("–", MUTED)
        self.conf.set("", MUTED)
        self.conf_bar.setValue(0)
        self.sub.set(text, MUTED)

    def _draw_decision(self, st) -> None:
        m = self.engine.model
        needs = bool(m and m.needs_calibration)
        for w in (self.cal_btn, self.cal_bar, self.cal_note):
            w.setVisible(needs)
        if m is None:
            self.p_dec.lamp.set("off")
            self._no_decision("3번 칸에서 모델을 고르세요")
            self.truth.set("")
            self.bars.set([], None)
            self.model_info.set("")
            self.cal_note.setText("")
            self.pic.set_gesture("rest", MUTED, dim=True)
            return
        self.model_info.set(m.info, MUTED)
        if st.calib is not None:
            c = st.calib
            self.p_dec.lamp.set("busy")
            self.cal_btn.setText("보정 취소")
            self.cal_bar.setValue(int(1000 * c.progress))
            self.pic.set_gesture(c.gesture, gestures.colour(c.gesture))
            self.bars.set(list(st.gestures), None)
            self.big.set(c.text, TEXT)
            self.conf.set(f"보정 중 · {c.remaining:.1f}초", TEXT)
            self.conf_bar.setValue(0)
            self.sub.set("그림대로 따라 하세요", MUTED)
            self.truth.set("")
            self.cal_note.setText("")
            return
        self.cal_btn.setText("착용 보정 시작 (약 40초)")
        self.cal_bar.setValue(0)
        if m.needs_calibration:
            if st.calib_note:
                self.cal_note.setText(st.calib_note)
                self.cal_note.setStyleSheet(f"color: {MUTED if st.calibrated else LEVEL_COLOR['warn']};")
            elif not st.calibrated:
                self.cal_note.setText("보정 전: 학습 때 기준을 써서 판정이 부정확합니다")
                self.cal_note.setStyleSheet(f"color: {LEVEL_COLOR['warn']};")
        else:
            self.cal_note.setText("")
        stale = st.proba is None or st.stale
        self.bars.set(list(st.gestures), None if stale else st.proba)
        if stale:
            self.p_dec.lamp.set("warn")
            self._no_decision("판정을 기다리는 중" if st.health.ok else "암밴드 신호가 없어 판정할 수 없습니다")
            self.pic.set_gesture("rest", MUTED, dim=True)
            self._draw_truth(None)
            return
        key = st.confirmed or st.top
        pr = float(st.proba[st.gestures.index(key)])
        sure = pr >= UNSURE
        self.p_dec.lamp.set("ok" if sure else "warn")
        self.pic.set_gesture(key, ACCENT if sure else MUTED, dim=not sure)
        self.big.set(gestures.name(key) + ("" if sure else "?"), ACCENT_TEXT if sure else MUTED)
        self.conf.set(f"확신도 {100 * pr:.0f}%", TEXT if sure else MUTED)
        self.conf_bar.setValue(int(round(100 * pr)))
        if st.top != key:
            self.sub.set(f"지금 창은 {gestures.name(st.top)} 쪽", LEVEL_COLOR["warn"])
        elif sure:
            self.sub.set("✓ 안정적으로 인식됨", LEVEL_COLOR["ok"])
        else:
            self.sub.set("불확실", LEVEL_COLOR["warn"])
        self._draw_truth(gestures.name(key))

    def _draw_truth(self, shown: str | None) -> None:
        """When playing a recording: what the screen asked for at that moment."""
        pr = self.engine.replay_prompt()
        if pr is None:
            self.truth.set("")
            return
        kind, name, since = pr
        what = {"ready": "준비", "hold": "유지", "rest": "휴식"}.get(kind, kind)
        target = name if kind in ("hold", "ready") else "휴식"
        ok = kind in ("hold", "rest") and since > 0.5 and shown == target
        bad = kind in ("hold", "rest") and since > 0.8 and shown != target
        self.truth.set(f"녹화 당시 안내: {name} ({what} {since:.1f}초)",
                       LEVEL_COLOR["ok"] if ok else LEVEL_COLOR["error"] if bad else MUTED)

    def _draw_robot(self, st) -> None:
        robot = self.engine.robot_view()
        pos = robot.position
        self.hand.set_pulses(pos)
        self.led.set_rgb(robot.led)
        self.tone.setText(f"♪ {robot.tone} Hz" if robot.tone else "♪ –")
        self.axes.set(pos, st.predicted)
        if st.mode == "theater":
            self._draw_scenes(st)
        if st.mode == "theater" and not st.parked:
            if st.scene is None:
                level, text = "warn", f"준비 자세 · {gestures.name(st.confirmed)} 장면을 재생할 수 없음"
            else:
                level = "warn" if st.scene_missing else "ok"
                text = (f"장면 {gestures.name(st.scene)} · 카드 {st.scene_card[0]}/{st.scene_card[1]}"
                        + (" · 파일 없음(대체 동작)" if st.scene_missing else ""))
        elif st.parked:
            level, text = "warn", f"준비 자세로 대기 · {st.park_reason}"
        else:
            level, text = "ok", "손을 따라 하는 중"
        self.p_robot.lamp.set(level)
        self.robot_state.set(text, LEVEL_COLOR[level])

    def _draw_send(self):
        s = self.engine.robot_status()
        level = ROBOT_LEVEL[s.state]
        self.send_state.set(ROBOT_TEXT[s.state], LEVEL_COLOR[level] if level != "off" else MUTED)
        self.send_kv.set("주소", s.endpoint or "–")
        self.send_kv.set("전송", f"{s.sent}회" + (f" · 초당 {s.rate:.1f}회" if s.state == rs.CONNECTED else ""))
        self.send_kv.set("응답", "–" if s.rtt_ms is None else f"{s.rtt_ms:.0f} ms"
                         + ("" if s.rtt_avg_ms is None else f" (평균 {s.rtt_avg_ms:.0f})"))
        self.send_kv.set("실패", f"{s.failed}회", LEVEL_COLOR["error"] if s.failed else None)
        self.send_error.set(s.error if s.state == rs.RETRY else "", LEVEL_COLOR["error"])
        return s

    def _draw_scenes(self, st) -> None:
        """Per gesture: is its scene file loaded, missing (the stand-in plays) or damaged, and
        which one is playing now."""
        self.scene_head.setToolTip(os.path.join(self.engine.scene_folder, "action_NN.uhjson"))
        for info in self.engine.scene_report():
            lamp, name, pick = self.scene_rows[info.key]
            if info.state == "damaged":
                level, tip = "error", f"손상: {info.problem}"
            elif info.state == "missing":
                level, tip = "warn", f"{info.file} 파일이 없어 대체 동작을 재생합니다"
            else:
                level, tip = "ok", f"{info.file} · 카드 {info.cards}장"
            lamp.set(level)
            pick.setToolTip(tip)
            playing = info.key == st.scene
            name.setStyleSheet(f"color: {ACCENT}; font-weight: bold;" if playing else "")
            name.setText(("▸ " if playing else "") + gestures.name(info.key))

    def closeEvent(self, ev) -> None:
        self.timer.stop()
        self.engine.close()
        self.hand.shutdown()
        super().closeEvent(ev)
