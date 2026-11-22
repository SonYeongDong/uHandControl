"""Desktop launcher for the two uHandControl desktop programs."""
from contextlib import nullcontext
from pathlib import Path
from queue import Empty, SimpleQueue
from threading import Event, Thread
import os
import shutil
import subprocess
import tempfile
import sys
import venv
import webbrowser
import tkinter as tk

ROOT = Path(__file__).resolve().parent
VERSION = "1.0.1"
REPOSITORY_URL = "https://github.com/SonYeongDong/uHandControl"
BG = "#f3f6fc"
ICON = ROOT / "assets" / "uHandControlLauncher.png"
ENV = ROOT / ".venv"
WINDOWS = sys.platform == "win32"
MACOS = sys.platform == "darwin"
PYTHON = ENV / "Scripts" / "python.exe" if WINDOWS else ENV / "bin" / "python"
GUI_PYTHON = PYTHON.with_name("pythonw.exe") if WINDOWS else PYTHON
READY = ENV / f".uhand-{VERSION}-{sys.platform}-desktop4-ready"
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
        # setuptools builds local wheels relative to the source directory. A long
        # checkout path can exceed MAX_PATH there even with an extended venv path.
        work = tempfile.TemporaryDirectory(prefix="uh-") if WINDOWS else nullcontext(ROOT)
        with work as build_root:
            if WINDOWS:
                for package in PACKAGES:
                    shutil.copytree(ROOT / package, Path(build_root) / package,
                                    ignore=shutil.ignore_patterns("build", "dist", "*.egg-info",
                                                                 "__pycache__", ".venv"))
            subprocess.run([install_python(), "-m", "pip", "install", "--disable-pip-version-check",
                            "--constraint", str(ROOT / "requirements-runtime.lock"),
                            *PACKAGES], cwd=build_root, check=True)
        imports = "import uhand_motion_creator.ui, uhand_virtual_server.ui"
        if sys.platform == "darwin":
            imports += ", uhand_desktop_audio, pygame.mixer"
        subprocess.run([str(PYTHON), "-c", imports], cwd=ROOT, check=True)
        READY.touch()


WINDOWS_HOSTS = ROOT / "build" / "windows-apps"
LAUNCHER_NAME = "uHandControlLauncher"


def windows_command(name, args):
    from windows_app_host import host_command

    if name == LAUNCHER_NAME:
        base = Path(sys.base_prefix)
        interpreter = Path(sys.executable).with_name("pythonw.exe")
    else:
        # The project venv may have been prepared by a different Python installation.
        config = dict(line.split(" = ", 1) for line in (ENV / "pyvenv.cfg").read_text(
            encoding="utf-8").splitlines() if " = " in line)
        base = Path(config["home"])
        interpreter = GUI_PYTHON
    icons = [(LAUNCHER_NAME, ICON.with_suffix(".ico"))]
    for label, package in APPS.items():
        path = ROOT / "projects" / package.replace("_", "-") / "src" / package
        icons.append((label, path / (label + ".ico")))
    return host_command(name, base, interpreter, WINDOWS_HOSTS, tuple(icons), VERSION, args)


def macos_command(name):
    from macos_app_host import app_command

    module = APPS.get(name)
    if name == LAUNCHER_NAME:
        icon = ICON.with_suffix(".ico")
        interpreter = Path(sys.executable)
    else:
        icon = ROOT / "projects" / module.replace("_", "-") / "src" / module / (name + ".ico")
        interpreter = GUI_PYTHON
    return app_command(ROOT, name, module, interpreter, icon, VERSION)


def launch(label):
    with LOG.open("a", encoding="utf-8") as log:
        args = ["-m", APPS[label]]
        if WINDOWS:
            command, env = windows_command(label, args)
        elif MACOS:
            command, env = macos_command(label), None
        else:
            command, env = [str(GUI_PYTHON), *args], None
        return subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=log)


