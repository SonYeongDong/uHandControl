"""Check the two installed GUIs and a saved sequence using only loopback."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from unittest.mock import patch

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog

from uhand_motion_creator.ui import MainWindow as Creator
from uhand_virtual_server.server import VirtualServer
from uhand_virtual_server.ui import MainWindow as Monitor

ROOT = Path(__file__).resolve().parents[2]


def wait_for(check, timeout=15):
    end = monotonic() + timeout
    while not check():
        if monotonic() >= end:
            raise TimeoutError("The GUI did not reach the expected state.")
        QTest.qWait(20)


def main():
    app = QApplication([])
    server = VirtualServer("127.0.0.1", 0)
    server.start()
    monitor = Monitor(server)
    creator = Creator()
    creator.force_close = True
    try:
        monitor.show()
        creator.show()
        app.processEvents()
        assert creator.isVisible() and monitor.isVisible()
        creator.spins[1].setValue(1800)
        creator.add_motion()
        assert creator.sequence.items[0].pulses[1] == 1800
        with TemporaryDirectory() as temp:
            path = Path(temp) / "시험 동작.uhjson"
            with patch.object(creator, "choose_save_path", return_value=path):
                assert creator.save_document()
            assert creator.new_document()
            with patch.object(QFileDialog, "getOpenFileName", return_value=(str(path), "")):
                assert creator.open_document()
            assert creator.sequence.items[0].pulses[1] == 1800
            legacy = ROOT / "projects/uhand-motion-creator/examples/sequences/mixed-demo.uhand.json"
            with patch.object(QFileDialog, "getOpenFileName", return_value=(str(legacy), "")):
                assert creator.open_document()
            with patch.object(creator, "choose_save_path", return_value=path):
                assert creator.save_document(save_as=True)
            assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == 2
        creator.show_server_panel()
        creator.server_panel.ip.setText("127.0.0.1")
        creator.server_panel.port.setValue(server.port)
        creator.connect_remote()
        wait_for(lambda: creator.remote.connected and not creator.remote.busy)
        creator.run_remote("all")
        wait_for(lambda: not creator.remote.busy and not creator.remote_running)
        status = server.snapshot()["status"]
        assert status["TargetPulses"] == [2200, 800, 800, 800, 800, 1500], status
        assert status["LED"] == [0, 0, 0] and status["BuzzerFrequency"] == 0, status
        creator.disconnect_remote()
        wait_for(lambda: not creator.remote.connected and not creator.remote.busy)
        print("PASS: two windows, add/save/open, legacy migration, loopback remote playback")
    finally:
        creator.close()
        monitor.close()
        server.shutdown()


if __name__ == "__main__":
    main()
