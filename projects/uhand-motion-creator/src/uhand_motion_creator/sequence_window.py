"""Modeless sequence rows sharing the main editor's sequence and selection."""
from .shortcuts import HISTORY_KEYS, MODIFIER, PREFIX
from PySide6.QtCore import Qt,Signal,QSize,QSignalBlocker,QItemSelectionModel
from PySide6.QtGui import QPainter,QColor,QPen
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QListWidgetItem,QListView,QAbstractItemView,QStyledItemDelegate,QStyle
from .motion_list import MotionList
from .motion import Motion,Buzzer,kind,call_code
from .style import STYLE

def columns(width):
    return (8,64,244,334,max(470,width-140),width-8)

def values(item):
    if isinstance(item,Motion):params=" / ".join(f"{name} {p}" for name,p in zip(("F1","F2","F3","F4","F5","W"),item.pulses))
    elif isinstance(item,Buzzer):params=("무음" if item.frequency == 0 else f"{item.frequency} Hz") + (" · 연속" if item.continuous else "")
    else:params=f"RGB {item.red}, {item.green}, {item.blue} · {item.brightness}%"
    return item.name,("손동작","부저","삼색 LED")[kind(item)],params, "즉시 적용" if isinstance(item,Buzzer) and item.continuous else (f"{item.running_time} ms" if item.running_time else "즉시 적용")

class RowDelegate(QStyledItemDelegate):
    def paint(self,painter,option,index):
        painter.save()
        selected=bool(option.state & QStyle.StateFlag.State_Selected)
        playing=bool(index.data(Qt.ItemDataRole.UserRole+1))
        rect=option.rect
        painter.fillRect(rect,QColor("#ffffff" if index.row()%2==0 else "#f7f9fd"))
        if selected or playing:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setBrush(QColor("#fff1d2" if playing else "#dce8ff"))
            painter.setPen(QPen(QColor("#e59217" if playing else "#386bff"),2))
            painter.drawRoundedRect(rect.adjusted(2,2,-2,-2),6,6)
        else:
            painter.setPen(QColor("#e1e8f3"));painter.drawLine(rect.bottomLeft(),rect.bottomRight())
        item=index.data(Qt.ItemDataRole.UserRole)
        texts=(f"{index.row()+1:02d}",*values(item))
        edges=columns(rect.width())
        for col,text in enumerate(texts):
            box=rect.adjusted(edges[col],0,-(rect.width()-edges[col+1]+10),0)
            painter.setPen(QColor("#182a45" if col!=1 else "#245eea"))
            painter.drawText(box,Qt.AlignmentFlag.AlignVCenter,option.fontMetrics.elidedText(text,Qt.TextElideMode.ElideRight,box.width()))
        painter.restore()

class RowList(MotionList):
    selectionRequested=Signal(int,object)
    def __init__(self,parent=None):
        super().__init__(parent,vertical=True)
        self.setViewMode(QListView.ViewMode.ListMode)
        self.setFlow(QListView.Flow.TopToBottom);self.setWrapping(False)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setMovement(QListView.Movement.Static);self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setItemDelegate(RowDelegate(self));self.setUniformItemSizes(True)
    def mousePressEvent(self,event):
        super().mousePressEvent(event)
        self.selectionRequested.emit(self.currentRow(),self.selected_rows())
    def mouseReleaseEvent(self,event):
        was_dragging=self._source>=0
        super().mouseReleaseEvent(event)
        # Reordering has already selected the new positions in the shared editor.
        if not was_dragging:self.selectionRequested.emit(self.currentRow(),self.selected_rows())
    def keyPressEvent(self,event):
        if self.shortcut_action(event):
            super().keyPressEvent(event);return
        super().keyPressEvent(event)
        self.selectionRequested.emit(self.currentRow(),self.selected_rows())