def running_instances():
    """Find the GUI launched by -m in this installation, including earlier sessions."""
    instances = {label: set() for label in APPS}
    labels = {module: label for label, module in APPS.items()}
    if WINDOWS:
        import _wmi  # Included with CPython on Windows.
        executable = str(GUI_PYTHON).replace("\\", "\\\\")
        names = " OR ".join(f'Name="{label}.exe"' for label in APPS)
        query = ('SELECT ProcessId,ExecutablePath,CommandLine FROM Win32_Process '
                 f'WHERE (Name="pythonw.exe" AND ExecutablePath="{executable}") OR ({names})')
        for row in _wmi.exec_query(query).split("\0\0"):
            fields = dict(field.split("=", 1) for field in row.split("\0") if "=" in field)
            image = Path(fields.get("ExecutablePath", ""))
            command, _, module = fields.get("CommandLine", "").rpartition(" -m ")
            label = labels.get(module)
            if not label or not fields.get("ProcessId"):
                continue
            # Match only this installation's GUI. A spawned server worker uses -c.
            if (image == GUI_PYTHON or (image.parent.parent == WINDOWS_HOSTS
                                       and image.name == label + ".exe")) and Path(command.strip('"')) == image:
                instances[label].add(int(fields["ProcessId"]))
        return instances

    from macos_app_host import app_for_process

    output = subprocess.check_output(
        ["/bin/ps", "-ww", "-x", "-U", str(os.getuid()), "-o", "pid=,command="],
        text=True, errors="replace", timeout=5,
    )
    for line in output.splitlines():
        record = line.split(None, 1)
        if len(record) == 2:
            pid, command = record
            label = app_for_process(command, ROOT / "build/macos-apps", APPS)
            if label:
                instances[label].add(int(pid))
                continue
            executable, _, module = command.rpartition(" -m ")
            if module in labels and Path(executable.strip('"')) == GUI_PYTHON:
                instances[labels[module]].add(int(pid))
    return instances


def create_windows_shortcut():
    """Create a launcher shortcut in the current user's Windows desktop folder."""
    # WScript resolves redirected/OneDrive desktops. Pass Unicode paths as data.
    script = """
$ErrorActionPreference = 'Stop'
$shell = New-Object -ComObject WScript.Shell
$path = Join-Path ($shell.SpecialFolders.Item('Desktop')) 'uHandControlLauncher.lnk'
$link = $shell.CreateShortcut($path)
if ((Test-Path -LiteralPath $path) -and
    ($link.TargetPath -ne $env:UHAND_PYTHONW -or $link.Arguments -cne $env:UHAND_ARGS)) {
    throw '다른 uHandControlLauncher 바로가기가 이미 있습니다. 기존 바로가기의 이름을 확인하세요.'
}
$link.TargetPath = $env:UHAND_PYTHONW
$link.Arguments = $env:UHAND_ARGS
$link.WorkingDirectory = $env:UHAND_ROOT
$link.IconLocation = $env:UHAND_ICON + ',0'
$link.Description = 'uHandControlLauncher'
$link.Save()
"""
    interpreter = Path(sys.executable).with_name("pythonw.exe")
    environment = dict(os.environ, UHAND_PYTHONW=str(interpreter),
                       UHAND_ARGS=f'"{Path(__file__).resolve()}"',
                       UHAND_ROOT=str(ROOT), UHAND_ICON=str(ICON.with_suffix(".ico")))
    subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                   env=environment, check=True, creationflags=subprocess.CREATE_NO_WINDOW,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def logo_image(parent, name, size):
    # Use prefiltered PNGs at the same display sizes as the original 256px artwork.
    step = max(1, min(5, round(256 / size)))
    pixels = (256 + step - 1) // step
    path = ICON.with_name(name + ".png")
    if pixels < 256:
        path = ICON.parent / "launch-cards" / f"{name}-{pixels}.png"
    return tk.PhotoImage(master=parent, file=str(path))


