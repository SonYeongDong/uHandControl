"""Does everything on the screen fit? Run this after any change to src/uhand_emg_live/ui.

    python tools/ui_check.py                          # synthetic signal
    python tools/ui_check.py --session <session dir>  # a recorded studio session (more realistic)

It drives the window through its states (start, forest, CNN calibration, map, errors, puppet
show) at three window sizes, with the real fonts but without showing the window, and reports:
  - text cut off in a label or button, widgets outside their parent, a window that cannot shrink
  - notes (not problems): text shortened with an ellipsis, big text shrunk to fit
It exits with 1 when it finds a problem, and saves a picture of each state under tools/_shots/
(not committed). Text drawn by hand in a paintEvent is NOT measured: look at the pictures for
the custom views (tree, votes, map, robot hand).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))     # the source tree, not an installed copy

from PySide6.QtCore import QEventLoop, Qt, QTimer                      # noqa: E402
from PySide6.QtWidgets import QAbstractButton, QApplication, QComboBox, QLabel, QWidget   # noqa: E402

from uhand_emg_live import config                                                 # noqa: E402
from uhand_emg_live.engine import Engine                                          # noqa: E402
from uhand_emg_live.models import discover                                        # noqa: E402
from uhand_emg_live.ui import theme                                               # noqa: E402
from uhand_emg_live.ui.widgets import ElideLabel, FitLabel                        # noqa: E402
from uhand_emg_live.ui.window import MainWindow                                   # noqa: E402

SMALL, LARGE = (1264, 690), (1700, 800)


def spin(seconds: float) -> None:
    """Let the application run for a while."""
    loop = QEventLoop()
    QTimer.singleShot(int(seconds * 1000), loop.quit)
    loop.exec()


def name_of(w: QWidget) -> str:
    text = ""
    if isinstance(w, (QLabel, QAbstractButton, ElideLabel, FitLabel)):
        text = w.text()
    elif isinstance(w, QComboBox):
        text = w.currentText()
    text = re.sub(r"<[^>]+>", "", text).replace("\n", " / ")
    return f"{type(w).__name__}({text[:40]!r})"


def check(win: MainWindow, tag: str) -> int:
    """Print what does not fit right now. -> number of problems."""
    bad, info = [], []
    for w in win.centralWidget().findChildren(QWidget):
        if not w.isVisibleTo(win) or type(w).__module__.startswith("pyqtgraph"):
            continue
        par = w.parentWidget()
        if par is not None and "pyqtgraph" not in type(par).__module__ and type(par).__name__ != "QStackedWidget"                 and par.objectName() != "qt_scrollarea_viewport" \
                and w.geometry().width() > 0 and not par.rect().adjusted(-1, -1, 1, 1).contains(w.geometry()):
            g = w.geometry()
            bad.append(f"outside its parent: {name_of(w)} at {g.x()},{g.y()} {g.width()}x{g.height()} "
                       f"in {par.width()}x{par.height()}")
        if isinstance(w, QLabel) and w.text():
            if w.wordWrap():
                need = w.heightForWidth(w.width())
                if need > w.height() + 1:
                    bad.append(f"text cut off (needs {need}px height, has {w.height()}): {name_of(w)}")
            elif w.sizeHint().width() > w.width() + 1:
                bad.append(f"text cut off (needs {w.sizeHint().width()}px width, has {w.width()}): {name_of(w)}")
        elif isinstance(w, QAbstractButton) and w.text() and w.sizeHint().width() > w.width() + 1:
            bad.append(f"button text cut off: {name_of(w)}")
        elif isinstance(w, FitLabel):
            size = w.fitted_size()
            if size <= 8:
                bad.append(f"big text does not fit even at the smallest font: {name_of(w)}")
            elif size < w._pt:
                info.append(f"shrunk {w._pt}->{size:.0f}pt: {name_of(w)}")
        elif isinstance(w, ElideLabel):
            if w.fontMetrics().horizontalAdvance(w.text()) > w.width():
                info.append(f"shortened with an ellipsis: {name_of(w)}")
        elif isinstance(w, QComboBox) and w.fontMetrics().horizontalAdvance(w.currentText()) > w.width() - 28:
            info.append(f"list text shortened: {name_of(w)}")
    for line in bad:
        print(f"  [PROBLEM] {tag}: {line}")
    for line in info:
        print(f"  [note]    {tag}: {line}")
    return len(bad)


def scene_file(folder: str, number: int, cards: list[dict]) -> None:
    doc = {"format": "uhand-motion-sequence", "schema_version": 2,
           "units": {"pulse": "us", "running_time": "ms", "frequency": "Hz"}, "cards": cards}
    with open(os.path.join(folder, f"action_{number:02d}.uhjson"), "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False)


def main() -> int:
    ap = argparse.ArgumentParser(description="check that the window's contents fit, in every state")
    ap.add_argument("--session", help="recorded studio session to play (default: the synthetic demo signal)")
    ap.add_argument("--out", default=os.path.join(ROOT, "tools", "_shots"), help="where to save the pictures")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")     # labels hold symbols a Korean console cannot print

    qt = QApplication([])
    theme.apply(qt)
    screen = qt.primaryScreen().availableGeometry()
    print(f"screen available: {screen.width()} x {screen.height()}")
    eng = Engine(config.load())
    specs, problems = discover(config.MODELS_DIR)
    win = MainWindow(eng, specs, problems)
    win.setAttribute(Qt.WA_DontShowOnScreen)         # real fonts and layout, nothing on the user's screen
    eng.start()
    win.show()
    sizes = {"default": (win.width(), win.height()), "small": SMALL, "large": LARGE}
    least = win.centralWidget().minimumSizeHint()
    print(f"window opens at {win.width()} x {win.height()}; its content can shrink to {least.width()} x {least.height()}")
    total = 0

    def signal() -> None:
        eng.link.close()
        if a.session:
            win.select_input("replay", os.path.abspath(a.session))
        else:
            win.select_input("demo")

    def state(tag: str, shots=("default",)) -> None:
        nonlocal total
        for size_name, (w, h) in sizes.items():
            win.resize(w, h)
            spin(0.35)
            label = f"{tag} @ {size_name} {win.width()}x{win.height()}"
            if (win.width(), win.height()) != (w, h):
                print(f"  [PROBLEM] {label}: the window refused to be {w}x{h}")
                total += 1
            total += check(win, label)
            if size_name in shots:
                win.grab().save(os.path.join(a.out, f"{tag}_{size_name}.png"))
        print(f"checked: {tag}")

    # A. just started: nothing connected, no model
    spin(1.0)
    state("A_start")

    # B. signal in, random forest
    win.select_model("500그루")
    signal()
    spin(7.0)
    state("B_forest", shots=("default", "small"))

    # C. CNN with the longest name; calibration running: first the long rest text, then a gesture
    win.select_model("시연용")
    spin(2.0)
    eng.start_calibration()
    spin(1.0)
    state("C1_calib_rest")
    spin(2.8)
    state("C2_calib_gesture")
    eng.cancel_calibration()
    spin(3.0)
    state("C3_cnn_map", shots=("default", "small"))

    # C4-C5. SVM: nothing before its rest-only calibration, then its duel view
    win.select_model("emg_svm")
    spin(1.5)
    state("C4_svm_uncalibrated")
    eng.model.calibration_rest_s = 4.0
    eng.start_calibration()
    spin(6.5)
    state("C5_svm_duels", shots=("default", "small"))

    # D. numbers model, robot address that nothing answers on (long error text)
    win.select_model("숫자0-5_전체")
    eng.link.close()
    win.select_input("demo")
    eng.sender.set_endpoint(("127.0.0.1", 1))
    spin(8.0)
    state("D_numbers_robot_error", shots=("default", "small"))

    # E. armband errors: a port that does not exist, then ASCII mode
    eng.link.close()
    eng.link.open_serial("COM99")
    spin(2.0)
    state("E1_port_error", shots=("default", "small"))
    eng.link.close()
    eng.link.open_demo("ascii")
    spin(3.0)
    state("E2_ascii_mode")

    # F. puppet show, with scene files made here: two good, one damaged, the rest missing
    scene_dir = os.path.join(a.out, "scenes")
    os.makedirs(scene_dir, exist_ok=True)
    wave = [{"name": "초록", "kind": "led", "red": 0, "green": 255, "blue": 80, "brightness": 60},
            {"name": "펴기", "kind": "motion", "pulses": [800, 2000, 2000, 2000, 2000, 1000], "running_time": 400},
            {"name": "삐", "kind": "buzzer", "frequency": 523, "running_time": 200, "continuous": False},
            {"name": "돌리기", "kind": "motion", "pulses": [800, 2000, 2000, 2000, 2000, 2000], "running_time": 400}]
    scene_file(scene_dir, 0, wave)                   # rest
    scene_file(scene_dir, 2, wave[:2])               # radial_dev
    scene_file(scene_dir, 6, [{"name": "잘못", "kind": "motion", "pulses": [9999, 800, 800, 800, 800, 1500],
                               "running_time": 300}])                    # fist: thumb out of range
    set_dir = os.path.join(scene_dir, "인형 동작")     # a second set to switch to
    os.makedirs(set_dir, exist_ok=True)
    scene_file(set_dir, 0, wave)
    eng.cfg["theater"]["folder"] = scene_dir
    eng.sender.set_endpoint(None)
    win.select_model("500그루")
    signal()
    win.select_mode("theater")
    spin(9.0)
    state("F_theater", shots=("default", "small"))
    win.select_mode("follow")
    spin(1.0)
    state("G_back_to_follow")

    print(f"\nPROBLEMS: {total}   (pictures: {a.out})")
    win.close()
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
