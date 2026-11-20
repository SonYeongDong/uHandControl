"""RGB and brightness editor shared by card editing and direct control."""
from PySide6.QtCore import Qt, Signal, QSignalBlocker
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QWidget, QLabel, QPushButton, QSlider, QSpinBox,
                              QHBoxLayout, QVBoxLayout, QGridLayout, QColorDialog)
from .motion import LED


class LedEditor(QWidget):
    changed = Signal()
    presets = (("꺼짐", "#000000"), ("빨강", "#ff0000"), ("초록", "#00ff00"),
               ("파랑", "#0000ff"), ("노랑", "#ffff00"), ("청록", "#00ffff"),
               ("자홍", "#ff00ff"), ("흰색", "#ffffff"))

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(QLabel("기본 색상"))
        presets = QHBoxLayout()
        presets.setSpacing(4)
        for name, hex_color in self.presets:
            button = QPushButton(name)
            foreground = "white" if name in ("꺼짐", "파랑") else "#10131a"
            button.setStyleSheet(f"QPushButton {{background:{hex_color};color:{foreground};"
                                 "border:1px solid #c7cfdb;padding:2px;min-height:20px;}"
                                 "QPushButton:focus, QPushButton:pressed {border:2px solid #627491;}")
            button.clicked.connect(lambda checked=False, c=hex_color: self.set_color(QColor(c)))
            presets.addWidget(button, 1)
        layout.addLayout(presets)
        tools = QHBoxLayout()
        tools.addWidget(QLabel("RGB 채널"))
        tools.addStretch()
        choose = QPushButton("색상 선택…")
        choose.clicked.connect(self.choose_color)
        tools.addWidget(choose)
        layout.addLayout(tools)
        self.spins = []
        grid = QGridLayout()
        grid.setColumnStretch(2, 1)
        grid.setVerticalSpacing(3)
        for row, (name, limit, color) in enumerate((
                ("R  빨강", 255, "#cc4255"), ("G  초록", 255, "#258552"),
                ("B  파랑", 255, "#3763d4"), ("전체 밝기", 100, "#245eea"))):
            spin = QSpinBox()
            spin.setAccessibleName(name)
            spin.setRange(0, limit)
            if row == 3:
                spin.setSuffix("%")
                spin.setValue(100)
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setAccessibleName(name)
            slider.setRange(0, limit)
            slider.setValue(spin.value())
            slider.setStyleSheet(f"QSlider::sub-page:horizontal {{background:{color};}}")
            spin.valueChanged.connect(slider.setValue)
            slider.valueChanged.connect(spin.setValue)
            spin.valueChanged.connect(self.update_color)
            self.spins.append(spin)
            grid.addWidget(QLabel(name), row, 0)
            grid.addWidget(spin, row, 1)
            grid.addWidget(slider, row, 2)
        layout.addLayout(grid)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet("background:#f4f7fc;border-radius:5px;padding:4px;")
        layout.addWidget(self.summary)
        layout.addStretch()
        self.update_color()

    def card(self, name="삼색 LED"):
        r, g, b, brightness = [spin.value() for spin in self.spins]
        return LED(r, g, b, name=name, brightness=brightness)

    def load(self, card):
        with QSignalBlocker(self):
            for spin, value in zip(self.spins, (*card.rgb, card.brightness)):
                spin.setValue(value)
        self.update_color()

    def set_color(self, color):
        if color.isValid():
            self.load(LED(color.red(), color.green(), color.blue(),
                          brightness=self.spins[3].value()))

    def choose_color(self):
        self.set_color(QColorDialog.getColor(QColor(*self.card().rgb), self, "LED 색상 선택"))

    def update_color(self):
        card = self.card()
        def swatch(rgb):
            return f'<span style="color:{QColor(*rgb).name()}">■</span> ' + ", ".join(map(str, rgb))
        self.summary.setText(f"선택 색상 {swatch(card.rgb)}　 LED 1·2 출력색 {swatch(card.output_rgb)}")
        self.changed.emit()
