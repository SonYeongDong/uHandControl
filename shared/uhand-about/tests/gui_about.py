"""Exercise each installed app's About action in its own Windows environment."""
import sys
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QPushButton
from PySide6.QtTest import QTest
from uhand_about import AboutDialog

app = QApplication([])
name = sys.argv[1]
if name == "uHandMotionCreator":
    from uhand_motion_creator.ui import MainWindow
    from uhand_motion_creator import __version__
    window = MainWindow()
    window.force_close = True
else:
    import uhand_client_module as client
    from uhand_virtual_server.ui import MainWindow
    from uhand_virtual_server.server import VirtualServer
    from uhand_virtual_server import __version__
    server = VirtualServer(port=0)
    server.start()
    window = MainWindow(server)
window.show()
QTest.qWait(200)
try:
    action = window.menuBar().actions()[-1]
    assert action.text() == "프로그램 정보"
    bar = window.menuBar()
    QTest.mouseClick(bar, Qt.MouseButton.LeftButton, pos=bar.actionGeometry(action).center())
    QTest.qWait(120)
    dlg = window.findChild(AboutDialog)
    assert dlg is not None and dlg.isVisible() and not dlg.isModal()
    action.trigger()
    assert window.findChildren(AboutDialog) == [dlg]
    labels = dlg.findChildren(QLabel)
    assert {name, "v"+__version__, "U", "Developed by", "2026 Data Science Team 1", "Inha University"} <= {w.text() for w in labels}
    members = sorted(dlg.findChildren(QLabel, "member"), key=lambda w: (w.y(), w.x()))
    assert [w.text() for w in members] == [
        "손영동 (Yeong-dong Son)", "이민지 (Min-ji Lee)", "이상윤 (Sang-yun Lee)",
        "정한결 (Han-gyeol Jeong)", "조승준 (Seung-jun Jo)",
    ]
    expected = "#cc3344" if name == "uHandVirtualServer" else "#245eea"
    for mark in (window.findChild(QLabel, "appLogo"), dlg.findChild(QLabel, "mark")):
        image = mark.grab().toImage()
        assert image.pixelColor(8, image.height()//2).name() == expected
    logo = dlg.findChild(QLabel,"universityLogo")
    assert logo.isVisible() and not logo.pixmap().isNull()
    assert all(dlg.rect().contains(w.geometry()) for w in labels)
    assert all(w.width() >= w.fontMetrics().horizontalAdvance(w.text()) for w in labels if w.text())
    if name == "uHandMotionCreator":
        QTest.mouseClick(window.add_button, Qt.MouseButton.LeftButton)
        assert dlg.isVisible() and len(window.sequence.items) == 1
    else:
        client.Connect(server.host, server.port)
        try:
            client.SetuHandLED(True,False,True)
            assert dlg.isVisible() and client.GetStatus()["LED"] == [255,0,255]
        finally:
            client.Disconnect()
    out = Path(__file__).resolve().parents[3]/"reports/about-design"
    assert dlg.grab().save(str(out/(name+"-installed.png")))
    QTest.keyClick(dlg,Qt.Key.Key_Escape)
    assert not dlg.isVisible()
    action.trigger()
    QTest.mouseClick(dlg.findChild(QPushButton),Qt.MouseButton.LeftButton)
    assert not dlg.isVisible()
    print(name, __version__, "PASS")
finally:
    window.close()
