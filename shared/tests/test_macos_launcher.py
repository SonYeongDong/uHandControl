"""Test desktop launcher selection, macOS bundle contents and instance discovery."""
import hashlib
import json
from pathlib import Path
import plistlib
import runpy
import shutil
import struct
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
with patch.object(sys, "path", [str(ROOT), *sys.path]):
    import macos_app_host as host


def launcher_for(platform):
    with patch.object(sys, "platform", platform):
        return runpy.run_path(str(ROOT / "uHandControlLauncher.pyw"))


def seed_vendor(root):
    shutil.copytree(ROOT / "assets/macos/py2app", root / "assets/macos/py2app")


class DesktopLauncherTests(unittest.TestCase):
    def test_mac_uses_venv_for_apps_and_base_for_launcher(self):
        launcher = launcher_for("darwin")
        python = ROOT / ".venv/bin/python"
        self.assertEqual(launcher["install_python"](), str(python))
        self.assertIn("shared/uhand-desktop-audio", launcher["PACKAGES"])
        with patch.object(host, "app_command", return_value=["named-host"]) as build:
            launcher["macos_command"](launcher["LAUNCHER_NAME"])
            self.assertEqual(build.call_args.args[2:4], (None, Path(sys.executable)))
            with TemporaryDirectory() as tmp, patch.dict(
                launcher["launch"].__globals__, LOG=Path(tmp) / "launcher.log"
            ), patch("subprocess.Popen") as popen:
                for name, module in launcher["APPS"].items():
                    launcher["launch"](name)
                    self.assertEqual(build.call_args.args[1:4], (name, module, python))
                    self.assertEqual(popen.call_args.args[0], ["named-host"])

    def test_windows_uses_its_existing_audio_driver_and_gui_interpreter(self):
        launcher = launcher_for("win32")
        self.assertEqual(launcher["GUI_PYTHON"].name, "pythonw.exe")
        self.assertNotIn("shared/uhand-desktop-audio", launcher["PACKAGES"])

    def test_named_and_older_instances_are_scoped_to_checkout(self):
        launcher = launcher_for("darwin")
        editor = "uHandMotionCreator"
        server = "uHandVirtualServer"
        def image(cache, name):
            return cache / "abc" / (name + ".app") / "Contents/MacOS" / name
        cache = ROOT / "build/macos-apps"
        records = [image(cache, editor), image(cache, editor), image(cache, server),
                   image(cache.parent / "other", editor),
                   f'{launcher["GUI_PYTHON"]} -c spawn_main()',
                   f'{launcher["GUI_PYTHON"]} -m uhand_motion_creator']
        def snapshot(rows):
            output = "\n".join(f"{pid} {exe}" for pid, exe in enumerate(rows, 1) if exe)
            with patch.object(launcher["running_instances"].__globals__["os"], "getuid", create=True,
                              return_value=501), patch("subprocess.check_output", return_value=output):
                return launcher["running_instances"]()
        self.assertEqual(snapshot(records), {editor: {1, 2, 6}, server: {3}})
        records[0] = None
        self.assertEqual(snapshot(records), {editor: {2, 6}, server: {3}})

    def test_vendored_host_supports_intel_and_apple_silicon(self):
        binary = (ROOT / "assets/macos/py2app/main-universal2").read_bytes()
        self.assertEqual(hashlib.sha256(binary).hexdigest(),
                         "716e5eb2c2a93fe56095d1edc6b25bab72f535572cdff06d39f20fed40b85540")
        magic, count = struct.unpack_from(">II", binary)
        self.assertEqual(magic, 0xcafebabe)
        self.assertEqual({struct.unpack_from(">I", binary, 8 + 20*i)[0] for i in range(count)},
                         {0x01000007, 0x0100000c})

    def test_all_bundles_are_complete_and_reused(self):
        launcher = launcher_for("darwin")
        config = dict(executable=sys.executable, library="/Library/example/Python")
        def run(command, **kwargs):
            output = json.dumps(config) if "-I" in command else ""
            return subprocess.CompletedProcess(command, 0, output, "")
        # Windows may forbid creating symlinks. Exercise real links in the native test below.
        with TemporaryDirectory() as tmp, patch.object(host.subprocess, "run", side_effect=run) as calls, \
                patch.object(Path, "symlink_to", autospec=True, side_effect=lambda link, dest: link.touch()):
            root = Path(tmp) / "한글 project"
            seed_vendor(root)
            with patch.dict(launcher["macos_command"].__globals__, ROOT=root):
                for name in [launcher["LAUNCHER_NAME"], *launcher["APPS"]]:
                    if name in launcher["APPS"]:
                        module = launcher["APPS"][name]
                        path = Path("projects") / module.replace("_", "-") / "src" / module / (name + ".ico")
                        (root / path).parent.mkdir(parents=True)
                        shutil.copyfile(ROOT / path, root / path)
                    exe, = launcher["macos_command"](name)
                    bundle = Path(exe).parents[2]
                    self.assertEqual(Path(exe).name, name)
                    info = plistlib.loads((bundle / "Contents/Info.plist").read_bytes())
                    self.assertEqual(info["CFBundleExecutable"], name)
                    self.assertEqual(info["CFBundleDisplayName"], name)
                    self.assertTrue(info["CFBundleIdentifier"].endswith("." + name))
                    resources = bundle / "Contents/Resources"
                    icon = (resources / info["CFBundleIconFile"]).read_bytes()
                    self.assertEqual(icon[:4], b"icns")
                    self.assertEqual(int.from_bytes(icon[4:8], "big"), len(icon))
                    self.assertTrue((resources / "py2app-LICENSE.txt").is_file())
                    runtime = json.loads((resources / "runtime.json").read_text(encoding="utf-8"))
                    self.assertEqual(runtime["module"], launcher["APPS"].get(name))
                    self.assertEqual(launcher["macos_command"](name), [exe])
            signs = [c for c in calls.call_args_list if c.args[0][0] == "/usr/bin/codesign"]
            self.assertEqual(len(signs), 3)

    def test_bundle_entry_runs_module_and_can_start_a_python_child(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "한글 project"
            root.mkdir()
            resources = root / "Resources"
            resources.mkdir()
            entry = resources / "__boot__.py"
            entry.write_text(host._BOOT, encoding="utf-8")
            config = dict(root=str(root), module="sample_gui", executable=sys.executable,
                          prefix=sys.prefix, base_prefix=sys.base_prefix,
                          base_executable=sys._base_executable, paths=sys.path)
            (resources / "runtime.json").write_text(json.dumps(config), encoding="utf-8")
            (root / "sample_gui.py").write_text(
                'import subprocess, sys\n'
                'assert __name__ == "__main__"\n'
                'subprocess.run([sys.executable, "-I", "-c", "print(1234)"], check=True)\n',
                encoding="utf-8")
            result = subprocess.run([sys.executable, "-B", "-I", str(entry)], capture_output=True,
                                    text=True, check=True, timeout=10)
            self.assertEqual(result.stdout.strip(), "1234")

    @unittest.skipUnless(sys.platform == "darwin", "requires a real macOS framework and codesign")
    def test_native_host_binds_name_icon_and_uses_selected_venv(self):
        import venv
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / "한글 project"
            seed_vendor(root)
            env = root / ".venv"
            venv.EnvBuilder(with_pip=False, symlinks=True).create(env)
            interpreter = env / "bin/python"
            # Query the live macOS main bundle rather than reading back its plist from disk.
            (root / "identity_probe.py").write_text(
                'import ctypes as c, json, os, sys\n'
                'from pathlib import Path\n'
                'cf = c.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")\n'
                'cf.CFBundleGetMainBundle.restype = c.c_void_p\n'
                'cf.CFBundleGetIdentifier.argtypes = [c.c_void_p]\n'
                'cf.CFBundleGetIdentifier.restype = c.c_void_p\n'
                'cf.CFStringGetCString.argtypes = [c.c_void_p, c.c_void_p, c.c_long, c.c_uint32]\n'
                'buf = c.create_string_buffer(256)\n'
                'assert cf.CFStringGetCString(cf.CFBundleGetIdentifier(cf.CFBundleGetMainBundle()), '
                'buf, len(buf), 0x08000100)\n'
                'Path("probe.json").write_text(json.dumps([buf.value.decode(), sys.executable, '
                'sys.prefix, os.getpid()]))\n', encoding="utf-8")
            command = host.app_command(root, "uHandMotionCreator", "identity_probe", interpreter,
                                       ROOT / "assets/uHandControlLauncher.ico", "1.0.0")
            with subprocess.Popen(command) as proc:
                try:
                    self.assertEqual(proc.wait(timeout=20), 0)
                finally:
                    if proc.poll() is None:
                        proc.kill()
                identity, executable, prefix, pid = json.loads((root / "probe.json").read_text())
                self.assertTrue(identity.endswith(".uHandMotionCreator"))
                self.assertEqual((Path(executable), Path(prefix), pid), (interpreter, env, proc.pid))
