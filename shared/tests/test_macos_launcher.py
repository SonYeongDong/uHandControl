"""Check launcher paths and child-process arguments without opening a GUI."""
from pathlib import Path
import runpy
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


class DesktopLauncherTests(unittest.TestCase):
    def test_mac_uses_venv_bin_for_install_and_gui(self):
        with patch.object(sys, "platform", "darwin"):
            launcher = runpy.run_path(str(ROOT / "run.pyw"))
        python = ROOT / ".venv/bin/python"
        self.assertEqual(launcher["install_python"](), str(python))
        self.assertEqual(launcher["GUI_PYTHON"], python)
        self.assertIn("shared/uhand-desktop-audio", launcher["PACKAGES"])
        with TemporaryDirectory() as tmp, patch.dict(
            launcher["launch"].__globals__, LOG=Path(tmp) / "launcher.log"
        ), patch("subprocess.Popen") as popen:
            launcher["launch"]("uHandVirtualServer")
        self.assertEqual(popen.call_args.args[0], [str(python), "-m", "uhand_virtual_server"])

    def test_windows_uses_its_existing_audio_driver_and_gui_interpreter(self):
        with patch.object(sys, "platform", "win32"):
            launcher = runpy.run_path(str(ROOT / "run.pyw"))
        self.assertEqual(launcher["GUI_PYTHON"].name, "pythonw.exe")
        self.assertNotIn("shared/uhand-desktop-audio", launcher["PACKAGES"])