class LaunchCard(tk.Canvas):
    """A single focusable target for the logo, two labels and arrow."""
    def __init__(self, parent, name, subtitle, accent, tint, command, scale, family):
        self.size = lambda n: round(n * scale)
        self.accent, self.tint = accent, tint
        self.command = command
        self.subtitle = subtitle
        self.enabled = True
        self.pressed = False
        self.hovered = False
        super().__init__(parent, height=self.size(84), width=1, bg=BG, bd=0,
                         highlightthickness=0, takefocus=True, cursor="hand2")
        self.shape = self.create_polygon(0, 0, 0, 0, smooth=True, splinesteps=16)
        self.logo = logo_image(self, name, self.size(48))
        self.create_image(self.size(43), self.size(42), image=self.logo)
        self.title_item = self.create_text(self.size(84), self.size(30), anchor="w",
                                           text=name, font=(family, 15, "bold"))
        self.detail = self.create_text(self.size(84), self.size(57), anchor="w",
                                       text=subtitle, font=(family, 10))
        self.badge_bg = self.create_polygon(0, 0, 0, 0, smooth=True, splinesteps=16,
                                            fill="#e6f4eb", outline="", state="hidden")
        self.badge_text = self.create_text(0, 0, anchor="e", font=(family, 10, "bold"),
                                           fill="#14633d", state="hidden")
        self.arrow = self.create_line(0, 0, 0, 0, arrow=tk.LAST, width=self.size(2),
                                      arrowshape=tuple(self.size(v) for v in (8, 9, 4)))
        self.bind("<Configure>", self.layout_card)
        self.bind("<Enter>", lambda _: self.hover(True))
        self.bind("<Leave>", lambda _: self.hover(False))
        self.bind("<ButtonPress-1>", self.press)
        self.bind("<ButtonRelease-1>", self.release)
        self.bind("<FocusIn>", lambda _: self.paint())
        self.bind("<FocusOut>", self.blur)
        for key in ("Return", "KP_Enter", "space"):
            self.bind(f"<KeyPress-{key}>", self.press)
            self.bind(f"<KeyRelease-{key}>", self.release)
        self.paint()

    @staticmethod
    def rounded(x, y, right, bottom, r):
        return (x+r,y, right-r,y, right,y, right,y+r, right,bottom-r, right,bottom,
                right-r,bottom, x+r,bottom, x,bottom, x,bottom-r, x,y+r, x,y)

    def layout_card(self, event):
        w, h, s = event.width, event.height, self.size
        self.coords(self.shape, *self.rounded(2, 2, w-2, h-2, s(10)))
        self.coords(self.arrow, w-s(43), h/2, w-s(22), h/2)
        self.layout_badge()

    def layout_badge(self):
        self.coords(self.badge_text, self.winfo_width()-self.size(64), self.winfo_height()/2)
        bounds = self.bbox(self.badge_text)
        if bounds:
            left, top, right, bottom = bounds
            pad = self.size(8)
            self.coords(self.badge_bg, *self.rounded(left-pad, top-3, right+pad, bottom+3,
                                                     (bottom-top+6)/2))

    def set_running_count(self, count):
        state = "normal" if count else "hidden"
        text = "● 실행 중" if count == 1 else f"● 실행 중 · {count}개"
        self.itemconfigure(self.badge_text, text=text if count else "", state=state)
        self.itemconfigure(self.badge_bg, state=state)
        self.layout_badge()

    def paint(self):
        focused = self.enabled and self.focus_get() is self
        highlighted = focused or (self.enabled and self.hovered)
        fill = self.accent if self.pressed else (self.tint if highlighted else "white")
        self.itemconfigure(self.shape, fill=fill, outline=self.accent if focused else "#d4deeb",
                           width=self.size(2) if focused else 1)
        title = "#132640" if self.enabled else "#778496"
        self.itemconfigure(self.title_item, fill="white" if self.pressed else title)
        self.itemconfigure(self.detail, fill="white" if self.pressed else "#516076")
        self.itemconfigure(self.arrow, fill="white" if self.pressed else self.accent)

    def set_enabled(self, enabled):
        self.enabled = enabled
        self.pressed = False
        self.configure(takefocus=enabled, cursor="hand2" if enabled else "arrow")
        self.paint()

    def hover(self, value):
        self.hovered = value
        self.paint()

    def blur(self, event):
        self.pressed = False
        self.paint()

    def press(self, event):
        if self.enabled:
            self.focus_set()
            self.pressed = True
            self.paint()
        return "break"

    def release(self, event):
        invoke = self.enabled and self.pressed
        if event.type == tk.EventType.ButtonRelease:
            invoke = invoke and 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height()
        self.pressed = False
        self.paint()
        if invoke:
            self.command()
        return "break"


