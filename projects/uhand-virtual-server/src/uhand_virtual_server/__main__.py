import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description="uHandVirtualServer • Light Studio")
    parser.add_argument("--host", default="127.0.0.1", help="Numeric bind address (default: local PC only)")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()
    from PySide6.QtWidgets import QApplication, QMessageBox
    from .desktop_server import DesktopServer
    from .ui import MainWindow
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Inha.uHandControl.uHandVirtualServer")
    app = QApplication(sys.argv[:1])
    app.setApplicationName("uHandVirtualServer")
    server = None
    try:
        server = DesktopServer(args.host, args.port)
        try:
            server.start(background=True)
        except OSError as exc:
            server.log(f"전원 켜기 실패 · IP와 포트를 확인하세요. {exc}", "error")
        window = MainWindow(server)
    except Exception as exc:
        if server is not None:
            server.shutdown()
        QMessageBox.critical(None, "uHandVirtualServer 시작 오류", str(exc))
        return 1
    app.setWindowIcon(window.windowIcon())
    window.show()
    try:
        return app.exec()
    finally:
        server.shutdown()


if __name__ == "__main__":
    sys.exit(main())
