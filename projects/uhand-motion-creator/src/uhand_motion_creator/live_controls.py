"""Live device controls. All widget and pending-command state belongs to the GUI thread."""
from collections import OrderedDict
from time import monotonic

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QGridLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QSlider, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from .led_editor import LedEditor
from .motion import Buzzer, Motion, PULSE_LIMITS
from .pulse_spin import PulseSpinBox


class LiveControls(QWidget):
    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.setStyleSheet("""
            QSpinBox:disabled { color: #78869b; background: #f3f5f9; }
            QSlider::sub-page:horizontal:disabled { background: #c3ccda; }
            QSlider::handle:horizontal:disabled { background: #f1f3f7; border: 1px solid #a9b5c5; }
        """)
        self.active = False
        self.hand_state = "off"
        self.playing = False
        self.tone_revision = 0
        self.pending = OrderedDict()
        self.inflight = None
        self.generation = None
        self.was_connected = False
        self.send_timer = QTimer(self)
        self.send_timer.setSingleShot(True)
        self.send_timer.timeout.connect(self.dispatch)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self.mute)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        header = QHBoxLayout()
        self.target = QLabel()
        self.target.setWordWrap(True)
        header.addWidget(self.target, 1)
        connect = QPushButton("서버 연결·테스트")
        connect.clicked.connect(editor.show_server_panel)
        header.addWidget(connect)
        layout.addLayout(header)
        self.pages = QTabWidget()
        layout.addWidget(self.pages)
        hand = QWidget()
        grid = QGridLayout(hand)
        grid.setContentsMargins(4, 4, 4, 4)
        grid.setVerticalSpacing(3)
        self.hand_button = QPushButton("실시간 손 제어 시작")
        self.hand_button.clicked.connect(self.toggle_hand)
        grid.addWidget(self.hand_button, 0, 0, 1, 3)
        self.axes = []
        self.sliders = []
        for index, (name, limits) in enumerate(zip(("엄지", "검지", "중지", "약지", "소지", "손목"), PULSE_LIMITS)):
            spin = PulseSpinBox(name, limits)
            spin.setValue(1500)
            spin.setKeyboardTracking(False)
            spin.setAccessibleName(name + " 펄스")
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setAccessibleName(name + " 실시간 제어")
            slider.setRange(*limits)
            slider.setValue(1500)
            self.axes.append(spin)
            self.sliders.append(slider)
            slider.valueChanged.connect(spin.setValue)
            spin.valueChanged.connect(slider.setValue)
            spin.valueChanged.connect(self.hand_changed)
            spin.inputRejected.connect(self.message)
            grid.addWidget(QLabel(name), index + 1, 0)
            grid.addWidget(spin, index + 1, 1)
            grid.addWidget(slider, index + 1, 2)
        grid.setColumnStretch(2, 1)
        grid.setRowStretch(len(self.axes) + 1, 1)
        self.pages.addTab(hand, "손 자세")

        buzzer = QWidget()
        controls = QGridLayout(buzzer)
        self.frequency = QSpinBox()
        self.frequency.setRange(0, 10000)
        self.frequency.setValue(1000)
        self.frequency.setKeyboardTracking(False)
        self.duration = QSpinBox()
        self.duration.setRange(100, 20000)
        self.duration.setValue(1000)
        self.duration.setKeyboardTracking(False)
        controls.addWidget(QLabel("주파수 (Hz)"), 0, 0)
        controls.addWidget(self.frequency, 0, 1)
        controls.addWidget(QLabel("재생 시간 (ms)"), 1, 0)
        controls.addWidget(self.duration, 1, 1)
        self.continuous = QCheckBox("연속 재생")
        controls.addWidget(self.continuous, 2, 0, 1, 2)
        self.play = QPushButton("재생")
        self.off = QPushButton("부저 끄기")
        controls.addWidget(self.play, 3, 0)
        controls.addWidget(self.off, 3, 1)
        controls.setRowStretch(4, 1)
        self.play.clicked.connect(self.play_tone)
        self.off.clicked.connect(self.mute)
        self.continuous.toggled.connect(self.buzzer_mode)
        self.frequency.valueChanged.connect(self.change_frequency)
        self.pages.addTab(buzzer, "부저")
        self.led = LedEditor()
        for slider in self.led.findChildren(QSlider):
            slider.setStyleSheet(slider.styleSheet() + "QSlider::sub-page:horizontal:disabled {background:#c3ccda;}")
        self.led.changed.connect(self.led_changed)
        self.pages.addTab(self.led, "삼색 LED")
        self.feedback = QLabel()
        self.feedback.setWordWrap(True)
        self.feedback.setObjectName("notice")
        layout.addWidget(self.feedback)

    def message(self, text):
        self.feedback.setText(text)

    def target_name(self):
        address = self.editor.remote_endpoint
        host = address.rpartition(":")[0]
        if host in ("localhost", "127.0.0.1", "::1"):
            name = "가상 로봇손"
        elif host == "192.168.61.1":
            name = "실물 로봇손"
        else:
            name = "사용자 지정 서버"
        return f"{name} · {address}"

    def available(self):
        return self.active and self.editor.remote.connected and not self.editor.remote_disconnect_pending

    def refresh(self):
        connected = self.editor.remote.connected
        generation = self.editor.remote.generation
        if not connected or self.generation != generation:
            if self.was_connected and self.active and not connected:
                self.message("연결이 끊겨 실시간 제어가 중지되었습니다.")
            self.reset_session()
        if connected and not self.was_connected and self.active:
            self.message("연결되었습니다. 제어할 장치를 선택하세요.")
        self.generation = generation
        self.was_connected = connected
        self.target.setText(self.target_name() if connected else "서버에 연결하면 조작할 수 있습니다.")
        enabled = self.available()
        # Disable the contents only. The user can browse all three tabs offline.
        self.pages.widget(0).setEnabled(enabled)
        self.pages.widget(1).setEnabled(enabled)
        self.led.setEnabled(enabled)
        self.hand_button.setEnabled(self.hand_state != "sync")
        self.hand_button.setText({"off": "실시간 손 제어 시작", "sync": "자세 맞추는 중…", "on": "손 제어 종료"}[self.hand_state])
        hand_on = self.hand_state == "on" and enabled
        for field in self.axes + self.sliders:
            field.setEnabled(hand_on)
        if self.active:
            self.editor.viewport.previewing = not hand_on
        self.duration.setEnabled(not self.continuous.isChecked())

    def enter(self):
        self.active = True
        self.original_pose = tuple(self.editor.viewport.pulses)
        for spin, value in zip(self.axes, self.original_pose):
            spin.setValue(value)
        self.editor.viewport.drag = None
        self.message("손 제어 시작 전에는 화면 자세를 전송하지 않습니다.")
        self.refresh()

    def leave(self):
        self.active = False
        self.hand_state = "off"
        needs_mute = self.playing or "tone" in self.pending or (self.inflight and self.inflight[0] == "tone")
        self.pending.clear()
        self.inflight = None
        if needs_mute:
            self.mute()
        self.editor.viewport.drag = None
        self.editor.viewport.previewing = False
        self.editor.viewport.set_pulses(self.original_pose)

    def reset_session(self):
        self.send_timer.stop()
        self.timer.stop()
        self.pending.clear()
        self.inflight = None
        self.playing = False
        self.hand_state = "off"

    def confirm_hand(self):
        box = QMessageBox(self)
        box.setWindowTitle("실시간 손 제어 시작")
        box.setText(f"{self.target_name()}\n손가락 5개와 손목이 현재 3D 자세로 이동합니다. 손 주변을 비운 뒤 시작하세요.")
        start = box.addButton("자세를 맞추고 시작", QMessageBox.ButtonRole.AcceptRole)
        cancel = box.addButton("취소", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel)
        box.setEscapeButton(cancel)
        box.exec()
        return box.clickedButton() is start

    def toggle_hand(self):
        if not self.available():
            return
        if self.hand_state == "on":
            self.pending.pop("hand", None)
            self.hand_state = "off"
            self.message("손 제어 종료 · 마지막 목표 자세를 유지합니다.")
        elif self.hand_state == "off":
            session = self.editor.remote.generation
            if not self.confirm_hand() or not self.available() or session != self.editor.remote.generation:
                return
            self.hand_state = "sync"
            self.queue("sync", Motion(tuple(s.value() for s in self.axes), 500))
        self.refresh()

    def hand_changed(self):
        if self.available() and self.hand_state == "on":
            pulses = tuple(s.value() for s in self.axes)
            self.editor.viewport.set_pulses(pulses)
            self.queue("hand", Motion(pulses, 100))

    def buzzer_mode(self):
        self.duration.setEnabled(not self.continuous.isChecked())
        if self.playing:
            self.mute()

    def change_frequency(self):
        if self.playing and self.continuous.isChecked():
            self.play_tone()

    def play_tone(self):
        if not self.available():
            return
        self.timer.stop()
        self.tone_revision += 1
        self.playing = True
        duration = None if self.continuous.isChecked() else self.duration.value()
        self.queue("tone", Buzzer(self.frequency.value(), 100, continuous=True), duration)

    def mute(self):
        self.timer.stop()
        self.tone_revision += 1
        self.playing = False
        if self.editor.remote.connected:
            self.queue("tone", Buzzer(0, 100, continuous=True))
            self.pending.move_to_end("tone", last=False)

    def led_changed(self):
        if self.available():
            self.queue("led", self.led.card())

    def queue(self, key, card, duration=None):
        self.pending[key] = (card, duration, self.tone_revision)
        # Coalesce slider signals from the current UI event, but wake immediately
        # for a free command slot (especially for the local buzzer deadline).
        if not self.editor.remote.busy and not self.send_timer.isActive():
            self.send_timer.start(0)

    def dispatch(self):
        session = self.editor.remote
        if not self.pending or session.busy or not session.connected or self.editor.remote_disconnect_pending:
            return
        key = next(iter(self.pending))
        card, duration, revision = self.pending[key]
        # A servo move occupies the server until its duration expires. Let a
        # scheduled mute go first when this move would straddle its deadline.
        if isinstance(card, Motion) and self.timer.isActive() and self.timer.remainingTime() <= card.running_time:
            return
        del self.pending[key]
        self.inflight = (key, card, duration, revision)
        session.submit("live", cards=((-1, card),))

    def completed(self, event):
        sent = self.inflight
        self.inflight = None
        if not event["connected"] or event["errors"]:
            if event["errors"]:
                message = "실시간 명령 실패 · " + " / ".join(event["errors"])
                self.message(message)
                self.editor.remote_message(message)
                if not self.active:
                    self.editor.notice.setText(message)
            should_mute = (self.playing or "tone" in self.pending) and event["connected"] and not (
                sent and isinstance(sent[1], Buzzer) and sent[1].frequency == 0)
            self.reset_session()
            if should_mute:
                self.mute()
            self.refresh()
            return
        if not sent:
            return
        key, card, duration, revision = sent
        if key == "sync" and self.active and self.hand_state == "sync":
            self.hand_state = "on"
            self.message("손 제어 중 · 슬라이더 또는 3D 손을 움직이세요.")
        elif key == "tone" and revision == self.tone_revision:
            self.message(f"부저 {card.frequency} Hz" if card.frequency else "부저 무음")
            if duration is not None and self.playing:
                elapsed = (monotonic() - event["finished_at"]) * 1000
                self.timer.start(max(0, round(duration - elapsed)))
        self.refresh()
