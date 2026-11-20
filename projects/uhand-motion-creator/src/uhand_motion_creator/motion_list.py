"""Card selection and in-window group dragging."""
from .shortcuts import MACOS, PREFIX
from PySide6.QtCore import Qt, Signal, QTimer, QEvent, QRect, QItemSelectionModel
from PySide6.QtGui import QPainter, QColor, QPen, QKeySequence
from PySide6.QtWidgets import QListWidget, QApplication

class MotionList(QListWidget):
    reorderRequested=Signal(object,int)
    commandRequested=Signal(str)

    def __init__(self,parent=None,vertical=False):
        super().__init__(parent)
        self.vertical=vertical
        self._pressed_row=-1;self._press=None;self._source=-1;self._snapshot=None
        self._sources=();self._preserve_selection=False
        self._slot=None;self._position=None;self._ghost=None;self._hotspot=None
        self._scroll_timer=QTimer(self);self._scroll_timer.setInterval(60)
        self._scroll_timer.timeout.connect(self._auto_scroll)
        self.setToolTip(f"Shift+클릭으로 범위를 선택한 뒤 끌어 이동합니다. Esc로 취소합니다. Delete: 삭제 · {PREFIX}C/X/V: 복사/잘라내기/붙여넣기.")

    def selected_rows(self):
        return tuple(sorted(self.row(item) for item in self.selectedItems()))

    def _items(self):
        return tuple(self.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.count()))

    def _restore_selection(self,rows):
        self.clearSelection()
        for row in rows:self.item(row).setSelected(True)

    def mousePressEvent(self,event):
        self._end_drag()
        point=event.position().toPoint();row=self.indexAt(point).row()
        before=self.selected_rows();current=self.currentRow()
        preserve=(event.button()==Qt.MouseButton.LeftButton and
                  event.modifiers()==Qt.KeyboardModifier.NoModifier and row in before and
                  current in before and len(before)>1)
        if preserve:
            # Qt's normal press would collapse the group before we can drag it.
            self.setFocus();event.accept();self._preserve_selection=True
        else:
            super().mousePressEvent(event)
            if row>=0 and row!=current and self.currentRow()==current:
                # The editor rejected a selection change to protect an unsaved draft.
                self._restore_selection(before);return
        if event.button()==Qt.MouseButton.LeftButton and row>=0 and row in self.selected_rows():
            self._pressed_row=row;self._press=point;self._sources=self.selected_rows()

    def mouseMoveEvent(self,event):
        point=event.position().toPoint()
        if self._press is not None and event.buttons() & Qt.MouseButton.LeftButton:
            if self._source<0:
                if (point-self._press).manhattanLength()<QApplication.startDragDistance():return
                self._source=self._pressed_row;self._snapshot=self._items()
                rect=self.visualItemRect(self.item(self._source))
                self._ghost=self.viewport().grab(rect);self._hotspot=self._press-rect.topLeft()
                self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
                self._scroll_timer.start()
            self._show_indicator(point);event.accept();return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self,event):
        if self._source>=0:
            sources=self._sources;point=event.position().toPoint()
            valid=(event.button()==Qt.MouseButton.LeftButton and self.viewport().rect().contains(point) and self._snapshot==self._items())
            slot=self.insertion_slot(point)
            self._end_drag();event.accept()
            if valid:self.reorderRequested.emit(sources,slot)
            return
        preserve=self._preserve_selection;row=self._pressed_row;before=self.selected_rows();current=self.currentRow()
        self._end_drag()
        if preserve:
            self.setCurrentRow(row,QItemSelectionModel.SelectionFlag.ClearAndSelect)
            if self.currentRow()==current and row!=current:self._restore_selection(before)
            event.accept();return
        super().mouseReleaseEvent(event)

    @staticmethod
    def shortcut_action(event):
        for key,action in ((QKeySequence.StandardKey.Copy,"copy"),(QKeySequence.StandardKey.Cut,"cut"),(QKeySequence.StandardKey.Paste,"paste")):
            if event.matches(key):return action
        delete_key = event.key() == Qt.Key.Key_Delete or (MACOS and event.key() == Qt.Key.Key_Backspace)
        if delete_key and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            return "delete"
        return None

    def keyPressEvent(self,event):
        action=self.shortcut_action(event)
        if action:
            self._end_drag()
            if self.isEnabled():self.commandRequested.emit(action)
            event.accept();return
        if event.key()==Qt.Key.Key_Escape and self._press is not None:
            self._end_drag();event.accept();return
        super().keyPressEvent(event)

    def event(self,event):
        if event.type()==QEvent.Type.WindowDeactivate and hasattr(self,"_scroll_timer"):
            self._end_drag()
        return super().event(event)

    def insertion_slot(self,point):
        for row in range(self.count()):
            center=self.visualItemRect(self.item(row)).center()
            if (point.y()<center.y() if self.vertical else point.x()<center.x()):return row
        return self.count()

    def _show_indicator(self,point):
        self._position=point
        self._slot=self.insertion_slot(point) if self.viewport().rect().contains(point) else None
        self.viewport().update()

    def _end_drag(self):
        self._scroll_timer.stop();self._position=None;self._slot=None
        self._source=-1;self._snapshot=None;self._press=None;self._pressed_row=-1
        self._sources=();self._preserve_selection=False
        self._ghost=None;self.viewport().unsetCursor();self.viewport().update()

    def _auto_scroll(self):
        if self._position is None or not self.viewport().rect().contains(self._position):return
        x=self._position.y() if self.vertical else self._position.x();width=self.viewport().height() if self.vertical else self.viewport().width()
        delta=-24 if x<32 else 24 if x>width-32 else 0
        if delta:
            bar=self.verticalScrollBar() if self.vertical else self.horizontalScrollBar();bar.setValue(bar.value()+delta)
            self._show_indicator(self._position)

    def paintEvent(self,event):
        super().paintEvent(event)
        if self._slot is None or not self.count():return
        painter=QPainter(self.viewport())
        if self._ghost is not None:
            painter.setOpacity(.65);painter.drawPixmap(self._position-self._hotspot,self._ghost);painter.setOpacity(1)
        row=min(self._slot,self.count()-1);rect=self.visualItemRect(self.item(row))
        x=rect.left() if self._slot<self.count() else rect.right()+1
        x=max(2,min(x,self.viewport().width()-3))
        painter.setPen(QPen(QColor("#2860f6"),3))
        if self.vertical:
            y=rect.top() if self._slot<self.count() else rect.bottom()+1
            y=max(2,min(y,self.viewport().height()-3))
            painter.drawLine(3,y,self.viewport().width()-4,y)
        else:
            painter.drawLine(x,max(3,rect.top()+3),x,min(self.viewport().height()-4,rect.bottom()-3))
        if len(self._sources)>1:
            badge=QRect(min(max(0,self._position.x()+12),self.viewport().width()-96),4,92,26)
            painter.setPen(Qt.PenStyle.NoPen);painter.setBrush(QColor("#2860f6"));painter.drawRoundedRect(badge,6,6)
            painter.setPen(QColor("white"));painter.drawText(badge,Qt.AlignmentFlag.AlignCenter,f"{len(self._sources)}개 이동")
        painter.end()
