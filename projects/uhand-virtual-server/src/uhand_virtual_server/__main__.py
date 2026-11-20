import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description="uHandVirtualServer • Light Studio")
    parser.add_argument("--host", default="127.0.0.1", help="Numeric bind address (default: local PC only)")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()
    from PySide6.QtWidgets import QApplication, QMessageBox
    from .audio import create_audio
    from .server import VirtualServer
    from .ui import MainWindow
    app = QApplication(sys.argv[:1])
    app.setApplicationName("uHandVirtualServer")
    server = VirtualServer(args.host, args.port, audio=create_audio())
    try:
        try:
            server.start(background=True)
        except OSError as exc:
            server.log(f"전원 켜기 실패 · IP와 포트를 확인하세요. {exc}", "error")
        window = MainWindow(server)
    except Exception as exc:
        server.shutdown()
        QMessageBox.critical(None, "uHandVirtualServer 시작 오류", str(exc))
        return 1
    window.show()
    try:
        return app.exec()
    finally:
        server.shutdown()


if __name__ == "__main__":
    sys.exit(main())