class SequenceWindow(QDialog):
    def __init__(self,editor):
        super().__init__(editor)
        self.editor=editor;self.items=None;self.setWindowTitle("동작 시퀀스 · 리스트 보기")
        # Share the existing actions so both windows use the same history and guards.
        self.addActions((editor.undo_action, editor.redo_action, *editor.file_actions))
        self.setModal(False);self.resize(1100,560);self.setMinimumSize(850,360);self.setStyleSheet(STYLE)
        layout=QVBoxLayout(self);layout.setContentsMargins(18,16,18,16);layout.setSpacing(10)
        row=QHBoxLayout();self.title=QLabel("동작 시퀀스");self.title.setObjectName("section");row.addWidget(self.title);row.addStretch()
        self.up=QPushButton("↑");self.down=QPushButton("↓");self.remove=QPushButton("선택 삭제")
        self.up.setToolTip("현재 동작 한 개를 앞으로 이동");self.down.setToolTip("현재 동작 한 개를 뒤로 이동")
        for b in (self.up,self.down,self.remove):row.addWidget(b)
        layout.addLayout(row)
        self.help=QLabel(f"Shift: 범위 선택 · {MODIFIER}: 개별 선택 · 드래그: 함께 이동 · Delete: 삭제 · {PREFIX}C/X/V: 복사/잘라내기/붙여넣기 · {HISTORY_KEYS}: 실행 취소/다시 실행")
        self.help.setWordWrap(True)
        self.help.setObjectName("muted");layout.addWidget(self.help)
        # A matching delegate keeps column headings aligned when the window resizes.
        self.header=RowHeader();layout.addWidget(self.header)
        self.list=RowList();layout.addWidget(self.list,1)
        self.status=QLabel();self.status.setWordWrap(True);self.status.setObjectName("notice");layout.addWidget(self.status)
        close=QPushButton("닫기");close.clicked.connect(self.close);row=QHBoxLayout();row.addStretch();row.addWidget(close);layout.addLayout(row)
        self.list.selectionRequested.connect(editor.select_from_sequence_window)
        self.list.itemClicked.connect(lambda item:editor.reselect_card(self.list.row(item)))
        self.list.reorderRequested.connect(lambda rows,slot:editor.reorder_motion(rows,slot,focus=False))
        self.list.commandRequested.connect(lambda action:editor.card_command(action,self.list))
        self.remove.clicked.connect(editor.delete_motion)
        self.up.clicked.connect(lambda:editor.move_motion(-1));self.down.clicked.connect(lambda:editor.move_motion(1))
    def update_row(self, row, item):
        row.setData(Qt.ItemDataRole.UserRole, item)
        row.setSizeHint(QSize(0,46))
        row.setToolTip(item.name+"\n"+call_code(item))

    def sync_items(self, items):
        """Return whether new rows need revealing; avoid resetting edit/insert views."""
        previous = self.items
        if previous == items:return False
        self.list._end_drag()
        self.items = items
        if previous is not None and len(previous) == len(items):
            for index, item in enumerate(items):
                if previous[index] != item:self.update_row(self.list.item(index), item)
            return False
        if previous is not None and len(items) > len(previous):
            start = 0
            while start < len(previous) and previous[start] == items[start]:start += 1
            count = len(items)-len(previous)
            if previous[start:] == items[start+count:]:
                for index in range(start, start+count):
                    row = QListWidgetItem();self.update_row(row, items[index])
                    self.list.insertItem(index, row)
                return True
        # Deletion, reload and history changes retain the existing selection policy.
        scroll = self.list.verticalScrollBar().value()
        self.list.clear()
        for item in items:
            row = QListWidgetItem();self.update_row(row, item);self.list.addItem(row)
        self.list.doItemsLayout()
        self.list.verticalScrollBar().setValue(scroll)
        return True

    def refresh(self):
        e=self.editor;rows=e.list.selected_rows();current=e.selected;active=e.sequence_locked()
        changed=self.list.currentRow()!=current
        auto_scroll=self.list.hasAutoScroll()
        self.list.setAutoScroll(False)
        try:
            with QSignalBlocker(self.list):
                reveal=self.sync_items(e.sequence.items)
                if self.list.currentRow()!=current:
                    self.list.setCurrentRow(current,QItemSelectionModel.SelectionFlag.NoUpdate)
                if self.list.selected_rows()!=rows:
                    self.list.clearSelection()
                    for row in rows:self.list.item(row).setSelected(True)
                for row in range(self.list.count()):
                    playing=row==e.playing_row
                    if self.list.item(row).data(Qt.ItemDataRole.UserRole+1)!=playing:
                        self.list.item(row).setData(Qt.ItemDataRole.UserRole+1,playing)
                self.list.doItemsLayout()
                if (changed or reveal) and current>=0:
                    rect=self.list.visualItemRect(self.list.item(current))
                    bottom=self.list.viewport().rect().bottom()
                    delta=rect.top() if rect.top()<0 else max(0,rect.bottom()-bottom)
                    bar=self.list.verticalScrollBar();bar.setValue(bar.value()+delta)
        finally:
            self.list.setAutoScroll(auto_scroll)
        self.title.setText(f"동작 시퀀스 ({len(self.items):,}) · {e.remaining_label.text()}")
        self.list.setEnabled(not e.is_running())
        self.list.set_read_only(e.live.active)
        self.remove.setText(f"선택 삭제 ({len(rows)})" if rows else "선택 삭제")
        self.remove.setMinimumWidth(max(124,self.remove.fontMetrics().horizontalAdvance(self.remove.text())+26))
        self.remove.setEnabled(bool(rows) and not active)
        self.up.setEnabled(not active and current>0);self.down.setEnabled(not active and 0<=current<len(self.items)-1)
        self.status.setText("실시간 제어 중 · 목록 읽기 전용" if e.live.active else "재생 중 · 목록 편집은 잠시 사용할 수 없습니다." if active else
            f"현재 동작 {current+1} · 메인 창의 동작 파라미터에서 수정한 뒤 ‘선택 동작에 적용’을 누르세요." if current>=0 else
            "동작을 선택하면 메인 창에 파라미터를 표시합니다. 선택이 없으면 새 동작은 맨 뒤에 추가됩니다.")
    def closeEvent(self,event):
        self.list._end_drag();super().closeEvent(event)

class RowHeader(QLabel):
    def __init__(self):
        super().__init__();self.setFixedHeight(30)
    def paintEvent(self,event):
        painter=QPainter(self);painter.fillRect(self.rect(),QColor("#eef3fb"));painter.setPen(QColor("#526887"))
        edges=columns(self.width()-2)
        for i,text in enumerate(("순서","동작 이름","종류","파라미터","RunningTime")):
            rect=self.rect().adjusted(edges[i]+1,0,-(self.width()-edges[i+1]+8),0)
            painter.drawText(rect,Qt.AlignmentFlag.AlignVCenter,text)
        painter.end()
