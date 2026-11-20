STYLE = """
QMainWindow, QWidget#root, QDialog {background:#f3f6fc;color:#182a45;}
QWidget {font-family:'Segoe UI','Malgun Gothic';font-size:13px;color:#182a45;}
QFrame#card {background:white;border:1px solid #dce4f1;border-radius:12px;}
QLabel {background:transparent;border:none;}
QLabel#title {font-size:23px;font-weight:700;color:#122644;}
QLabel#section {font-size:14px;font-weight:650;}
QLabel#muted {font-size:12px;color:#718098;}
QLabel#notice {font-size:12px;color:#2459d3;}
QPushButton {background:white;border:1px solid #d7e1ef;border-radius:7px;padding:5px 10px;min-height:24px;}
QPushButton:hover:enabled {background:#eaf1ff;border-color:#98b5ed;}
QPushButton:checked:enabled {background:#d5e5ff;border-color:#2d62ee;color:#154ccc;}
QPushButton:focus:enabled {border-color:#315bcc;}
QPushButton:pressed:enabled {background:#3867bd;border-color:#254c92;color:white;}
QPushButton#primary {background:#245df5;color:white;border-color:#245df5;font-weight:600;}
QPushButton#primary:hover:enabled {background:#194dd9;border-color:#194dd9;}
QPushButton#primary:pressed:enabled {background:#10318f;border-color:#0d2876;color:white;}
QPushButton:disabled, QPushButton#primary:disabled {background:#f3f5f9;color:#a2aec1;border-color:#e5eaf1;}
QSpinBox,QLineEdit {background:#f8faff;border:1px solid #d7e1ef;border-radius:5px;padding:5px;min-height:20px;}
QSpinBox:focus,QLineEdit:focus {border-color:#2962ef;}
QSlider::groove:horizontal {height:5px;background:#dde5f3;border-radius:2px;}
QSlider::sub-page:horizontal {background:#2f63f5;border-radius:2px;}
QSlider::handle:horizontal {width:14px;margin:-5px 0;background:white;border:2px solid #366bf6;border-radius:8px;}
QListWidget {border:none;background:white;outline:none;}
QListWidget::item {background:#f5f8fd;border:1px solid #e1e8f3;border-radius:8px;margin:3px;padding:7px;}
QListWidget::item:selected {background:#eaf1ff;border:2px solid #386bff;color:#16419f;}
QPlainTextEdit {background:#f5f8ff;border:1px solid #e0e7f3;border-radius:7px;font-family:'Consolas';font-size:12px;padding:8px;}
QMenuBar {background:#f3f6fc;} QMenu {background:white;border:1px solid #d7e1ef;}
QMenu::item:selected {background:#eaf1ff;}
QScrollBar:horizontal {height:10px;background:#f4f7fc;}
QScrollBar::handle:horizontal {background:#c3d1e8;min-width:24px;border-radius:5px;}
"""