def shortcut_button(parent, command, family, size):
    from tkinter import ttk

    style = ttk.Style(parent)
    # Stretch only the center of each state image so the rounded corners stay crisp.
    sheet = tk.PhotoImage(master=parent, file=str(ICON.with_name("shortcut-button.png")))
    side = sheet.height()
    normal, hover, focus, pressed = (
        sheet.copy(from_coords=(x, 0, x + side, side)) for x in range(0, sheet.width(), side)
    )
    style.element_create("Shortcut.surface", "image", normal, ("pressed", pressed),
                         ("focus", focus), ("active", hover), border=9, padding=0, sticky="nswe")
    style.layout("Shortcut.TButton", [
        ("Shortcut.surface", {"sticky": "nswe", "children": [
            ("Button.padding", {"sticky": "nswe", "children": [
                ("Button.label", {"sticky": "nswe"}),
            ]}),
        ]}),
    ])
    style.configure("Shortcut.TButton", font=(family, 9), padding=(size(8), size(5)),
                    foreground="#132640", anchor="center")
    style.map("Shortcut.TButton", foreground=[("pressed", "white")])
    button = ttk.Button(parent, text="바로가기 만들기", command=command, style="Shortcut.TButton",
                        cursor="hand2", takefocus=True)
    def invoke_key(event):
        button.event_generate("<<Invoke>>")
        return "break"

    for key in ("Return", "KP_Enter"):
        button.bind(f"<{key}>", invoke_key)
    button.state_images = (normal, hover, focus, pressed)
    return button


