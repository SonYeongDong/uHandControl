import sys
from PySide6.QtWidgets import QApplication
from .ui import MainWindow
def main():
    if sys.platform not in ("win32", "darwin"):
        raise SystemExit("Windows or macOS is required.")
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Inha.uHandControl.uHandMotionCreator")
    app=QApplication(sys.argv)
    app.setApplicationName("uHandMotionCreator")
    window=MainWindow()
    app.setWindowIcon(window.windowIcon())
    window.show()
    return app.exec()
if __name__=="__main__":
    sys.exit(main())
