"""Service switch failure-path tests. No system services are touched."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location("uhand_mode", Path(__file__).resolve().parents[1] / "tools" / "uhand_mode.py")
mode = importlib.util.module_from_spec(spec)
# The switch logic tests use no file locking. Windows lacks the Pi's fcntl module.
if sys.platform == "win32":
    with patch.dict(sys.modules, {"fcntl": Mock()}):
        spec.loader.exec_module(mode)
else:
    spec.loader.exec_module(mode)


class SwitchTests(unittest.TestCase):
    def setUp(self):
        self.server, self.vendor = mode.UNITS.values()
        self.active = {self.server}
        self.enabled = {self.server}
        self.calls = []
        self.fail_on = None
        for name, value in (("state", self.state), ("ctl", self.ctl)):
            p = patch.object(mode, name, value)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(mode.time, "sleep")
        p.start()
        self.addCleanup(p.stop)

    def state(self, unit):
        running = unit in self.active
        return dict(ActiveState="active" if running else "inactive",
                    SubState="running" if running else "dead", MainPID="5" if running else "0",
                    NRestarts="0", UnitFileState="enabled" if unit in self.enabled else "disabled")

    def ctl(self, verb, unit):
        self.calls.append((verb, unit))
        if self.fail_on == (verb, unit):
            raise subprocess.CalledProcessError(1, verb)
        if verb == "start":
            self.assertFalse(self.active - {unit})
            self.active.add(unit)
        elif verb == "stop":
            self.active.discard(unit)
        elif verb == "enable":
            self.enabled.add(unit)
        elif verb == "disable":
            self.enabled.discard(unit)

    def test_runtime_toggle_both_ways(self):
        mode.switch("toggle", False)
        self.assertEqual(self.calls, [("stop", self.server), ("start", self.vendor)])
        self.assertEqual(self.enabled, {self.server})
        mode.switch("toggle", False)
        self.assertEqual(self.active, {self.server})

    def test_explicit_mode_and_persistence(self):
        mode.switch("vendor", True)
        self.calls.clear()
        mode.switch("vendor", True)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.enabled, {self.vendor})

    def test_failed_start_restores_service(self):
        self.fail_on = ("start", self.vendor)
        with self.assertRaises(RuntimeError):
            mode.switch("vendor", True)
        self.assertEqual(self.active, {self.server})
        self.assertEqual(self.enabled, {self.server})

    def test_failed_enable_restores_runtime_and_boot(self):
        self.fail_on = ("enable", self.vendor)
        with self.assertRaises(RuntimeError):
            mode.switch("toggle", True)
        self.assertEqual(self.active, {self.server})
        self.assertEqual(self.enabled, {self.server})

    def test_ambiguous_toggle(self):
        for active in (set(), {self.server, self.vendor}):
            self.active = active
            with self.assertRaises(RuntimeError):
                mode.switch("toggle", False)
            self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
