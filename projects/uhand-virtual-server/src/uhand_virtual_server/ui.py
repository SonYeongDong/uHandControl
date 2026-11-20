"""Light Studio interface. Widgets display server state; they do not send output commands."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QRadialGradient
from PySide6.QtWidgets import (
    QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QMainWindow,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
    QHeaderView, QAbstractItemView, QLineEdit, QSpinBox,
)

from uhand_server_lifecycle import led_output
from .viewport import HandViewport
from .protocol import PULSE_LIMITS
from uhand_about import add_about_action
from . import __version__

LOGO_COLOR = "#cc3344"

STYLE = """
QMainWindow, QWidget#root { background: #f3f6fc; color: #182a45; }
QWidget { font-family: 'Segoe UI', 'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif; font-size: 13px; color: #182a45; }
QFrame#card { background: white; border: 1px solid #dce4f1; border-radius: 12px; }
QLabel { background: transparent; border: none; }
QLabel#title { font-size: 23px; font-weight: 700; color: #122644; }
QLabel#section { font-size: 15px; font-weight: 650; }
QLabel#muted { color: #718098; font-size: 12px; }
QLabel#badge { color: #2459d3; background: #edf3ff; border-radius: 7px; padding: 6px 10px; }
QFrame#errorBanner { background: #fff0ee; border-radius: 8px; }
QLabel#error { color: #a13838; }
QPushButton#dismissError { background: transparent; color: #913737; border: 1px solid transparent; padding: 0; font-size: 18px; }
QPushButton#dismissError:hover { background: #f9dcd8; }
QPushButton#dismissError:focus { border-color: #a13838; }
QPushButton#dismissError:pressed { background: #a13838; color: white; }
QPushButton { background: #fff; border: 1px solid #d7e1ef; border-radius: 7px; padding: 6px 12px; min-height: 24px; }
QPushButton:hover { background: #eaf1ff; border-color: #98b5ed; }
QPushButton:pressed:enabled {background:#3867bd;border-color:#254c92;color:white;}
QSpinBox,QLineEdit {background:#f8faff;border:1px solid #d7e1ef;border-radius:5px;padding:5px;min-height:20px;}
QSpinBox:focus,QLineEdit:focus {border-color:#2962ef;}
QTableWidget { background: white; border: none; gridline-color: #e8edf5; selection-background-color: #edf3ff; selection-color: #182a45; }
QTableWidget::item { padding: 4px; border: none; }
QTableWidget::item:selected { background: #edf3ff; color: #182a45; }
QHeaderView::section { background: #f3f6fc; color: #687992; border: none; padding: 7px; font-size: 11px; }
QScrollBar:vertical { background: #f6f8fc; width: 8px; }
QScrollBar::handle:vertical { background: #cbd6e7; border-radius: 4px; min-height: 22px; }
"""


def label(text="", name=None, *, minimum_height=18):
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setMinimumHeight(minimum_height)
    if name:
        widget.setObjectName(name)
    return widget


def card(title, action=None):
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(14, 12, 14, 12)
    layout.setSpacing(8)
    heading = QHBoxLayout()
    heading.addWidget(label(title, "section"))
    if action is not None:
        heading.addStretch()
        heading.addWidget(action)
    layout.addLayout(heading)
    return frame, layout


class Led(QWidget):
    def __init__(self, number):
        super().__init__()
        self.number = number
        self.rgb = None
        self.setMinimumWidth(90)
        self.setFixedHeight(76)

    def set_rgb(self, rgb):
        if rgb != self.rgb:
            self.rgb = rgb
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center_x, center_y = self.width()/2, 26
        rgb = self.rgb or [False, False, False]
        lit = any(rgb)
        color = QColor(*rgb) if lit else QColor("#9caac0")
        painter.setPen(QColor("#dce4f1"))
        painter.setBrush(QColor("#f4f7fc"))
        painter.drawEllipse(int(center_x-24), int(center_y-24), 48, 48)
        gradient = QRadialGradient(center_x-6, center_y-8, 37)
        gradient.setColorAt(0, color.lighter(145))
        gradient.setColorAt(1, color.darker(135))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawEllipse(int(center_x-17), int(center_y-17), 34, 34)
        painter.setPen(QColor("#687992"))
        painter.drawText(0, 53, self.width(), 20, Qt.AlignmentFlag.AlignCenter, f"LED {self.number}")


class MainWindow(QMainWindow):
    def __init__(self, server):
        super().__init__()
        self.server = server
        self.closing = False
        self.last_event = -1
        self.displayed_error_id = 0
        self.dismissed_error_id = 0
        self.setWindowTitle("uHandVirtualServer")
        self.setMinimumSize(740, 740)
        available = QApplication.primaryScreen().availableGeometry()
        scale = max(1,min(100,(available.width()-50)//16,(available.height()-60)//9))
        self.resize(16*scale,9*scale)
        self.setStyleSheet(STYLE)
        add_about_action(self, "uHandVirtualServer", "로봇손 가상 제어 환경", __version__, LOGO_COLOR)
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(20, 12, 20, 10)
        layout.setSpacing(10)
        header = QHBoxLayout()
        header.setSpacing(14)
        logo = label("U")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setFixedSize(44, 44)
        logo.setObjectName("appLogo")
        logo.setStyleSheet(f"background:{LOGO_COLOR};color:white;border-radius:12px;font-size:27px;font-weight:700;")
        header.addWidget(logo)
        titles = QVBoxLayout()
        titles.setSpacing(1)
        titles.addWidget(label("uHandVirtualServer", "title", minimum_height=0))
        self.subtitle = label("로봇손 가상 제어 환경", "muted", minimum_height=0)
        titles.addWidget(self.subtitle)
        header.addLayout(titles)
        header.setAlignment(titles, Qt.AlignmentFlag.AlignVCenter)
        header.addStretch()
        layout.addLayout(header)
        self.error_banner = QFrame()
        self.error_banner.setObjectName("errorBanner")
        error_row = QHBoxLayout(self.error_banner)
        error_row.setContentsMargins(10, 4, 6, 4)
        self.error = label("", "error")
        self.error.setWordWrap(True)
        error_row.addWidget(self.error, 1)
        self.dismiss_error_button = QPushButton("×")
        self.dismiss_error_button.setObjectName("dismissError")
        self.dismiss_error_button.setAccessibleName("오류 알림 닫기")
        self.dismiss_error_button.setToolTip("오류 알림 닫기")
        self.dismiss_error_button.setFixedSize(28, 28)
        self.dismiss_error_button.clicked.connect(self.dismiss_error)
        error_row.addWidget(self.dismiss_error_button)
        self.error_banner.hide()
        layout.addWidget(self.error_banner)

        main = QHBoxLayout()
        main.setSpacing(12)
        viewport_card, viewport_layout = card("3D 로봇손")
        tools = QHBoxLayout()
        camera_hint = label("오른쪽 드래그로 회전 · 휠로 확대", "muted")
        camera_hint.setWordWrap(True)
        tools.addWidget(camera_hint, 1)
        self.viewport = HandViewport()
        for text, action in (
            ("기본 보기", self.viewport.home), ("정면", self.viewport.front),
            ("＋", lambda: self.viewport.zoom(0.85)), ("−", lambda: self.viewport.zoom(1.15)),
        ):
            button = QPushButton(text)
            button.clicked.connect(action)
            button.setAccessibleName(text)
            tools.addWidget(button)
        viewport_layout.addLayout(tools)
        viewport_layout.addWidget(self.viewport, 1)
        self.motion_label = label("표시 기준 자세 · 완료 기록 없음", "muted")
        viewport_layout.addWidget(self.motion_label)
        pulse_layout = QHBoxLayout()
        self.pulse_labels = []
        for name,limits in zip(("Finger1", "Finger2", "Finger3", "Finger4", "Finger5", "Wrist"),PULSE_LIMITS):
            widget = label(f"{name}\n1500")
            widget.setToolTip(f"{name}: {limits[0]}~{limits[1]}")
            widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
            widget.setStyleSheet("background:#f3f6fc;border-radius:6px;padding:5px;font-size:11px;")
            pulse_layout.addWidget(widget)
            self.pulse_labels.append((name, widget))
        viewport_layout.addLayout(pulse_layout)
        main.addWidget(viewport_card, 7)

        side = QVBoxLayout()
        self.side_layout = side
        side.setSpacing(layout.spacing())
        side.setContentsMargins(0,0,0,0)
        self.listen_button = QPushButton("전원 끄기")
        self.listen_button.clicked.connect(self.toggle_listener)
        connection_card, connection_layout = card("연결 상태", self.listen_button)
        self.connection = label("●  연결 대기")
        self.connection.setStyleSheet("color:#2459d3;background:#edf3ff;padding:9px;border-radius:7px;font-weight:600;")
        self.connection.setFixedHeight(32)
        self.connection_layout = connection_layout
        connection_layout.addWidget(self.connection)
        endpoint_row = QHBoxLayout()
        self.host_input = QLineEdit(server.host)
        self.host_input.setAccessibleName("서버 IP")
        self.host_input.setToolTip("이 PC의 수신 IPv4 또는 IPv6 주소")
        self.port_input = QSpinBox()
        self.port_input.setAccessibleName("포트")
        self.port_input.setRange(1, 65535)
        self.port_input.setValue(server.port or 5000)
        endpoint_row.addWidget(label("IP"))
        endpoint_row.addWidget(self.host_input, 1)
        endpoint_row.addWidget(label("포트"))
        endpoint_row.addWidget(self.port_input)
        connection_layout.addLayout(endpoint_row)
        side.addWidget(connection_card, connection_card.sizeHint().height())

        buzzer_card, buzzer_layout = card("가상 부저")
        self.frequency = label("— Hz")
        self.frequency.setStyleSheet("font-size:27px;font-weight:650;")
        self.frequency.setMinimumHeight(36)
        buzzer_row = QHBoxLayout()
        buzzer_row.addWidget(self.frequency)
        buzzer_row.addStretch()
        self.buzzer_state = label("대기", "badge")
        self.buzzer_state.setFixedHeight(30)
        buzzer_row.addWidget(self.buzzer_state)
        buzzer_layout.addLayout(buzzer_row)
        self.buzzer_time = label("재생 기록 없음", "muted")
        self.buzzer_layout = buzzer_layout
        buzzer_layout.addWidget(self.buzzer_time)
        side.addWidget(buzzer_card, buzzer_card.sizeHint().height())

        led_card, led_layout = card("RGB LED")
        self.led_caption = label("LED 1 · 2 동시 출력", "muted")
        self.led_layout = led_layout
        led_layout.addWidget(self.led_caption)
        lamps = QHBoxLayout()
        self.leds = [Led(1), Led(2)]
        for lamp in self.leds:
            lamps.addWidget(lamp)
        led_layout.addLayout(lamps)
        details = QFrame()
        details.setObjectName("ledDetails")
        details.setStyleSheet("QFrame#ledDetails {background:#f3f6fc;border-radius:6px;}")
        grid = QGridLayout(details)
        grid.setContentsMargins(6, 4, 6, 4)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(1)
        self.led_source = label()
        self.led_brightness = label()
        self.led_output = label()
        for column, (title, field) in enumerate((
            ("설정 RGB", self.led_source), ("전체 밝기", self.led_brightness), ("출력 RGB", self.led_output)
        )):
            heading = label(title, "muted")
            heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
            field.setAlignment(Qt.AlignmentFlag.AlignCenter)
            field.setAccessibleName(title)
            grid.addWidget(heading, 0, column)
            grid.addWidget(field, 1, column)
        grid.setColumnStretch(0, 2)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 2)
        led_layout.addWidget(details)
        side.addWidget(led_card, led_card.sizeHint().height())
        side_widget = QWidget()
        side_widget.setLayout(side)
        side_widget.setMinimumWidth(310)
        side_widget.setMaximumWidth(430)
        main.addWidget(side_widget, 3)
        layout.addLayout(main, 1)

        bottom = QHBoxLayout()
        bottom.setSpacing(12)
        status_card, status_layout = card("마지막 적용·완료 상태")
        self.status_heading = status_card.findChild(QLabel, "section")
        self.status_table = QTableWidget(6, 2)
        self.status_table.setHorizontalHeaderLabels(["항목", "값"])
        self.status_table.verticalHeader().hide()
        self.status_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.status_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.status_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for row, key in enumerate(("TargetPulses", "PulseRunningTime", "BuzzerFrequency", "BuzzerRunningTime", "BuzzerContinuous", "LED")):
            self.status_table.setItem(row, 0, QTableWidgetItem(key))
            self.status_table.setItem(row, 1, QTableWidgetItem("기록 없음"))
            self.status_table.setRowHeight(row, 24)
        self.status_table.ensurePolished()
        self.status_table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.status_table.horizontalHeader().geometriesChanged.connect(self.fit_status_table)
        self.fit_status_table()
        status_layout.addWidget(self.status_table)
        bottom.addWidget(status_card, 6)
        self.clear_log_button = QPushButton("전체 삭제")
        self.clear_log_button.setAccessibleName("이벤트 로그 전체 삭제")
        self.clear_log_button.clicked.connect(self.clear_log)
        log_card, log_layout = card("이벤트 로그", self.clear_log_button)
        self.log_table = QTableWidget(0, 2)
        self.log_table.setObjectName("eventLog")
        self.log_table.setHorizontalHeaderLabels(["시각", "이벤트"])
        self.log_table.verticalHeader().hide()
        self.log_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        # Timestamp width is constant; avoid rescanning 200 rows on each item change.
        self.log_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.log_table.setColumnWidth(0, self.log_table.fontMetrics().horizontalAdvance("00:00:00")+28)
        self.log_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.log_table.setMinimumHeight(72)
        self.log_table.setMaximumHeight(160)
        log_layout.addWidget(self.log_table)
        bottom.addWidget(log_card, 4)
        layout.addLayout(bottom)
        footer = QHBoxLayout()
        self.version_label = label(f"v{__version__}", "muted", minimum_height=0)
        footer.addWidget(self.version_label)
        footer.addStretch()
        layout.addLayout(footer)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(33)
        self.refresh()

    def fit_status_table(self):
        table = self.status_table
        height = (table.horizontalHeader().sizeHint().height()
                  + table.verticalHeader().length() + 2 * table.frameWidth())
        if table.minimumHeight() != height or table.maximumHeight() != height:
            table.setFixedHeight(height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.centralWidget() is None:
            return
        self.version_label.setMinimumHeight(self.subtitle.sizeHint().height())
        narrow = event.size().width() < 1050
        self.viewport.setMinimumWidth(280 if narrow else 420)
        short = event.size().height() < 920
        tight = event.size().height() < 800
        compact = short or narrow
        self.viewport.setMinimumHeight(165 if short else 230)
        if getattr(self, "_short_cards", False) != short:
            self._short_cards = short
            for column, field, index in (
                (self.connection_layout, self.connection, 1),
                (self.buzzer_layout, self.buzzer_time, 2),
                (self.led_layout, self.led_caption, 1),
            ):
                heading = column.itemAt(0).layout()
                if short:
                    column.removeWidget(field)
                    heading.insertWidget(1, field, 0, Qt.AlignmentFlag.AlignRight)
                else:
                    heading.removeWidget(field)
                    column.insertWidget(index, field)
        # Match MotionCreator's outer margins and row spacing in split view.
        compact_window = event.size().width() < 1200 or event.size().height() < 890
        density = (narrow, short, tight, compact_window)
        if getattr(self, "_card_density", None) == density:
            return
        self._card_density = density
        root_layout = self.centralWidget().layout()
        margins = (12, 6, 12, 6) if compact_window else (20, 12, 20, 10)
        root_layout.setContentsMargins(*margins)
        root_layout.setSpacing(6 if compact_window else 10)
        self.side_layout.setSpacing(6 if tight else 10)
        vertical_padding = 6 if tight else (8 if compact else 12)
        for frame in self.findChildren(QFrame, "card"):
            frame.layout().setContentsMargins(14, vertical_padding, 14, vertical_padding)
            frame.layout().setSpacing(6 if compact else 8)
            frame.layout().invalidate()
            frame.updateGeometry()
        self.side_layout.invalidate()
        self.side_layout.parentWidget().updateGeometry()
        root_layout.invalidate()
        root_layout.activate()

    def toggle_listener(self):
        try:
            if self.server.listening:
                self.server.stop_listening()
            else:
                self.server.start(self.host_input.text().strip(), self.port_input.value(), background=True)
                self.host_input.setText(self.server.host)
        except (OSError, ValueError, RuntimeError) as exc:
            self.server.log(f"가상 전원 설정 오류 · {exc}", "error")
        self.refresh()

    def dismiss_error(self):
        # A newer error may already be waiting for the next refresh.
        self.dismissed_error_id = self.displayed_error_id
        self.error_banner.hide()

    def clear_log(self):
        self.last_event = self.server.clear_events()
        self.log_table.setRowCount(0)
        self.refresh()

    def refresh(self):
        state = self.server.snapshot()
        status = state["status"]
        phases = {"startup": "서버 준비 중", "connect": "연결 준비 중", "disconnect": "연결 해제 중"}
        powered_off = state.get("powered_off", False)
        if self.closing:
            connection_text = "종료 중"
        elif powered_off:
            connection_text = "전원 꺼짐"
        elif state.get("init_error"):
            connection_text = "초기화 오류"
        elif state.get("phase"):
            connection_text = phases[state["phase"]]
        elif state["connected"]:
            connection_text = "Client 연결됨"
        else:
            connection_text = "연결 대기" if state["listening"] else "전원 꺼짐"
        self.connection.setText(f"●  {connection_text}")
        editable = not state["listening"] and not self.closing
        self.host_input.setEnabled(editable)
        self.port_input.setEnabled(editable)
        self.listen_button.setText("전원 끄기" if state["listening"] else "전원 켜기")
        self.listen_button.setEnabled(not self.closing)
        self.listen_button.setToolTip("가상 로봇손의 동작을 중단하고 Client 연결을 즉시 끊습니다."
                                     if state["listening"] else "가상 로봇손을 켜고 기본 자세로 복귀한 뒤 준비음을 재생합니다.")
        self.clear_log_button.setEnabled(bool(state["events"]))
        self.viewport.set_pulses(state["pulses"])
        for (name, widget), value in zip(self.pulse_labels, state["pulses"]):
            widget.setText(f"{name}\n{round(value)}")
        if powered_off:
            self.motion_label.setText("전원 꺼짐 · 중지 시점의 자세")
        elif state["active"] == "SetuHandPulse":
            self.motion_label.setText("이동 중 · 표시값은 현재 가상 자세이며 완료 기록과 구분됩니다")
        else:
            self.motion_label.setText("마지막 목표 자세" if status["TargetPulses"] else "표시 기준 자세 · 완료 기록 없음")
        if powered_off:
            self.frequency.setText("0 Hz")
            self.buzzer_time.setText("전원 꺼짐")
            self.buzzer_state.setText("꺼짐")
        else:
            params = state["params"] if state["active"] == "SetuHandBuzzer" else state.get("buzzer_output")
            freq = params["Frequency"] if params else status["BuzzerFrequency"]
            duration = params["RunningTime"] if params else status["BuzzerRunningTime"]
            self.frequency.setText(f"{freq} Hz" if freq is not None else "— Hz")
            continuous = params.get("Continuous", False) if params else False
            self.buzzer_time.setText("다음 부저 명령까지 유지" if continuous else (f"지정 시간  {duration} ms" if duration is not None else "재생 기록 없음"))
            self.buzzer_state.setText(("무음 유지" if freq == 0 else "연속 재생") if continuous else (("무음 대기" if freq == 0 else "재생 중") if params else ("완료" if freq is not None else "대기")))
        source = None if powered_off else status["LED"]
        brightness = None if powered_off else status["LEDBrightness"]
        output = [0, 0, 0] if powered_off else None
        if source is not None:
            output = led_output(source, brightness)
        for lamp in self.leds:
            lamp.set_rgb(output)
        self.led_source.setText("—" if source is None else ", ".join(map(str, source)))
        self.led_brightness.setText("—" if brightness is None else f"{brightness}%")
        self.led_output.setText("—" if output is None else ", ".join(map(str, output)))
        self.status_heading.setText("전원 차단 전 마지막 완료 상태" if powered_off else "마지막 적용·완료 상태")
        for row in range(self.status_table.rowCount()):
            key = self.status_table.item(row, 0).text()
            value = status[key]
            text = "기록 없음" if value is None else str(value)
            if value is not None and key.endswith("RunningTime"):
                text += " ms"
            elif value is not None and key == "BuzzerFrequency":
                text += " Hz"
            if key == "LED" and value is not None:
                text += f" · 밝기 {status['LEDBrightness']}%"
            self.status_table.item(row, 1).setText(text)
        self.update_log(state["events"])
        self.displayed_error_id = state["last_error_id"]
        if self.error.text() != state["last_error"]:
            self.error.setText(state["last_error"])
        self.error_banner.setVisible(bool(state["last_error"]) and self.displayed_error_id != self.dismissed_error_id)
        if self.closing and not state["busy"]:
            self.close()

    def update_log(self, events):
        """Insert only unseen events; retain at most the server's 200-event window."""
        if not events or events[-1][0] == self.last_event:return
        new_events = [event for event in events if event[0] > self.last_event]
        if not new_events:return
        self.log_table.setUpdatesEnabled(False)
        try:
            # Trim stale rows before inserting, even if the GUI missed a full window.
            remaining = len(events)-len(new_events)
            while self.log_table.rowCount() > remaining:
                self.log_table.removeRow(self.log_table.rowCount()-1)
            for _, stamp, level, text in new_events:
                self.log_table.insertRow(0)
                self.log_table.setItem(0, 0, QTableWidgetItem(stamp))
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                if level == "error":item.setForeground(QColor("#b64646"))
                self.log_table.setItem(0, 1, item)
                self.log_table.setRowHeight(0, 27)
            self.last_event = events[-1][0]
        finally:
            self.log_table.setUpdatesEnabled(True)

    def closeEvent(self, event):
        if self.server.snapshot()["busy"]:
            self.closing = True
            self.server.drain()
            self.connection.setText("현재 동작 완료 후 종료합니다")
            event.ignore()
            return
        self.timer.stop()
        self.server.shutdown()
        self.viewport.shutdown()
        event.accept()
