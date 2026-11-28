from .card_clipboard import MIME_TYPE, encode_cards, decode_cards
from .shortcuts import PREFIX
from PySide6.QtCore import QMimeData
"""Light Studio authoring UI with optional explicit server control."""
from time import perf_counter
from functools import lru_cache
import math
import re
from dataclasses import replace
from .audio import create_audio
from .remote_ui import RemoteUi
from .live_controls import LiveControls
from .file_ui import FileUi
from .pulse_spin import PulseSpinBox
from .motion import PULSE_LIMITS
from .previews import OutputPreview, card_thumbnail
from .led_editor import LedEditor
from .playback import MotionPlayback
from PySide6.QtCore import Qt, QSize, QSignalBlocker, QTimer, QItemSelectionModel
from PySide6.QtGui import QAction, QIcon, QKeySequence, QFont, QPainter, QColor, QPen
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QBoxLayout,
    QTabBar, QStackedWidget, QCheckBox, QFrame, QLabel, QPushButton, QSizePolicy, QSpinBox, QSlider, QLineEdit, QListWidget,
    QListWidgetItem, QListView, QAbstractItemView, QPlainTextEdit, QDialog,
    QMessageBox, QButtonGroup, QSplitter, QLayout, QStyledItemDelegate, QStyle,
)
from .motion import Motion, Buzzer, LED, kind, detail, Sequence, call_code, generate_code
from .motion_list import MotionList
from .sequence_window import SequenceWindow
from .viewport import EditViewport, thumbnail
from .style import STYLE
from pathlib import Path
from uhand_about import add_about_action, product_logo
from . import __version__

AXES=("Finger1","Finger2","Finger3","Finger4","Finger5","Wrist")

def label(text,name=None):
    w=QLabel(text);w.setTextFormat(Qt.TextFormat.PlainText)
    if name:w.setObjectName(name)
    return w

def button(text,slot,primary=False):
    w=QPushButton(text);w.clicked.connect(slot)
    if primary:w.setObjectName("primary")
    return w

def ask(parent,title,text,buttons,default):
    dialog=QMessageBox(parent)
    dialog.setWindowTitle(title);dialog.setText(text)
    dialog.setStandardButtons(buttons);dialog.setDefaultButton(default)
    return dialog.exec()

def card():
    w=QFrame();w.setObjectName("card")
    layout=QVBoxLayout(w);layout.setContentsMargins(14,12,14,12);layout.setSpacing(8);layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
    return w,layout

class StableHeightStack(QStackedWidget):
    """Measure every page at the available width, regardless of which one is visible."""
    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        pages = (self.widget(index) for index in range(self.count()))
        return max((page.heightForWidth(width) if page.hasHeightForWidth()
                    else page.sizeHint().height() for page in pages), default=0)


class MotionDelegate(QStyledItemDelegate):
    LED_TEXT_LEFT = 72

    @staticmethod
    @lru_cache(maxsize=128)
    def thumbnail_icon(card):
        return QIcon(card_thumbnail(card))

    def paint(self,painter,option,index):
        painter.save();painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect=option.rect.adjusted(3,3,-3,-3)
        selected=bool(option.state & QStyle.StateFlag.State_Selected)
        playing=bool(index.data(Qt.ItemDataRole.UserRole+1))
        painter.setBrush(QColor("#fff1d2" if playing else "#eaf1ff" if selected else "#f5f8fd"))
        painter.setPen(QPen(QColor("#e59217" if playing else "#386bff" if selected else "#e1e8f3"),2 if selected or playing else 1))
        painter.drawRoundedRect(rect,8,8)
        motion = index.data(Qt.ItemDataRole.UserRole)
        led = isinstance(motion, LED)
        left = self.LED_TEXT_LEFT if led else 84
        x = rect.x() + left
        available = rect.width() - left - 8
        icon = self.thumbnail_icon(motion)
        icon.paint(painter, rect.x()+7, rect.y()+8, left-14, 82)
        painter.setPen(QColor("#182a45"))
        painter.drawText(x, rect.y()+27, f"{index.row()+1:02d}" + ("  ▶ 재생" if playing else ""))
        painter.drawText(x, rect.y()+48, option.fontMetrics.elidedText(motion.name, Qt.TextElideMode.ElideRight, available))
        if led:
            painter.setPen(QColor("#465b76"))
            painter.drawText(x, rect.y()+71, f"RGB {motion.red}, {motion.green}, {motion.blue}")
            painter.drawText(x, rect.y()+91, f"밝기 {motion.brightness}%")
        else:
            painter.setPen(QColor("#718098"))
            painter.drawText(x, rect.y()+75, option.fontMetrics.elidedText(detail(motion), Qt.TextElideMode.ElideRight, available))
        painter.restore()

class CodeDialog(QDialog):
    def __init__(self,motions,parent=None):
        super().__init__(parent);self.motions=tuple(motions);self.setWindowTitle("전체 동작 코드")
        self.resize(850,620);self.setMinimumSize(620,440);self.setStyleSheet(STYLE)
        layout=QVBoxLayout(self)
        layout.addWidget(label(f"전체 {len(motions)}개 동작 · 목록 순서대로 실행", "section"))
        row=QHBoxLayout();row.addWidget(label("서버 IP"))
        self.ip=QLineEdit("127.0.0.1");self.ip.setAccessibleName("서버 IP")
        row.addWidget(self.ip);row.addWidget(label("Port"))
        self.port=QSpinBox();self.port.setRange(1,65535);self.port.setValue(5000);row.addWidget(self.port)
        layout.addLayout(row)
        self.error=label("","notice");self.error.setWordWrap(True);layout.addWidget(self.error)
        self.code=QPlainTextEdit();self.code.setReadOnly(True);self.code.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self.code,1)
        layout.addWidget(label("복사한 코드를 Client가 설치된 Python 환경에서 실행하세요. 이 화면은 연결하지 않습니다.","muted"))
        row=QHBoxLayout();row.addStretch()
        self.copy_button=button("전체 코드 복사",self.copy,True);row.addWidget(self.copy_button)
        row.addWidget(button("닫기",self.accept));layout.addLayout(row)
        self.ip.textChanged.connect(self.refresh);self.port.valueChanged.connect(self.refresh);self.refresh()
    def refresh(self):
        try:
            text=generate_code(self.motions,self.ip.text().strip(),self.port.value())
        except ValueError:
            self.error.setText("올바른 IPv4 또는 IPv6 주소를 입력하세요.")
            self.copy_button.setEnabled(False);self.code.clear();return
        self.error.setText("손동작·부저는 완료 후 다음 카드 실행 / LED는 즉시 변경 후 유지됩니다.")
        self.copy_button.setEnabled(True);self.code.setPlainText(text)
    def copy(self):
        if self.copy_button.isEnabled():
            QApplication.clipboard().setText(self.code.toPlainText())
            self.error.setText("전체 코드를 복사했습니다.")

