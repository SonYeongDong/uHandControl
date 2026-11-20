"""Pulse editor with axis-specific limits and explicit invalid-input feedback."""
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QValidator
from PySide6.QtWidgets import QSpinBox


class PulseSpinBox(QSpinBox):
    inputRejected = Signal(str)

    def __init__(self, axis_name, limits):
        super().__init__()
        self.axis_name = axis_name
        self.setRange(*limits)
        self.setToolTip(f"{axis_name}: {limits[0]}~{limits[1]} 정수")

    def error_text(self):
        return f"{self.axis_name}: {self.minimum()}~{self.maximum()} 정수만 입력하세요."

    def setValue(self, value):
        if type(value) is not int or not self.minimum() <= value <= self.maximum():
            raise ValueError(self.error_text())
        super().setValue(value)

    def validate(self, text, pos):
        result = super().validate(text, pos)
        if self.hasFocus() and text.strip().lstrip("-").isdigit():
            value = int(text)
            if not self.minimum() <= value <= self.maximum() and len(text.strip()) >= len(str(self.minimum())):
                self.inputRejected.emit(self.error_text())
        return result

    def fixup(self, text):
        self.inputRejected.emit(self.error_text())
        return str(self.value())

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not self.hasAcceptableInput():
            self.inputRejected.emit(self.error_text())
            self.lineEdit().setText(str(self.value()))
            event.accept()
            return
        super().keyPressEvent(event)
