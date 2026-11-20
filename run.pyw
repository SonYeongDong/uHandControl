"""Desktop launcher for the two uHandControl desktop programs."""
from pathlib import Path
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parent
ENV = ROOT / ".venv"
WINDOWS = sys.platform == "win32"
PYTHON = ENV / "Scripts" / "python.exe" if WINDOWS else ENV / "bin" / "python"
GUI_PYTHON = PYTHON.with_name("pythonw.exe") if WINDOWS else PYTHON
READY = ENV / f".uhand-1.0.0-{sys.platform}-desktop1-ready"
LOG = ROOT / "build" / "launcher.log"
PACKAGES = (
    "shared/uhand-server-lifecycle", "shared/uhand-about", "shared/uhand-model",
    "projects/uhand-client-module", "projects/uhand-motion-creator", "projects/uhand-virtual-server",
)
if sys.platform == "darwin":
    PACKAGES += ("shared/uhand-desktop-audio",)
APPS = {"uHandVirtualServer": "uhand_virtual_server", "uHandMotionCreator": "uhand_motion_creator"}


def install_python():
    # pip unpacks deeply nested Qt resources under sys.prefix. An extended
    # executable path also gives the child interpreter an extended sys.prefix.
    path = str(PYTHON)
    if not WINDOWS:
        return path
    if path.startswith("\\\\?\\"):
        return path
    if path.startswith("\\\\"):
        return "\\\\?\\UNC\\" + path[2:]
    return "\\\\?\\" + path


def lock_install(file):
    if WINDOWS:
        import msvcrt
        file.seek(0)
        msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)


def prepare():
    LOG.parent.mkdir(exist_ok=True)
    with (LOG.parent / "install.lock").open("a+b") as lock:
        lock_install(lock)
        if READY.is_file() and PYTHON.is_file():
            return
        if not PYTHON.is_file():
            venv.EnvBuilder(with_pip=True).create(ENV)
        subprocess.run([install_python(), "-m", "pip", "install", "--disable-pip-version-check",
                        "--constraint", str(ROOT / "requirements-runtime.lock"),
                        *PACKAGES], cwd=ROOT, check=True)
        imports = "import uhand_motion_creator.ui, uhand_virtual_server.ui"
        if sys.platform == "darwin":
            imports += ", uhand_desktop_audio, pygame.mixer"
        subprocess.run([str(PYTHON), "-c", imports], cwd=ROOT, check=True)
        READY.touch()


def launch(label):
    with LOG.open("a", encoding="utf-8") as log:
        return subprocess.Popen([str(GUI_PYTHON), "-m", APPS[label]],
                                cwd=ROOT, stdout=log, stderr=log)


def main():
    import tkinter as tk
    from tkinter import messagebox, ttk

    window = tk.Tk()
    window.title("uHandControl 1.0.0")
    if sys.platform not in ("win32", "darwin") or sys.version_info < (3, 13):
        messagebox.showerror("uHandControl", "Windows 또는 macOS용 Python 3.13 이상이 필요합니다.")
        window.destroy()
        return
    if sys.platform == "darwin":
        import platform
        if int(platform.mac_ver()[0].split(".")[0]) < 14:
            messagebox.showerror("uHandControl", "두 GUI를 실행하려면 macOS 14 이상이 필요합니다.")
            window.destroy()
            return
    pane = ttk.Frame(window, padding=20)
    pane.pack(fill="both", expand=True)
    status = tk.StringVar(value="실행할 프로그램을 선택하세요.")
    buttons = []

    def enable():
        for button in buttons:
            button.state(["!disabled"])

    def watch_app(child, label):
        code = child.poll()
        if code is None:
            window.after(1000, watch_app, child, label)
        elif code:
            messagebox.showerror(label, f"프로그램이 종료되었습니다. 로그를 확인하세요.\n{LOG}")

    def start(label):
        for button in buttons:
            button.state(["disabled"])
        status.set("실행 환경을 준비하고 있습니다. 첫 설치에는 인터넷 연결이 필요합니다.")
        try:
            LOG.parent.mkdir(exist_ok=True)
            with LOG.open("a", encoding="utf-8") as log:
                child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--prepare"],
                                         cwd=ROOT, stdout=log, stderr=log,
                                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as error:
            enable()
            status.set("실행 환경을 준비하지 못했습니다.")
            messagebox.showerror(label, str(error))
            return

        def check():
            if child.poll() is None:
                window.after(200, check)
                return
            enable()
            try:
                if child.returncode:
                    raise RuntimeError(f"설치를 완료하지 못했습니다. 다른 설치가 진행 중인지 확인하고 다시 시도하세요.\n{LOG}")
                app = launch(label)
            except (OSError, RuntimeError) as error:
                status.set("실행 준비에 실패했습니다.")
                messagebox.showerror(label, str(error))
                return
            status.set(f"{label} 실행 중 · 다른 프로그램도 열 수 있습니다.")
            window.after(500, watch_app, app, label)
        check()

    for label in APPS:
        button = ttk.Button(pane, text=label, command=lambda name=label: start(name))
        button.pack(fill="x", pady=4)
        buttons.append(button)
    ttk.Label(pane, textvariable=status, wraplength=340).pack(pady=(10, 0))
    window.mainloop()


if __name__ == "__main__":
    if sys.argv[1:] == ["--prepare"]:
        prepare()
    else:
        main()