class MainWindow(FileUi,RemoteUi,QMainWindow):
    def __init__(self,audio=None):
        super().__init__()
        self.init_remote()
        self.audio=audio if audio is not None else create_audio()
        self.led_state=(False,False,False)
        self.sound_timer=QTimer(self);self.sound_timer.setSingleShot(True);self.sound_timer.setTimerType(Qt.TimerType.PreciseTimer);self.sound_timer.timeout.connect(self.stop_sound)
        self.sequence=Sequence();self.selected=-1;self.loading=False;self.force_close=False;self.name_serials=[1,1,1]
        self.init_document()
        self.sequence_window=None
        self.sequence_sync_timer=QTimer(self);self.sequence_sync_timer.setSingleShot(True);self.sequence_sync_timer.timeout.connect(self.sync_sequence_window)
        self.baseline=Motion(name="동작 01")
        self.playback=None;self.playing_row=-1
        self.play_timer=QTimer(self);self.play_timer.setInterval(16);self.play_timer.timeout.connect(self._play_tick)
        self.setWindowTitle("uHandMotionCreator");self.setStyleSheet(STYLE)
        self.setWindowIcon(QIcon(str(Path(__file__).with_name("uHandMotionCreator.ico"))))
        self.setMinimumSize(740,740)
        available=QApplication.primaryScreen().availableGeometry()
        scale=max(1,min(100,(available.width()-50)//16,(available.height()-60)//9))
        minimum_scale = max(math.ceil(self.minimumWidth() / 16), math.ceil(self.minimumHeight() / 9))
        if available.width() >= minimum_scale * 16 and available.height() >= minimum_scale * 9:
            scale = max(scale, minimum_scale)
        self.resize(16*scale,9*scale)
        root=QWidget();root.setObjectName("root")
        self.setCentralWidget(root)
        layout=QVBoxLayout(root);layout.setContentsMargins(20,12,20,10);layout.setSpacing(10);layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        header=QHBoxLayout()
        logo = product_logo(self, 44, "appLogo")
        brand = QHBoxLayout()
        brand.setSpacing(14)
        brand.addWidget(logo)
        title = QVBoxLayout()
        title.setSpacing(1)
        title.addWidget(label("uHandMotionCreator", "title"))
        self.subtitle = label("로봇손 동작의 설계부터 실행까지", "muted")
        title.addWidget(self.subtitle)
        brand.addLayout(title)
        brand.setAlignment(title, Qt.AlignmentFlag.AlignVCenter)
        header.addLayout(brand)
        header.addStretch()
        self.connection_badge=label("OFFLINE · 로컬 편집","notice");header.addWidget(self.connection_badge)
        self.connection_badge.setWordWrap(True)
        header.addWidget(button("서버 연결 · 테스트",self.show_server_panel))
        self.file_open_button=button("열기",self.open_document);header.addWidget(self.file_open_button)
        self.file_save_button=button("저장",self.save_document);header.addWidget(self.file_save_button)
        self.generate_button=button("</>  코드 생성",self.show_code,True);header.addWidget(self.generate_button)
        layout.addLayout(header)
        top=QHBoxLayout();top.setSpacing(12)
        viewport_card,outer_vl=card()
        self.preview_header = StableHeightStack()
        self.preview_stack = QStackedWidget()
        preview_footer = StableHeightStack()
        for strip in (self.preview_header, preview_footer):
            strip.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        outer_vl.addWidget(self.preview_header)
        outer_vl.addWidget(self.preview_stack, 1)
        outer_vl.addWidget(preview_footer)
        self.preview_stack.currentChanged.connect(self.preview_header.setCurrentIndex)
        self.preview_stack.currentChanged.connect(preview_footer.setCurrentIndex)

        hand_header = QWidget()
        vl = QVBoxLayout(hand_header)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(8)
        row=QHBoxLayout();row.addWidget(label("3D 자세 편집","section"));row.addStretch()
        self.edit_button=button("자세 편집",lambda:self.set_mode(True));self.edit_button.setCheckable(True)
        self.camera_button=button("카메라",lambda:self.set_mode(False));self.camera_button.setCheckable(True)
        group=QButtonGroup(self);group.addButton(self.edit_button);group.addButton(self.camera_button);self.edit_button.setChecked(True)
        row.addWidget(self.edit_button);row.addWidget(self.camera_button);vl.addLayout(row)
        row=QHBoxLayout()
        self.axis_hint=label("Finger1 선택 · 위아래 드래그로 펄스 조정","notice");self.axis_hint.setWordWrap(True);row.addWidget(self.axis_hint,1)
        row.addWidget(button("기본 보기",lambda:self.viewport.home()))
        row.addWidget(button("정면",lambda:self.viewport.front()))
        row.addWidget(button("+",lambda:self.viewport.zoom(.85)))
        row.addWidget(button("−",lambda:self.viewport.zoom(1.18)));vl.addLayout(row)

        buzzer_header = QWidget()
        bl = QVBoxLayout(buzzer_header)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(8)
        row = QHBoxLayout()
        row.addWidget(label("부저 미리보기", "section"))
        row.addStretch()
        self.listen_button = button("▶ 소리 미리듣기", self.preview_sound, True)
        self.sound_stop_button = button("■ 소리 정지", self.stop_sound)
        row.addWidget(self.listen_button)
        row.addWidget(self.sound_stop_button)
        bl.addLayout(row)
        bl.addWidget(label("PC 스피커로 미리 듣기 · 실제 장치 연결 없음", "muted"))
        led_header = QWidget()
        ll = QVBoxLayout(led_header)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(8)
        ll.addWidget(label("삼색 LED 미리보기", "section"))
        ll.addWidget(label("LED 1 · LED 2 동시 제어 / RGB 0~255 · 전체 밝기 0~100%", "muted"))
        for header_page in (hand_header, buzzer_header, led_header):
            self.preview_header.addWidget(header_page)

        self.audio_status = label("미리듣기 버튼을 눌러 소리를 확인하세요.", "notice")
        self.audio_status.setWordWrap(True)
        hand_note = label("왼쪽 드래그: 자세 편집 · 오른쪽: 카메라 회전 · 휠: 확대/축소", "muted")
        hand_note.setWordWrap(True)
        preview_footer.addWidget(hand_note)
        preview_footer.addWidget(self.audio_status)
        preview_footer.addWidget(label("색상을 즉시 변경하고 다음 LED 카드까지 유지합니다.", "notice"))
        self.viewport = EditViewport()
        self.buzzer_preview = OutputPreview("buzzer")
        self.led_preview = OutputPreview("led")
        for canvas in (self.viewport, self.buzzer_preview, self.led_preview):
            self.preview_stack.addWidget(canvas)
        top.addWidget(viewport_card,3)
        controls,cl=card();self.controls=controls;controls.setMinimumWidth(360);cl.setSpacing(6)
        self.parameter_header = QGridLayout()
        self.parameter_header.addWidget(label("동작 파라미터","section"), 0, 0)
        self.parameter_header.setColumnStretch(0, 1)
        self.reset_button=button("초기값으로 초기화",self.reset_parameters)
        self.reset_button.setToolTip("Finger1~5·Wrist: 1500 / RunningTime: 1000ms\n동작 이름과 저장된 카드는 유지됩니다.")
        self.remote_apply_button=button("서버에 적용",self.apply_remote)
        self.remote_mute_button=button("서버 소리 끄기",self.mute_remote)
        self.remote_led_off_button=button("서버 LED 끄기",self.led_off_remote)
        self.remote_led_off_button.setToolTip("연결된 서버의 LED 1·2를 모두 끕니다.")
        self.remote_buttons = QWidget()
        remote_row = QHBoxLayout(self.remote_buttons)
        remote_row.setContentsMargins(0, 0, 0, 0)
        for control in (self.remote_apply_button, self.remote_mute_button, self.remote_led_off_button):
            remote_row.addWidget(control)
        self.parameter_header.addWidget(self.remote_buttons, 0, 1)
        self.parameter_header.addWidget(self.reset_button, 0, 2)
        cl.addLayout(self.parameter_header)
        self.tabs=QTabBar();self.tabs.setExpanding(True)
        for text in ("손동작","부저","삼색 LED","실시간 제어"):self.tabs.addTab(text)
        self.tabs.setStyleSheet("QTabBar::tab {padding:7px 16px; background:#f0f4fa; color:#61728b; border-radius:5px;} QTabBar::tab:selected {background:#245eea; color:white;} QTabBar::tab:hover {background:#dce7ff; color:#182a45;}")
        cl.addWidget(self.tabs)
        self.parameter_stack = StableHeightStack()
        hand_parameters=QWidget();hl=QVBoxLayout(hand_parameters);hl.setContentsMargins(0,0,0,0);hl.setSpacing(4)
        self.parameter_stack.addWidget(hand_parameters);cl.addWidget(self.parameter_stack,1)
        grid=QGridLayout();grid.setHorizontalSpacing(10);grid.setVerticalSpacing(4)
        self.axis_grid = grid
        self.spins=[];self.sliders=[];self.axis_buttons=[]
        self.axes_group=QButtonGroup(self)
        for index,name in enumerate(AXES):
            b=button(name,lambda checked=False,i=index:self.select_axis(i));b.setCheckable(True)
            self.axes_group.addButton(b);self.axis_buttons.append(b)
            spin=PulseSpinBox(name,PULSE_LIMITS[index]);spin.setValue(1500);spin.setKeyboardTracking(False)
            spin.inputRejected.connect(lambda message:self.notice.setText(message))
            spin.setAccessibleName(name+" Pulse");spin.setMinimumWidth(80)
            slider=QSlider(Qt.Orientation.Horizontal);slider.setRange(*PULSE_LIMITS[index]);slider.setValue(1500);slider.setMinimumWidth(80)
            slider.setAccessibleName(name+" slider");slider.setToolTip(f"{name}: {PULSE_LIMITS[index][0]}~{PULSE_LIMITS[index][1]}")
            spin.valueChanged.connect(lambda value,i=index:self.change_pulse(i,value))
            slider.valueChanged.connect(lambda value,i=index:self.spins[i].setValue(value))
            grid.addWidget(b,index,0);grid.addWidget(spin,index,1);grid.addWidget(slider,index,2)
            grid.setRowMinimumHeight(index,32)
            self.spins.append(spin);self.sliders.append(slider)
        self.axis_buttons[0].setChecked(True);hl.addLayout(grid)
        row=QHBoxLayout();row.addWidget(label("RunningTime (ms)"))
        self.time=QSpinBox();self.time.setRange(100,20000);self.time.setValue(1000);self.time.setKeyboardTracking(False);row.addWidget(self.time);hl.addLayout(row)
        self.time.setToolTip("100–20000 ms · 동작이 완료된 뒤 다음 카드 실행")
        buzzer_parameters=QWidget();bp=QVBoxLayout(buzzer_parameters);bp.setContentsMargins(0,0,0,0)
        bp.addWidget(label("Frequency (Hz)","section"))
        self.frequency=PulseSpinBox("Frequency (Hz)",(0,10000));self.frequency.inputRejected.connect(lambda message:self.notice.setText(message));self.frequency.setValue(1000);self.frequency.setKeyboardTracking(False);bp.addWidget(self.frequency)
        presets=QHBoxLayout()
        for hz in (0,1000,1900):presets.addWidget(button(f"{hz} Hz",lambda checked=False,h=hz:self.frequency.setValue(h)))
        bp.addLayout(presets);bp.addWidget(label("RunningTime (ms)"))
        self.buzzer_time=QSpinBox();self.buzzer_time.setRange(100,20000);self.buzzer_time.setValue(1000);self.buzzer_time.setKeyboardTracking(False);bp.addWidget(self.buzzer_time)
        self.continuous=QCheckBox("연속 재생 · 다음 부저 명령까지 유지");bp.addWidget(self.continuous)
        self.continuous.setToolTip("즉시 다음 카드 실행 · 0 Hz는 무음 유지 · RunningTime 대기 없음")
        limits=label("0 Hz: 무음 · 1–10,000 Hz: 부저 재생","muted");limits.setWordWrap(True);bp.addWidget(limits);bp.addStretch()
        self.parameter_stack.addWidget(buzzer_parameters)
        self.led_editor = LedEditor()
        self.parameter_stack.addWidget(self.led_editor)
        self.live = LiveControls(self)
        # Only the three card editors share a stable height.
        cl.addWidget(self.live, 1)
        self.live.hide()
        row=QHBoxLayout();self.name_label=label("동작 이름");row.addWidget(self.name_label)
        self.name=QLineEdit("동작 01");self.name.setMaxLength(60);row.addWidget(self.name);cl.addLayout(row)
        self.notice=label("값을 설정한 뒤 동작 추가를 누르세요.","notice");self.notice.setWordWrap(True);cl.addWidget(self.notice)
        self.add_button=button("+  동작 추가",self.add_motion,True)
        self.apply_button=button("선택 동작에 적용",self.apply_motion)
        action_row=QHBoxLayout();action_row.addWidget(self.add_button);action_row.addWidget(self.apply_button);cl.addLayout(action_row)
        top.addWidget(controls,2);layout.addLayout(top,3)
        bottom=QHBoxLayout();bottom.setSpacing(12)
        list_card,ll=card()
        self.sequence_toolbar = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        row=QHBoxLayout();row.setSpacing(6)
        self.sequence_toolbar.addLayout(row, 1)
        self.count=label("동작 시퀀스 (0)","section");row.addWidget(self.count)
        self.play_from_start=button("▶ 처음부터 재생",lambda:self.start_playback(False))
        self.play_from_current=button("▶ 현재 카드부터 재생",lambda:self.start_playback(True))
        self.play_stop=button("■ 정지",lambda:self.stop_playback())
        self.play_from_start.setToolTip("저장된 첫 동작부터 마지막 동작까지 미리보기")
        self.play_from_current.setToolTip("현재 편집 카드부터 마지막 동작까지 미리보기")
        for b in (self.play_from_start,self.play_from_current,self.play_stop):row.addWidget(b)
        row.addStretch()
        row = QHBoxLayout()
        self.sequence_toolbar.addLayout(row)
        self.sequence_view_button=button("리스트 보기",self.show_sequence_window);row.addWidget(self.sequence_view_button)
        self.left=button("←",lambda:self.move_motion(-1));self.left.setToolTip("선택 동작을 앞으로 이동")
        self.right=button("→",lambda:self.move_motion(1));self.right.setToolTip("선택 동작을 뒤로 이동")
        self.remove=button("삭제",self.delete_motion)
        for b in (self.left,self.right,self.remove):row.addWidget(b)
        ll.addLayout(self.sequence_toolbar)
        self.playback_status=label("손동작·일반 부저는 순차 재생 / 연속 부저·LED는 즉시 적용","muted")
        self.playback_status.setWordWrap(True)
        playback_row=QHBoxLayout();playback_row.addWidget(self.playback_status,1)
        self.remaining_label = label("", "muted")
        playback_row.addWidget(self.remaining_label)
        self.repeat_playback=QCheckBox("반복 재생")
        self.repeat_playback.setToolTip("PC 미리보기 반복 · 처음부터: 전체 / 현재 카드부터: 선택 카드~마지막\n정지 버튼으로 종료 · 시간 0인 카드만 있는 구간은 반복 불가")
        playback_row.addWidget(self.repeat_playback);ll.addLayout(playback_row)
        self.list=MotionList();self.list.setFlow(QListView.Flow.LeftToRight);self.list.setWrapping(False)
        self.list.setViewMode(QListView.ViewMode.IconMode);self.list.setMovement(QListView.Movement.Static)
        self.list.setResizeMode(QListView.ResizeMode.Adjust);self.list.setIconSize(QSize(88,96))
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setItemDelegate(MotionDelegate(self.list));self.list.setFixedHeight(132);self.list.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list.currentRowChanged.connect(self.select_motion)
        self.list.itemSelectionChanged.connect(self.refresh_delete_action)
        self.list.itemClicked.connect(lambda item:self.reselect_card(self.list.row(item)))
        self.list.reorderRequested.connect(self.reorder_motion)
        self.list.commandRequested.connect(lambda action:self.card_command(action,self.list))
        ll.addWidget(self.list)
        self.empty=label("아직 동작이 없습니다. 오른쪽의 ‘동작 추가’로 시작하세요.","muted")
        self.selection_hint=label(f"Shift: 범위 선택 · 드래그: 이동 · Delete: 삭제 · {PREFIX}C/X/V","muted")
        hints=QHBoxLayout();hints.setContentsMargins(0,0,0,0);hints.addWidget(self.empty);hints.addWidget(self.selection_hint)
        ll.addLayout(hints)
        bottom.addWidget(list_card,3)
        code_card,pl=card()
        row=QHBoxLayout();row.addWidget(label("선택 동작 코드 (Python)","section"));row.addStretch()
        self.copy_button=button("복사",self.copy_selected);row.addWidget(self.copy_button);pl.addLayout(row)
        self.preview=QPlainTextEdit();self.preview.setReadOnly(True)
        self.preview.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Ignored)
        self.preview.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth);self.preview.setMinimumWidth(320);pl.addWidget(self.preview,1)
        pl.addWidget(label("목록에 저장된 값 · 수정 후 ‘선택 동작에 적용’","muted"))
        bottom.addWidget(code_card,2);layout.addLayout(bottom,1)
        footer=QHBoxLayout();footer.addWidget(label(f"v{__version__}","muted"));footer.addStretch()
        self.document_label=label("새 동작 시퀀스","muted")
        self.document_label.setMaximumWidth(600)
        self.document_label.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred)
        footer.addWidget(self.document_label,1);layout.addLayout(footer)
        self.viewport.axisSelected.connect(self.select_axis);self.viewport.pulseChanged.connect(self.viewport_pulse)
        self.time.valueChanged.connect(self.editor_changed);self.name.textChanged.connect(self.editor_changed)
        self.tabs.currentChanged.connect(self.change_tab)
        self.continuous.toggled.connect(self.output_changed)
        self.frequency.valueChanged.connect(self.output_changed);self.buzzer_time.valueChanged.connect(self.output_changed)
        self.led_editor.changed.connect(self.output_changed)
        self.build_menu();self.refresh_list(-1);self.refresh_remote_controls();self.remote_timer.start()
    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not hasattr(self, "axis_grid"):
            return
        # Keep the footer on the same baseline for Korean and Latin filenames.
        self.document_label.setMinimumHeight(self.subtitle.sizeHint().height())
        size = event.size()
        compact = size.height() < 890 or size.width() < 1200
        narrow = size.width() < 1050
        if getattr(self, "_layout_mode", None) == (compact, narrow):
            return
        self._layout_mode = (compact, narrow)
        self.setMinimumHeight(800 if narrow else 740)
        if narrow:
            self.parameter_header.addWidget(self.remote_buttons, 1, 0, 1, 3)
        else:
            self.parameter_header.addWidget(self.remote_buttons, 0, 1)
        self.sequence_toolbar.setDirection(QBoxLayout.Direction.TopToBottom if narrow else QBoxLayout.Direction.LeftToRight)
        self.sequence_toolbar.setStretch(0, 0 if narrow else 1)
        self.preview.setMinimumWidth(190 if narrow else 320)
        # Keep the preview height stable when the two-line playback hint becomes a short status.
        self.playback_status.setMinimumHeight(2 * self.playback_status.fontMetrics().lineSpacing() if narrow else 0)
        self.viewport.setMinimumWidth(260 if narrow else 380)
        root = self.centralWidget()
        root.setStyleSheet(
            "QPushButton {padding:2px 6px; min-height:18px;}"
            "QSpinBox, QLineEdit {padding:2px; min-height:18px;}" if compact else ""
        )
        margins = (12, 6, 12, 6) if compact else (20, 12, 20, 10)
        root.layout().setContentsMargins(*margins)
        root.layout().setSpacing(6 if compact else 10)
        panel_margins = (10, 6, 10, 6) if compact else (14, 12, 14, 12)
        for panel in root.findChildren(QFrame, "card"):
            layout = panel.layout()
            layout.setContentsMargins(*panel_margins)
            layout.setSpacing(4 if compact else (6 if panel is self.controls else 8))
        self.viewport.setMinimumHeight(210 if compact else 270)
        for row in range(self.axis_grid.rowCount()):
            self.axis_grid.setRowMinimumHeight(row, 24 if compact else 32)
        # Hidden pages keep old size hints until selected unless their nested layouts refresh.
        for stack in (self.preview_header, self.parameter_stack, self.live):
            for layout in reversed(stack.findChildren(QLayout)):
                layout.invalidate()
                layout.activate()
            stack.updateGeometry()

    def build_menu(self):
        self.build_file_menu()
        edit=self.menuBar().addMenu("편집")
        self.undo_action=QAction("실행 취소",self);self.undo_action.setShortcut(QKeySequence.StandardKey.Undo);self.undo_action.triggered.connect(self.undo)
        self.redo_action=QAction("다시 실행",self);self.redo_action.setShortcut(QKeySequence.StandardKey.Redo);self.redo_action.triggered.connect(self.redo)
        edit.addAction(self.undo_action);edit.addAction(self.redo_action)
        view=self.menuBar().addMenu("보기");view.addAction("기본 보기",self.viewport.home);view.addAction("정면 보기",self.viewport.front)
        help_menu=self.menuBar().addMenu("도움말");help_menu.addAction("사용 방법",self.help)
        add_about_action(self, "uHandMotionCreator", "로봇손 동작의 설계부터 실행까지", __version__)
    def help(self):
        QMessageBox.information(self,"사용 방법",f"1. 손동작 / 부저 / 삼색 LED 탭을 선택합니다.\n2. 값을 편집하고 이름을 정해 동작을 추가합니다.\n3. 목록 선택 후 수정은 ‘선택 동작에 적용’으로 확정합니다.\n4. Shift+클릭으로 여러 카드를 선택한 뒤 함께 드래그할 수 있습니다.\n5. 시퀀스 재생으로 PC에서 확인하고 전체 코드를 복사합니다.\n6. 서버 연결·테스트에서 선택적으로 가상/실물 서버에 연결합니다.\n7. 실시간 제어 탭에서 손·부저·LED를 조작하거나 직접 제어 모드를 켜고 서버에 적용하거나 저장 카드를 실행합니다.\n서버 정지는 현재 명령 완료 후 다음 카드 실행을 중단합니다.\n\n부저: 미리듣기를 눌러야 소리가 납니다.\nLED: 즉시 변경 후 다음 LED 카드까지 유지됩니다.\n탭 전환: 미적용 수정 확인 후 새 카드 작성을 시작합니다.\n\n자세 편집: 손가락 상하 / 손바닥 좌우 드래그\n카메라: 모든 모드에서 오른쪽 드래그로 회전 / 휠로 확대·축소\n파일 메뉴에서 JSON으로 저장({PREFIX}S)하고 다시 열 수 있습니다({PREFIX}O).")
    def draft(self):
        tab = kind(self.baseline) if self.live.active else self.tabs.currentIndex()
        if tab==1:return Buzzer(self.frequency.value(),self.buzzer_time.value(),self.name.text().strip(),self.continuous.isChecked())
        if tab==2:return self.led_editor.card(self.name.text().strip())
        return Motion(tuple(s.value() for s in self.spins),self.time.value(),self.name.text().strip())
    def changed(self):
        try:return self.draft()!=self.baseline
        except ValueError:return True
    def confirm_discard(self):
        if not self.changed():return True
        return ask(self,"편집 중인 카드","목록에 적용하지 않은 수정이 있습니다. 이 수정을 버리고 계속할까요?",QMessageBox.StandardButton.Discard|QMessageBox.StandardButton.Cancel,QMessageBox.StandardButton.Cancel)==QMessageBox.StandardButton.Discard
    def set_mode(self,editing):
        self.edit_button.setChecked(editing);self.camera_button.setChecked(not editing);self.viewport.mode(editing)
        self.update_hint()
    def select_axis(self,index):
        self.axis_buttons[index].setChecked(True);self.viewport.select_axis(index);self.update_hint()
    def update_hint(self):
        axis=self.viewport.axis
        self.axis_hint.setText((AXES[axis]+" 선택 · "+("좌우 드래그 · YAW" if axis==5 else "위아래 드래그로 펄스 조정")) if self.viewport.edit_mode else "카메라 모드 · 좌/우 드래그로 회전 / 휠로 확대")
    def viewport_pulse(self, index, value):
        if self.live.active:
            if self.live.available() and self.live.hand_state == "on":
                self.live.axes[index].setValue(value)
        else:
            self.spins[index].setValue(value)

    def change_pulse(self,index,value):
        with QSignalBlocker(self.sliders[index]):self.sliders[index].setValue(value)
        if not self.loading:
            self.viewport.set_pulses([s.value() for s in self.spins]);self.editor_changed()
    def editor_changed(self,*_):
        if self.loading:return
        if self.live.active:
            self.add_button.setEnabled(False);self.apply_button.setEnabled(False)
            return
        try:self.draft();valid=True
        except ValueError as exc:self.notice.setText(str(exc));valid=False
        if valid:self.notice.setText("편집 중 · 추가하거나 선택 동작에 적용하세요." if self.changed() else "목록의 선택 카드와 같은 값입니다." if self.selected>=0 else "값을 설정한 뒤 동작 추가를 누르세요.")
        self.add_button.setEnabled(valid and not self.is_running() and self.sequence.remaining_cards > 0)
        self.apply_button.setEnabled(valid and not self.is_running() and self.selected>=0 and kind(self.sequence.items[self.selected])==self.tabs.currentIndex() and self.changed())
        self.refresh_remote_controls()
    def reset_parameters(self):
        if self.sequence_locked():return
        self.stop_sound()
        defaults=(Motion(),Buzzer(),LED())[self.tabs.currentIndex()]
        name=self.name.text();baseline=self.baseline
        self.load_motion(defaults)
        self.loading=True;self.name.setText(name);self.baseline=baseline;self.loading=False
        self.editor_changed()

    def load_motion(self,motion):
        self.loading=True
        index=kind(motion)
        with QSignalBlocker(self.tabs):self.tabs.setCurrentIndex(index)
        self.parameter_stack.setCurrentIndex(index)
        self.preview_stack.setCurrentIndex(0 if self.is_running() else index)
        if isinstance(motion,Motion):
            for spin,value in zip(self.spins,motion.pulses):spin.setValue(value)
            self.time.setValue(motion.running_time);self.viewport.set_pulses(motion.pulses)
        elif isinstance(motion,Buzzer):
            self.frequency.setValue(motion.frequency);self.buzzer_time.setValue(motion.running_time)
            self.continuous.setChecked(motion.continuous);self.buzzer_time.setEnabled(not motion.continuous)
            self.buzzer_preview.frequency=motion.frequency;self.buzzer_preview.update()
        else:
            self.led_editor.load(motion)
            self.set_led_preview(motion.output_rgb)
        self.name.setText(motion.name);self.baseline=motion;self.loading=False
        self.reset_button.setToolTip(("Finger1~5·Wrist: 1500 / RunningTime: 1000ms","Frequency: 1000Hz / RunningTime: 1000ms","RGB: 0, 0, 0 / 전체 밝기: 100%")[index]+"\n이름과 저장된 카드는 유지됩니다.")
        self.editor_changed()

    def next_name(self,index):
        return f"{('동작','부저','LED')[index]} {self.name_serials[index]:02d}"

    def show_edit_controls(self, show):
        self.live.setVisible(not show)
        for widget in (self.parameter_stack, self.remote_buttons, self.reset_button, self.name_label, self.name,
                       self.notice, self.add_button, self.apply_button):
            widget.setVisible(show)
        self.list.set_read_only(not show)
        self.sequence_view_button.setEnabled(show)
        self.schedule_sequence_sync()

    def change_tab(self,index):
        if self.loading:return
        previous=kind(self.baseline)
        if index == 3:
            if self.is_running():
                with QSignalBlocker(self.tabs):
                    self.tabs.setCurrentIndex(previous)
                return
            self.stop_sound()
            self.preview_stack.setCurrentIndex(0)
            self.live.enter()
            self.show_edit_controls(False)
            self.refresh_actions()
            return
        if self.live.active:
            self.live.leave()
            self.show_edit_controls(True)
            self.preview_stack.setCurrentIndex(previous)
            if index == previous:
                self.refresh_actions()
                return
        # Validate the old draft before leaving its tab.
        with QSignalBlocker(self.tabs):self.tabs.setCurrentIndex(previous)
        if not self.confirm_discard():
            self.refresh_actions()
            return
        self.stop_sound()
        # Keep the current card as the insertion anchor when changing output type.
        defaults=(Motion(name=self.next_name(0)),Buzzer(name=self.next_name(1)),LED(name=self.next_name(2)))
        self.load_motion(defaults[index]);self.refresh_actions()

    def set_led_preview(self,rgb):
        self.led_state=tuple(rgb);self.led_preview.rgb=self.led_state;self.led_preview.update()

    def output_changed(self,*_):
        self.buzzer_time.setEnabled(not self.continuous.isChecked())
        if self.loading:return
        self.stop_sound()
        self.buzzer_preview.frequency=self.frequency.value();self.buzzer_preview.update()
        if self.tabs.currentIndex()==2:self.set_led_preview(self.led_editor.card().output_rgb)
        self.editor_changed()

    def stop_sound(self):
        self.sound_timer.stop();self.sound_continuous=False;error=None
        try:self.audio.stop()
        except (OSError,RuntimeError) as exc:error=str(exc)
        self.buzzer_preview.active=error is not None;self.buzzer_preview.update()
        self.sound_stop_button.setEnabled(error is not None and not self.is_running())
        self.listen_button.setEnabled(error is None and not self.is_running())
        self.audio_status.setText(error or "소리 정지 · 미리듣기 버튼을 눌러 다시 재생")
        if error:self.notice.setText(error)
        self.refresh_playback_actions()
        return error is None

    def play_sound(self,frequency,duration,continuous=False):
        self.sound_timer.stop()
        try:
            if frequency == 0:self.audio.stop()
            elif continuous:self.audio.play(frequency,duration,True)
            else:self.audio.play(frequency,duration)
        except (ValueError,OSError,RuntimeError) as exc:
            self.audio_status.setText(str(exc));return False
        self.sound_continuous=continuous
        self.buzzer_preview.frequency=frequency
        self.buzzer_preview.active=frequency > 0;self.buzzer_preview.update()
        self.audio_status.setText(("무음" if frequency == 0 else f"{frequency} Hz") + (" · 다음 부저 명령까지 유지" if continuous else " · 지정 시간 재생"))
        self.listen_button.setEnabled(False);self.sound_stop_button.setEnabled(not self.is_running())
        if not continuous:self.sound_timer.start(max(1,math.ceil(duration)))
        self.refresh_playback_actions()
        return True

    def preview_sound(self):
        if self.is_running() or self.tabs.currentIndex()!=1:return
        self.stop_sound()
        self.play_sound(self.frequency.value(),self.buzzer_time.value(),self.continuous.isChecked())

    def add_motion(self):
        if self.sequence_locked():return
        try:
            self.sequence.require_space(1)
            motion = self.draft()
        except ValueError as exc:self.notice.setText(str(exc));return
        index=self.selected+1 if self.selected in self.list.selected_rows() else len(self.sequence.items)
        output=kind(motion)
        prefix=("동작","부저","LED")[output]
        if re.fullmatch(re.escape(prefix)+r" [0-9]+",motion.name):
            motion=replace(motion,name=self.next_name(output))
        self.sequence.insert(index,motion);self.name_serials[output]+=1;self.show_inserted_cards((index,))
    def apply_motion(self):
        if self.sequence_locked():return
        if self.selected<0 or kind(self.sequence.items[self.selected])!=self.tabs.currentIndex():return
        try:self.sequence.replace(self.selected,self.draft())
        except ValueError as exc:self.notice.setText(str(exc));return
        self.stop_sound()
        # Update the existing card; rebuilding the list resets its scroll position.
        self.update_card_item(self.list.item(self.selected), self.selected)
        self.load_motion(self.sequence.items[self.selected])
        self.refresh_actions()
    def select_motion(self,index):
        if self.loading or self.sequence_locked():return
        if index==self.selected and (index<0 or self.baseline==self.sequence.items[index]):return
        if not self.confirm_discard():
            with QSignalBlocker(self.list):self.list.setCurrentRow(self.selected)
            return
        self.stop_sound();self.selected=index
        if index>=0:self.load_motion(self.sequence.items[index])
        self.refresh_actions()
    def update_card_item(self, item, index):
        motion = self.sequence.items[index]
        item.setText(f"{index+1:02d}  {motion.name}\n{detail(motion)}")
        item.setToolTip(f"{motion.name}\n{call_code(motion)}")
        item.setData(Qt.ItemDataRole.UserRole, motion)
        width = 204
        if isinstance(motion, LED):
            # Reserve both outer insets and the text column, even at larger font sizes.
            metrics = self.list.fontMetrics()
            longest = max(metrics.horizontalAdvance("RGB 255, 255, 255"), metrics.horizontalAdvance("밝기 100%"))
            width = max(width, 6 + MotionDelegate.LED_TEXT_LEFT + longest + 8)
        item.setSizeHint(QSize(width, 112))

    def show_inserted_cards(self, positions):
        """Insert without resetting the model or auto-scrolling through other cards."""
        self.stop_sound()
        self.loading = True
        auto_scroll = self.list.hasAutoScroll()
        self.list.setAutoScroll(False)
        try:
            with QSignalBlocker(self.list):
                for index in positions:
                    item = QListWidgetItem()
                    self.update_card_item(item, index)
                    self.list.insertItem(index, item)
                for index in range(positions[-1]+1, self.list.count()):
                    motion = self.sequence.items[index]
                    self.list.item(index).setText(f"{index+1:02d}  {motion.name}\n{detail(motion)}")
                self.selected = positions[-1]
                self.list.setCurrentRow(self.selected, QItemSelectionModel.SelectionFlag.NoUpdate)
                self.list.clearSelection()
                for index in positions:self.list.item(index).setSelected(True)
            self.list.doItemsLayout()
        finally:
            self.list.setAutoScroll(auto_scroll)
            self.loading = False
        self.load_motion(self.sequence.items[self.selected])
        self.refresh_actions()
        rect = self.list.visualItemRect(self.list.item(self.selected))
        viewport = self.list.viewport().rect()
        delta = rect.left() if rect.left() < 0 else max(0, rect.right()-viewport.right())
        bar = self.list.horizontalScrollBar()
        bar.setValue(bar.value()+delta)

    def refresh_list(self,index):
        self.stop_sound()
        self.loading=True
        self.list.clear()
        for i in range(len(self.sequence.items)):
            item=QListWidgetItem()
            self.update_card_item(item, i)
            self.list.addItem(item)
        self.selected=min(index,len(self.sequence.items)-1);self.list.setCurrentRow(self.selected);self.loading=False
        if self.selected>=0:self.load_motion(self.sequence.items[self.selected])
        else:self.load_motion(Motion(name=self.next_name(0)))
        self.refresh_actions()
    def refresh_actions(self):
        n=len(self.sequence.items);has=self.selected>=0;active=self.sequence_locked()
        self.remaining_label.setText(f"남은 카드 {self.sequence.remaining_cards:,}장")
        self.count.setText(f"동작 시퀀스 ({n})");self.empty.setVisible(n==0);self.selection_hint.setVisible(n>0)
        self.left.setEnabled(not active and has and self.selected>0);self.right.setEnabled(not active and has and self.selected<n-1)
        self.refresh_delete_action();self.copy_button.setEnabled(has and not self.live.active);self.generate_button.setEnabled(n>0 and not self.live.active)
        self.preview.setPlainText(call_code(self.sequence.items[self.selected]) if has else "# 동작을 추가하고 선택하면\n# 호출 코드가 여기에 표시됩니다.")
        self.undo_action.setEnabled(not active and bool(self.sequence.undo_stack));self.redo_action.setEnabled(not active and bool(self.sequence.redo_stack))
        self.editor_changed();self.refresh_playback_actions();self.refresh_remote_controls()
    def move_motion(self,delta):
        if self.sequence_locked():return
        if self.selected>=0 and self.confirm_discard():self.refresh_list(self.sequence.move(self.selected,delta))
    def reorder_motion(self,indices,slot,focus=True):
        if self.sequence_locked():return
        current=self.selected;baseline=self.baseline
        draft=([spin.value() for spin in self.spins],self.time.value(),self.name.text(),self.frequency.value(),self.buzzer_time.value(),self.led_editor.card(),self.continuous.isChecked())
        positions=self.sequence.move_group(indices,slot)
        target=positions[indices.index(current)] if current in indices else positions[0]
        self.refresh_list(target)
        for row in positions:self.list.item(row).setSelected(True)
        # The current editor follows its card; unsaved values remain uncommitted.
        if current in indices:
            self.load_motion(baseline)
            self.loading=True
            for spin,value in zip(self.spins,draft[0]):spin.setValue(value)
            self.time.setValue(draft[1]);self.name.setText(draft[2])
            self.frequency.setValue(draft[3]);self.buzzer_time.setValue(draft[4]);self.continuous.setChecked(draft[6]);self.buzzer_time.setEnabled(not draft[6])
            self.led_editor.load(draft[5])
            self.loading=False
            self.buzzer_preview.frequency=draft[3];self.buzzer_preview.update()
            if self.tabs.currentIndex()==2:self.set_led_preview(draft[5].output_rgb)
            self.viewport.set_pulses(draft[0]);self.editor_changed()
        self.list.scrollToItem(self.list.item(target))
        if focus:self.list.setFocus()
        self.schedule_sequence_sync()
    def refresh_delete_action(self):
        if self.loading:return
        count=len(self.list.selected_rows())
        self.remove.setEnabled(count>0 and not self.sequence_locked())
        self.refresh_playback_actions()
        self.remove.setText(f"삭제 ({count})" if count>1 else "삭제")
        self.remove.setToolTip(f"선택한 동작 {count}개 삭제" if count else "삭제할 동작을 선택하세요.")
        self.schedule_sequence_sync()
    def capacity_notice(self, message, view):
        self.notice.setText(message)
        if view is not self.list:
            self.sequence_window.status.setText(message)

    def card_command(self,action,view):
        if self.sequence_locked() or self.loading:return
        if view._items()!=self.sequence.items:
            self.sync_sequence_window();return
        if view is not self.list:
            rows=view.selected_rows();current=view.currentRow()
            if rows!=self.list.selected_rows() or current!=self.selected:
                self.select_from_sequence_window(current,rows)
                if rows!=self.list.selected_rows() or current!=self.selected:return
        if action in ("copy", "paste") and self.sequence.remaining_cards == 0:
            self.capacity_notice("남은 카드가 0장입니다. 카드를 삭제하거나 잘라낸 뒤 다시 시도하세요.", view)
            return
        if action=="delete":
            self.delete_motion()
        elif action in ("copy","cut"):
            rows=self.list.selected_rows()
            if not rows:return
            if action=="cut" and not self.confirm_discard():return
            try:data=encode_cards(self.sequence.items[row] for row in rows)
            except ValueError as exc:self.notice.setText(str(exc));return
            mime=QMimeData();mime.setData(MIME_TYPE,data)
            mime.setText("\n".join(call_code(self.sequence.items[row]) for row in rows))
            QApplication.clipboard().setMimeData(mime)
            if action=="cut":
                self.sequence.delete_group(rows)
                self.refresh_list(min(rows[0],len(self.sequence.items)-1))
            self.notice.setText(f"{len(rows)}개 카드 "+("잘라내기 완료 · 붙여넣을 위치를 선택하세요." if action=="cut" else "복사 완료 · 저장된 카드 값을 복사했습니다."))
        elif action=="paste":
            mime=QApplication.clipboard().mimeData()
            if mime is None or not mime.hasFormat(MIME_TYPE):
                self.notice.setText("먼저 동작 카드를 복사하거나 잘라내세요.");return
            try:
                items = decode_cards(bytes(mime.data(MIME_TYPE)))
                self.sequence.require_space(len(items))
            except ValueError as exc:
                self.capacity_notice(str(exc), view)
                return
            if not self.confirm_discard():return
            index=self.selected+1 if self.selected in self.list.selected_rows() else len(self.sequence.items)
            positions=self.sequence.insert_many(index,items)
            self.show_inserted_cards(positions)
            self.notice.setText(f"{len(items)}개 카드 붙여넣기 완료")
        self.sync_sequence_window()

    def delete_motion(self):
        if self.sequence_locked():return
        rows=self.list.selected_rows()
        if rows and self.confirm_discard():
            self.sequence.delete_group(rows)
            self.refresh_list(min(rows[0],len(self.sequence.items)-1))
    def undo(self):
        if self.sequence_locked():return
        if self.confirm_discard():self.sequence.undo();self.refresh_list(min(self.selected,len(self.sequence.items)-1))
    def redo(self):
        if self.sequence_locked():return
        if self.confirm_discard():self.sequence.redo();self.refresh_list(min(max(self.selected,0),len(self.sequence.items)-1))
    def show_sequence_window(self):
        if self.sequence_window is None:self.sequence_window=SequenceWindow(self)
        self.sequence_window.refresh();self.sequence_window.show();self.sequence_window.raise_();self.sequence_window.activateWindow()

    def schedule_sequence_sync(self):
        if self.sequence_window is not None:self.sequence_sync_timer.start(0)

    def sync_sequence_window(self):
        if self.sequence_window is not None:self.sequence_window.refresh()

    def reselect_card(self,index):
        if index>=0 and index==self.selected and self.baseline!=self.sequence.items[index]:
            self.select_motion(index)

    def select_from_sequence_window(self,index,rows):
        if self.loading or self.sequence_locked():
            self.sync_sequence_window();return
        if index!=self.selected:
            self.select_motion(index)
            if self.selected!=index:
                self.sequence_window.list._end_drag();self.sync_sequence_window();return
        with QSignalBlocker(self.list):
            self.list.setCurrentRow(index,QItemSelectionModel.SelectionFlag.NoUpdate)
            self.list.clearSelection()
            for row in rows:self.list.item(row).setSelected(True)
        self.refresh_actions()

    def copy_selected(self):
        if self.selected>=0:
            QApplication.clipboard().setText(call_code(self.sequence.items[self.selected]));self.notice.setText("선택 동작 코드를 복사했습니다.")
    def show_code(self):
        if self.sequence.items:
            self.code_dialog=CodeDialog(self.sequence.items,self);self.code_dialog.open()
    def refresh_playback_actions(self):
        active=self.sequence_locked() or self.remote.busy
        self.play_from_start.setEnabled(bool(self.sequence.items) and not active)
        self.play_from_current.setEnabled(bool(self.list.selected_rows()) and self.selected>=0 and not active)
        self.play_stop.setEnabled(self.playback is not None or getattr(self,"sound_continuous",False))
        self.repeat_playback.setEnabled(not active)

    def start_playback(self,from_current=False):
        if self.sequence_locked() or self.remote.busy or not self.sequence.items:return
        index=self.selected if from_current else 0
        if index<0 or (from_current and not self.list.selected_rows()):return
        if not self.confirm_discard():return
        try:
            playback=MotionPlayback(self.sequence.items,index,[s.value() for s in self.spins],self.led_state,repeat=self.repeat_playback.isChecked())
        except ValueError as exc:
            self.playback_status.setText(str(exc));return
        self.stop_sound()
        self.playback=playback
        # Keep keyboard focus in the visible sequence toolbar while editing is locked.
        self.play_stop.setEnabled(True)
        self.play_stop.setFocus(Qt.FocusReason.OtherFocusReason)
        self.listen_button.setEnabled(False);self.sound_stop_button.setEnabled(False)
        self.play_started=perf_counter();self.playing_row=-1;self.playing_sound=None
        self.viewport.drag=None;self.viewport.previewing=True
        self.controls.setEnabled(False);self.list.setEnabled(False)
        self.refresh_actions()
        self.notice.setText("미리보기 재생 중 · 저장된 동작은 변경되지 않습니다.")
        self._play_tick()
        if self.playback is not None:self.play_timer.start()

    def _play_tick(self):
        if self.playback is None:return
        frame=self.playback.frame((perf_counter()-self.play_started)*1000)
        index=frame.index;motion=self.playback.motions[index]
        # Preserve already completed output states even if the next sound fails.
        values=tuple(round(p) for p in frame.pulses)
        self.loading=True
        for spin,value in zip(self.spins,values):spin.setValue(value)
        self.loading=False
        self.viewport.set_pulses(values);self.set_led_preview(frame.led)
        if index!=self.playing_row:
            if self.playing_row>=0:self.list.item(self.playing_row).setData(Qt.ItemDataRole.UserRole+1,False)
            self.playing_row=index
            self.list.item(index).setData(Qt.ItemDataRole.UserRole+1,True)
            with QSignalBlocker(self.list):self.list.setCurrentRow(index)
            self.selected=index;self.load_motion(motion)
            self.preview.setPlainText(call_code(motion));self.list.scrollToItem(self.list.item(index))
        sound_key=(frame.buzzer_cycle,frame.buzzer_index,frame.buzzer)
        if sound_key != self.playing_sound:
            self.playing_sound=sound_key
            self.stop_sound()
            if frame.buzzer is not None:
                sound=frame.buzzer
                if not self.play_sound(sound.frequency,frame.buzzer_remaining,sound.continuous):
                    error=self.audio_status.text()
                    self.stop_playback();self.audio_status.setText(error)
                    self.playback_status.setText("재생 중단 · "+error);return
        self.loading=True
        values=tuple(round(p) for p in frame.pulses)
        for spin,value in zip(self.spins,values):spin.setValue(value)
        self.loading=False
        self.viewport.set_pulses(values);self.set_led_preview(frame.led)
        prefix=f"반복 {frame.cycle+1}회차" if self.playback.repeat else "재생 중"
        self.playback_status.setText(f"{prefix} · {index+1}/{len(self.playback.motions)} · {motion.name}")
        self.schedule_sequence_sync()
        if frame.finished:self.stop_playback(completed=True)

    def stop_playback(self,completed=False):
        if self.playback is None:
            self.stop_sound();return
        self.play_timer.stop()
        if not (completed and getattr(self,"sound_continuous",False)):self.stop_sound()
        if self.playing_row>=0:self.list.item(self.playing_row).setData(Qt.ItemDataRole.UserRole+1,False)
        self.playback=None;self.playing_row=-1;self.viewport.previewing=False
        if not completed and 0<=self.selected<len(self.sequence.items):
            self.load_motion(self.sequence.items[self.selected])
        self.preview_stack.setCurrentIndex(self.tabs.currentIndex())
        self.controls.setEnabled(True);self.list.setEnabled(True);self.listen_button.setEnabled(True)
        self.sound_stop_button.setEnabled(getattr(self,"sound_continuous",False))
        if self.play_stop.hasFocus():
            self.play_from_start.setEnabled(True)
            self.play_from_start.setFocus(Qt.FocusReason.OtherFocusReason)
        self.refresh_actions()
        self.playback_status.setText(("재생 완료 · 연속 부저 유지 / 정지 버튼으로 종료" if getattr(self,"sound_continuous",False) else "재생 완료 · 마지막 자세 유지") if completed else "재생 정지 · 선택 카드 최종값 표시")

    def closeEvent(self,event):
        if not self.force_close and not self.protect_document(closing=True):
            event.ignore();return
        if self.defer_remote_close():event.ignore();return
        self.remote_timer.stop()
        self.play_timer.stop();self.playback=None;self.stop_sound()
        if hasattr(self.audio,"close"):
            try:self.audio.close()
            except (OSError,RuntimeError) as exc:self.audio_status.setText(str(exc))
        self.sequence_sync_timer.stop()
        if self.sequence_window is not None:self.sequence_window.close()
        self.viewport.shutdown();event.accept()