def main():
    from tkinter import font, messagebox

    if WINDOWS:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Inha.uHandControl.Launcher")
    window = tk.Tk()
    window.withdraw()
    window.title("uHandControlLauncher")
    window.configure(bg=BG)
    if WINDOWS:
        ico = str(ICON.with_suffix(".ico"))
        window.iconbitmap(default=ico)
        window.iconbitmap(ico)
    else:
        window._launcher_icon = tk.PhotoImage(file=str(ICON))
        window.iconphoto(True, window._launcher_icon)
    if sys.platform not in ("win32", "darwin") or sys.version_info < (3, 13):
        messagebox.showerror("uHandControlLauncher", "Windows 또는 macOS용 Python 3.13 이상이 필요합니다.")
        window.destroy()
        return
    if sys.platform == "darwin":
        import platform
        if int(platform.mac_ver()[0].split(".")[0]) < 14:
            messagebox.showerror("uHandControlLauncher", "두 GUI를 실행하려면 macOS 14 이상이 필요합니다.")
            window.destroy()
            return
    scale = font.nametofont("TkDefaultFont").metrics("linespace") / 18
    size = lambda value: round(value * max(1, scale))
    family = "맑은 고딕" if WINDOWS else "Apple SD Gothic Neo"
    pane = tk.Frame(window, bg=BG, padx=size(20), pady=size(14))
    pane.pack(fill="both", expand=True)
    heading = tk.Frame(pane, bg=BG)
    heading.pack(fill="x")
    heading.logo = tk.PhotoImage(master=heading, file=str(ICON.with_name("uHandControlLauncher-header.png")))
    tk.Label(heading, image=heading.logo, bg=BG, bd=0).pack(side="left", padx=(0, size(9)))
    tk.Label(heading, text="uHandControlLauncher", font=(family, 24, "bold"),
             anchor="w", fg="#122644", bg=BG).pack(side="left")
    prompt = "실행할 프로그램을 선택하세요. 같은 프로그램도 여러 개 실행할 수 있습니다."
    retry_hint = "실행 중인 프로그램을 확인하지 못했습니다. 다시 확인하고 있습니다."
    try:
        discovered = running_instances()
        initial_status = prompt
    except (OSError, ImportError, subprocess.SubprocessError):
        discovered = {label: set() for label in APPS}
        initial_status = retry_hint
    status = tk.StringVar(value=prompt)
    tk.Label(pane, textvariable=status, wraplength=0, font=(family, 10), anchor="w",
             fg="#516076", bg=BG).pack(fill="x", pady=(0, size(12)))
    buttons = {}
    running = {label: set() for label in APPS}
    displayed = dict.fromkeys(APPS, 0)
    snapshots = SimpleQueue()
    stopped = Event()

    def discover():
        while not stopped.wait(1):
            try:
                snapshots.put(running_instances())
            except (OSError, ImportError, subprocess.SubprocessError):
                # Keep the last successful snapshot and continue tracking local children.
                pass

    def update_badge(label):
        pids = discovered[label].union(child.pid for child in running[label])
        if displayed[label] != len(pids):
            displayed[label] = len(pids)
            buttons[label].set_running_count(len(pids))

    def refresh_badges():
        nonlocal discovered
        try:
            while True:
                discovered = snapshots.get_nowait()
                if status.get() == retry_hint:
                    status.set(prompt)
        except Empty:
            pass
        for label in APPS:
            update_badge(label)
        window.after(250, refresh_badges)

    def enable(label):
        for button in buttons.values():
            button.set_enabled(True)
        card = buttons[label]
        card.itemconfigure(card.detail, text=card.subtitle)

    def watch_app(child, label):
        code = child.poll()
        if code is None:
            window.after(1000, watch_app, child, label)
        else:
            running[label].remove(child)
            discovered[label].discard(child.pid)
            update_badge(label)
            if code:
                messagebox.showerror(label, f"프로그램이 종료되었습니다. 로그를 확인하세요.\n{LOG}")

    def start(label):
        for button in buttons.values():
            button.set_enabled(False)
        card = buttons[label]
        preparing = "실행 준비 중…" if READY.is_file() else "첫 설치 준비 중 · 인터넷 연결 필요"
        card.itemconfigure(card.detail, text=preparing)
        status.set(prompt)
        try:
            LOG.parent.mkdir(exist_ok=True)
            with LOG.open("a", encoding="utf-8") as log:
                child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--prepare"],
                                         cwd=ROOT, stdout=log, stderr=log,
                                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as error:
            enable(label)
            status.set("실행 환경을 준비하지 못했습니다.")
            messagebox.showerror(label, str(error))
            return

        def check():
            if child.poll() is None:
                window.after(200, check)
                return
            enable(label)
            try:
                if child.returncode:
                    raise RuntimeError(f"설치를 완료하지 못했습니다. 다른 설치가 진행 중인지 확인하고 다시 시도하세요.\n{LOG}")
                app = launch(label)
            except (OSError, RuntimeError) as error:
                status.set("실행 준비에 실패했습니다.")
                messagebox.showerror(label, str(error))
                return
            running[label].add(app)
            update_badge(label)
            window.after(500, watch_app, app, label)
        check()

    for name, subtitle, accent, tint in (
        ("uHandMotionCreator", "로봇손 동작 시퀀스 편집", "#285bea", "#edf3ff"),
        ("uHandVirtualServer", "가상 로봇손 제어 테스트", "#cc3344", "#fff1f3"),
    ):
        card = LaunchCard(pane, name, subtitle, accent, tint,
                          lambda label=name: start(label), max(1, scale), family)
        card.pack(fill="x", pady=(0, size(6)))
        buttons[name] = card
        update_badge(name)

    cards = tuple(buttons.values())

    def navigate(event):
        step = 1 if event.keysym == "Down" else -1
        if event.widget in cards:
            target = cards[(cards.index(event.widget) + step) % len(cards)]
        else:
            target = cards[0] if step == 1 else cards[-1]
        if target.enabled:
            target.focus_set()
        return "break"

    window.bind("<Up>", navigate)
    window.bind("<Down>", navigate)

    def add_shortcut():
        try:
            create_windows_shortcut()
        except (OSError, subprocess.CalledProcessError):
            messagebox.showerror("uHandControlLauncher", "바로가기를 만들 수 없습니다. 바탕화면 쓰기 권한과 같은 이름의 바로가기를 확인하세요.", parent=window)
        else:
            status.set("바탕화면에 uHandControlLauncher 바로가기를 만들었습니다.")

    footer = tk.Frame(pane, bg=BG)
    footer.pack(fill="x", pady=(size(3), 0))
    footer.columnconfigure(0, weight=1, uniform="edge")
    footer.columnconfigure(2, weight=1, uniform="edge")
    def footer_text(value):
        return tk.Label(footer, text=value, bg=BG, fg="#52647d", font=(family, 9))
    footer_text(f"v{VERSION}").grid(row=0, column=0, sticky="w")
    def open_repository(event):
        try:
            opened = webbrowser.open_new_tab(REPOSITORY_URL)
        except (OSError, webbrowser.Error):
            opened = False
        if not opened:
            messagebox.showerror("uHandControlLauncher", f"기본 브라우저를 열 수 없습니다.\n{REPOSITORY_URL}", parent=window)
        return "break"

    credit = footer_text("Designed by Data Science Team 1 at Inha University · 2026")
    credit.configure(cursor="hand2", takefocus=True, fg="#315a91",
                     highlightthickness=1, highlightbackground=BG, highlightcolor="#285bea")
    credit.grid(row=0, column=1)
    credit.bind("<Enter>", lambda _: credit.configure(font=(family, 9, "underline")))
    credit.bind("<Leave>", lambda _: credit.configure(font=(family, 9)))
    for sequence in ("<Button-1>", "<Return>", "<space>"):
        credit.bind(sequence, open_repository)
    if WINDOWS:
        shortcut_button(footer, add_shortcut, family, size).grid(row=0, column=2, sticky="e")
    window.update_idletasks()
    width = max(size(586), window.winfo_reqwidth() + size(20))
    window.geometry(f"{width}x{window.winfo_reqheight()}")
    window.resizable(False, False)
    status.set(initial_status)
    window.deiconify()
    buttons["uHandMotionCreator"].focus_set()
    Thread(target=discover, name="launcher-app-discovery", daemon=True).start()
    window.after(0, refresh_badges)
    try:
        window.mainloop()
    finally:
        stopped.set()


if __name__ == "__main__":
    if sys.argv[1:] == ["--prepare"]:
        prepare()
    elif MACOS and sys.argv[1:] != ["--desktop-window"] and sys.version_info >= (3, 13):
        try:
            command = macos_command(LAUNCHER_NAME)
            os.execv(command[0], command)
        except (OSError, RuntimeError, ValueError) as error:
            from tkinter import messagebox
            messagebox.showerror(LAUNCHER_NAME, f"macOS 앱을 준비할 수 없습니다.\n{error}")
    elif WINDOWS and sys.argv[1:] != ["--desktop-window"] and sys.version_info >= (3, 13):
        # The initial .pyw association exits; the named host owns the actual GUI.
        try:
            command, env = windows_command(LAUNCHER_NAME, [str(Path(__file__).resolve()), "--desktop-window"])
            subprocess.Popen(command, cwd=ROOT, env=env)
        except (OSError, ValueError) as error:
            from tkinter import messagebox
            messagebox.showerror(LAUNCHER_NAME, f"Windows 실행 파일을 준비할 수 없습니다.\n{error}")
    else:
        main()
