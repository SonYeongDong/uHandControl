"""Socket-level checks of readiness signals on both server implementations."""
import json
import socket
import struct
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for directory in ("shared/uhand-server-lifecycle/src", "projects/uhand-server/src", "projects/uhand-virtual-server/src"):
    sys.path.insert(0, str(ROOT / directory))

from uhand_server.backend import RecordingBackend
from uhand_server.server import PhysicalServer
from uhand_virtual_server.server import VirtualServer


class ClockedBoard(RecordingBackend):
    def __init__(self):
        super().__init__()
        self.notes = []

    def set_buzzer(self, freq, ms):
        self.notes.append((freq, ms, time.monotonic()))
        super().set_buzzer(freq, ms)


class ClockedAudio:
    def __init__(self):
        self.notes = []

    def play(self, freq, ms, cancel):
        self.notes.append((freq, ms, time.monotonic()))
        cancel.wait(ms / 1000)


def packet(rid, method, **params):
    return (json.dumps(dict(version=2, request_id=rid, method=method, params=params)) + "\n").encode()


def wait_until(predicate):
    deadline = time.monotonic() + 5
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("Server did not finish the transition")
        time.sleep(.01)


class Signals(unittest.TestCase):
    def assert_notes(self, notes, expected, began):
        self.assertEqual([(f, ms) for f, ms, _ in notes], [(f, 175) for f in expected])
        self.assertGreaterEqual(notes[0][2] - began, .48)
        for left, right in zip(notes, notes[1:]):
            self.assertAlmostEqual(right[2] - left[2], .25, delta=.075)

    def exercise(self, server, device):
        self.addCleanup(server.shutdown)
        began = time.monotonic()
        server.start()
        self.assert_notes(device.notes, (523, 659, 784), began)
        if isinstance(server, VirtualServer):
            server.stop_listening()
            began = time.monotonic()
            server.start(background=True)
            self.assertEqual(server.snapshot()["phase"], "startup")
            wait_until(lambda: not server.lifecycle.phase)
            self.assert_notes(device.notes[3:], (523,659,784), began)
        with socket.create_connection(("127.0.0.1", server.port), 5):
            pass
        time.sleep(.1)
        offset = len(device.notes)
        sock = socket.create_connection(("127.0.0.1", server.port), 5)
        self.addCleanup(sock.close)
        reader = sock.makefile("rb")
        self.addCleanup(reader.close)
        began = time.monotonic()
        sock.sendall(packet(1, "Hello") + packet(2, "SetuHandLED", RedEnable=True, GreenEnable=True, BlueEnable=True))
        self.assertEqual(json.loads(reader.readline())["error"]["code"], "BUSY")
        self.assertTrue(json.loads(reader.readline())["ok"])
        self.assert_notes(device.notes[offset:], (659,880), began)
        self.assertGreaterEqual(time.monotonic() - device.notes[-1][2], .17)
        sock.sendall(packet(3, "GetStatus"))
        self.assertEqual(json.loads(reader.readline())["result"]["LED"], [False]*3)
        offset = len(device.notes)
        sock.sendall(packet(4, "SetuHandLED", RedEnable=True, GreenEnable=True, BlueEnable=True))
        self.assertTrue(json.loads(reader.readline())["ok"])
        linger = struct.pack("HH" if sys.platform == "win32" else "ii", 1, 0)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, linger)
        began = time.monotonic()
        reader.close()
        sock.close()
        wait_until(lambda: server.owner is None and not server.lifecycle.phase)
        self.assert_notes(device.notes[offset:], (440,370,294), began)
        self.assertEqual(server.status["TargetPulses"], [1500]*6)
        self.assertEqual(server.status["PulseRunningTime"], 500)
        self.assertEqual(server.status["LED"], [False]*3)
        self.assertEqual(server.status["BuzzerFrequency"], 0)

    def test_virtual(self):
        audio = ClockedAudio()
        self.exercise(VirtualServer(port=0,audio=audio), audio)

    def test_physical(self):
        board = ClockedBoard()
        self.exercise(PhysicalServer(board,port=0), board)
