"""Modeless program information shared by the two Windows applications."""
from importlib.resources import files

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)


def product_logo(parent, size, object_name):
    mark = QLabel(parent)
    mark.setObjectName(object_name)
    mark.setFixedSize(size, size)
    mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
    mark.setAccessibleName(parent.windowTitle())
    mark.setPixmap(parent.windowIcon().pixmap(mark.size(), mark.devicePixelRatioF()))
    return mark


class AboutDialog(QDialog):
    def __init__(self, parent, name, description, version, logo_color="#245eea"):
        super().__init__(parent)
        self.setWindowTitle("프로그램 정보")
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setStyleSheet("""
            QDialog { background: white; color: #182a45; }
            QLabel { color: #182a45; background: transparent; font-size: 14px; }
            QLabel#product { font-size: 26px; font-weight: 700; }
            QLabel#team { font-size: 20px; font-weight: 650; }
            QLabel#secondary { color: #556a82; }
            QLabel#mark { color: white; border: 1px solid #cbd5e1; border-radius: 13px;
                          font-size: 34px; font-weight: 700; }
            QFrame#roster { background: #f4f7fc; border-radius: 8px; }
            QLabel#rosterTitle { color: #526681; font-size: 13px; font-weight: 600; }
            QLabel#member { font-size: 15px; }
            QFrame#rule { background: #dce4ef; border: none; }
            QPushButton { background: #245eea; color: white; border-radius: 6px;
                          min-width: 70px; padding: 5px 12px; }
            QPushButton:pressed { background: #194dd0; }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(18)
        header = QHBoxLayout()
        header.setSpacing(16)
        mark = product_logo(parent, 62, "mark")
        if parent.windowIcon().isNull():
            mark.setText("U")
            mark.setStyleSheet(f"background-color: {logo_color};")
        else:
            mark.setStyleSheet("border: none; background: transparent;")
        mark.setAccessibleName(name)
        header.addWidget(mark)
        titles = QVBoxLayout()
        titles.setSpacing(3)
        for text, key in ((name, "product"), (description, "secondary"), (f"v{version}", "secondary")):
            label = QLabel(text)
            label.setObjectName(key)
            titles.addWidget(label)
        header.addLayout(titles)
        header.addStretch()
        layout.addLayout(header)

        rule = QFrame()
        rule.setObjectName("rule")
        rule.setFixedHeight(1)
        layout.addWidget(rule)
        credit = QHBoxLayout()
        credit.setSpacing(18)
        pixmap = QPixmap()
        if not pixmap.loadFromData(files(__package__).joinpath("inha-horizontal.png").read_bytes()):
            raise ValueError("인하대학교 로고를 읽을 수 없습니다.")
        logo = QLabel()
        logo.setObjectName("universityLogo")
        logo.setAccessibleName("인하대학교 로고")
        logo.setPixmap(pixmap.scaledToWidth(207, Qt.TransformationMode.SmoothTransformation))
        credit.addWidget(logo)
        divider = QFrame()
        divider.setObjectName("rule")
        divider.setFixedSize(1, 48)
        credit.addWidget(divider)
        byline = QVBoxLayout()
        byline.setSpacing(2)
        for text, key in (("Developed by", "secondary"), ("2026 Data Science Team 1", "team"),
                          ("Inha University", "secondary")):
            label = QLabel(text)
            label.setObjectName(key)
            byline.addWidget(label)
        credit.addLayout(byline)
        credit.addStretch()
        layout.addLayout(credit)

        roster = QFrame()
        roster.setObjectName("roster")
        roster_layout = QVBoxLayout(roster)
        roster_layout.setContentsMargins(16, 12, 16, 13)
        roster_layout.setSpacing(6)
        heading = QLabel("Team Members")
        heading.setObjectName("rosterTitle")
        roster_layout.addWidget(heading)
        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(4)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        members = (
            "손영동 (Yeong-dong Son)", "이민지 (Min-ji Lee)",
            "이상윤 (Sang-yun Lee)", "정한결 (Han-gyeol Jeong)",
            "조승준 (Seung-jun Jo)",
        )
        for index, text in enumerate(members):
            member = QLabel(text)
            member.setObjectName("member")
            grid.addWidget(member, *divmod(index, 2))
        roster_layout.addLayout(grid)
        layout.addWidget(roster)
        layout.addStretch()
        close = QPushButton("닫기")
        close.setDefault(True)
        close.clicked.connect(self.accept)
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)
        self.resize(558, 382)


def add_about_action(window, name, description, version, logo_color="#245eea"):
    dialog = None

    def show_about():
        nonlocal dialog
        if dialog is None:
            dialog = AboutDialog(window, name, description, version, logo_color)
        dialog.showNormal()
        dialog.raise_()
        dialog.activateWindow()

    action = window.menuBar().addAction("프로그램 정보")
    action.triggered.connect(show_about)
