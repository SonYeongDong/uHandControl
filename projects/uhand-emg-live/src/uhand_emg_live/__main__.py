"""uHandEmgLive: armband -> gesture model -> predicted pose -> robot hand, on one screen.

    python -m uhand_emg_live                                 # pick input, model and robot on screen
    python -m uhand_emg_live --demo --model 500그루          # no devices: synthetic signal, on-screen robot only
    python -m uhand_emg_live --replay <session folder> --model random_forest
    python -m uhand_emg_live --port COM4 --model 조승준 --robot real
    python -m uhand_emg_live --port COM4 --model 조승준 --robot real --mode theater     # puppet show
"""
from __future__ import annotations

import argparse
import os
import sys


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="uHandEmgLive • EMG armband -> gesture model -> robot hand")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--port", help="armband serial port, e.g. COM4 (default: the CH340 dongle if one is found)")
    src.add_argument("--replay", metavar="FOLDER", help="play a recorded studio session instead of the armband")
    src.add_argument("--demo", action="store_true", help="synthetic signal, no armband")
    ap.add_argument("--model", help="model to load: any part of its name in the list")
    ap.add_argument("--robot", choices=["off", "virtual", "real"], default="off",
                    help="where to send poses (default off: on-screen simulation only)")
    ap.add_argument("--mode", choices=["follow", "theater"], default="follow",
                    help="follow: the hand copies the wearer (default); theater: play the puppet-show scene files")
    ap.add_argument("--shot", metavar="PNG", help=argparse.SUPPRESS)      # save a picture of the window and quit
    ap.add_argument("--after", type=float, default=6.0, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox

    from . import config
    from .engine import Engine
    from .models import discover
    from .sensor.sources import find_ch340
    from .ui import theme
    from .ui.window import MainWindow

    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Inha.uHandControl.uHandEmgLive")
    qt = QApplication(sys.argv[:1])
    qt.setApplicationName("uHandEmgLive")
    theme.apply(qt)
    try:
        cfg = config.load()
        engine = Engine(cfg)
    except ValueError as e:
        QMessageBox.critical(None, "uHandEmgLive 시작 오류", f"설정 오류: {e}")
        return 2
    specs, problems = discover(config.MODELS_DIR)
    win = MainWindow(engine, specs, problems)
    qt.setWindowIcon(win.windowIcon())
    engine.start()
    win.show()

    if a.model and not win.select_model(a.model):
        print(f"모델을 찾지 못했습니다: {a.model}", file=sys.stderr)
    win.select_robot(a.robot)
    win.select_mode(a.mode)
    if a.demo:
        win.select_input("demo")
    elif a.replay:
        win.select_input("replay", os.path.abspath(a.replay))
    else:
        port = a.port or (cfg["sensor"]["port"] if cfg["sensor"]["port"] != "auto" else None)
        if port is None:
            found = find_ch340()
            port = found[0] if found else None
        if port:
            win.select_input("serial", port)

    if a.shot:
        def shoot() -> None:
            win.grab().save(a.shot)
            win.close()
        QTimer.singleShot(int(a.after * 1000), shoot)
    code = qt.exec()
    engine.close()
    return code


if __name__ == "__main__":
    sys.exit(main())
