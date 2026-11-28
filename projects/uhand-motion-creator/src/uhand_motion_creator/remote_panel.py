"""Modeless server connection and test controls."""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QSpinBox, QComboBox, QCheckBox, QPlainTextEdit,
)
from PySide6.QtCore import Qt
from .style import STYLE


def text(value):
    label = QLabel(value)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


class ServerPanel(QDialog):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor
        self.setWindowTitle("서버 연결 · 원격 테스트")
        self.setStyleSheet(STYLE)
        self.resize(660, 650)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        title = text("서버 연결 · 원격 테스트");title.setObjectName("title")
        layout.addWidget(title)
        layout.addWidget(text("연결만으로 장치가 움직이지 않습니다. 실행 버튼을 눌러 명령을 전송하세요."))
        row = QHBoxLayout()
        self.preset = QComboBox()
        self.preset.addItems(("가상 서버 · 이 PC", "실제 로봇손 · Ethernet", "주소 직접 입력"))
        row.addWidget(self.preset)
        self.ip = QLineEdit("127.0.0.1");self.ip.setAccessibleName("서버 IP")
        row.addWidget(self.ip, 1)
        self.port = QSpinBox();self.port.setRange(1, 65535);self.port.setValue(5000)
        self.port.setAccessibleName("서버 Port");row.addWidget(self.port)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.connect_button = QPushButton("연결");self.connect_button.setObjectName("primary")
        self.disconnect_button = QPushButton("연결 해제")
        self.status_button = QPushButton("상태 조회")
        for widget in (self.connect_button, self.disconnect_button, self.status_button):row.addWidget(widget)
        layout.addLayout(row)
        self.connection = text("연결 안 됨");self.connection.setObjectName("section");layout.addWidget(self.connection)
        self.direct = QCheckBox("직접 제어 모드 · 현재 파라미터를 서버에 적용")
        layout.addWidget(self.direct)
        row = QHBoxLayout()
        self.apply_button = QPushButton("현재 파라미터 서버에 적용")
        self.mute_button = QPushButton("서버 소리 끄기")
        self.led_off_button = QPushButton("서버 LED 끄기")
        self.led_off_button.setToolTip("연결된 서버의 LED 1·2를 모두 끕니다.")
        row.addWidget(self.apply_button);row.addWidget(self.mute_button);row.addWidget(self.led_off_button);layout.addLayout(row)
        layout.addWidget(text("직접 제어는 카드를 만들지 않습니다. 확인한 값은 메인 창에서 동작 추가로 저장하세요."))
        row = QHBoxLayout()
        heading = text("저장된 카드 · 서버 실행");heading.setObjectName("section");heading.setWordWrap(False);row.addWidget(heading, 1)
        self.repeat = QCheckBox("반복 재생")
        self.repeat.setToolTip("선택한 실행 범위를 정지 요청까지 반복합니다. 로컬 미리보기의 반복 설정과 별개입니다.")
        row.addWidget(self.repeat);layout.addLayout(row)
        row = QHBoxLayout()
        self.selected_button = QPushButton("선택 카드 실행")
        self.all_button = QPushButton("처음부터 실행")
        self.current_button = QPushButton("현재 카드부터 실행")
        for widget in (self.selected_button, self.all_button, self.current_button):row.addWidget(widget)
        layout.addLayout(row)
        self.stop_button = QPushButton("■ 실행 정지 요청");layout.addWidget(self.stop_button)
        layout.addWidget(text("정지는 현재 명령 완료 후 다음 카드를 실행하지 않습니다. 테스트 종료·중단 시 부저를 끕니다."))
        self.progress = text("대기");self.progress.setObjectName("notice");layout.addWidget(self.progress)
        layout.addWidget(text("서버의 마지막 완료 / 적용 상태 · 센서 측정값 아님"))
        self.status = QPlainTextEdit();self.status.setReadOnly(True);self.status.setMinimumHeight(130)
        self.status.setPlainText("아직 조회한 상태가 없습니다.");layout.addWidget(self.status, 1)
        row = QHBoxLayout();row.addWidget(text("이 창을 닫아도 연결은 유지됩니다."));row.addStretch()
        close = QPushButton("닫기");close.clicked.connect(self.close);row.addWidget(close);layout.addLayout(row)
        self.preset.currentIndexChanged.connect(self._preset)
        self.connect_button.clicked.connect(editor.connect_remote)
        self.disconnect_button.clicked.connect(editor.disconnect_remote)
        self.status_button.clicked.connect(editor.query_remote)
        self.direct.toggled.connect(editor.refresh_remote_controls)
        self.apply_button.clicked.connect(editor.apply_remote)
        self.mute_button.clicked.connect(editor.mute_remote)
        self.led_off_button.clicked.connect(editor.led_off_remote)
        self.selected_button.clicked.connect(lambda: editor.run_remote("selected"))
        self.all_button.clicked.connect(lambda: editor.run_remote("all"))
        self.current_button.clicked.connect(lambda: editor.run_remote("current"))
        self.stop_button.clicked.connect(editor.stop_remote)

    def _preset(self, index):
        if index < 2:
            self.ip.setText(("127.0.0.1", "192.168.61.1")[index])
            self.port.setValue(5000)

    def refresh(self):
        e = self.editor;s = e.remote
        idle = not s.busy and not e.is_running() and not e.remote_disconnect_pending
        ready = s.connected and idle
        for w in (self.preset, self.ip, self.port):w.setEnabled(not s.connected and idle)
        self.connect_button.setEnabled(not s.connected and idle)
        self.disconnect_button.setEnabled(s.connected and not e.remote_disconnect_pending)
        self.status_button.setEnabled(ready)
        ready = ready and not e.live.active and not e.live.pending
        self.direct.setEnabled(ready)
        if not s.connected:self.direct.setChecked(False)
        self.apply_button.setEnabled(ready and self.direct.isChecked() and e.valid_remote_draft())
        self.mute_button.setEnabled(ready)
        self.led_off_button.setEnabled(ready)
        selected = e.selected >= 0 and bool(e.list.selected_rows())
        self.selected_button.setEnabled(ready and selected)
        self.current_button.setEnabled(ready and selected)
        self.all_button.setEnabled(ready and bool(e.sequence.items))
        self.repeat.setEnabled(idle and not e.live.active)
        self.stop_button.setEnabled(e.remote_running and not s.cancel.is_set())
        self.connection.setText(("접속 주소: " + e.remote_endpoint) if s.connected else "연결 안 됨")
