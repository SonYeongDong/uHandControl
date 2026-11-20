"""Carrier loss must abort a live owner without closing the listening socket."""
from pathlib import Path
import time
import unittest
from unittest.mock import patch

from test_server import Peer, pulse, led
from uhand_server.server import PhysicalServer
from uhand_server.backend import RecordingBackend
from uhand_server_lifecycle import reset_status


class ServerLinkLoss(unittest.TestCase):
    def test_unplug_and_fast_replug_during_motion(self):
        for replug in (False, True):
            with self.subTest(replug=replug):
                carrier = [0, 1]
                with patch("uhand_server.server.read_link", side_effect=lambda _: tuple(carrier)):
                    server = PhysicalServer(RecordingBackend(), port=0, link_directory=Path("test-net"))
                    server.start()
                    try:
                        peer = Peer(server.port)
                        try:
                            self.assertTrue(peer.call("Hello")["ok"])
                            self.assertTrue(peer.call("SetuHandLED", led())["ok"])
                            self.assertTrue(peer.call("SetuHandBuzzer", dict(Frequency=440, RunningTime=100, Continuous=True))["ok"])
                            peer.send("SetuHandPulse", pulse(1600, 20000))
                            self.wait_for(lambda: server.snapshot()["busy"])
                            carrier[:] = [1, int(replug)]
                            self.wait_for(lambda: server.owner is None, 1)
                            self.wait_for(lambda: not server.snapshot()["busy"])
                            self.assertEqual(server.snapshot()["status"], reset_status())
                            self.assertFalse(server.buzzer_continuous)
                            self.assertEqual([x[2] for x in server.backend.commands if x[0] == "buzzer"][-3:],
                                             [440, 370, 294])
                        finally:
                            peer.close()
                        carrier[1] = 1
                        fresh = Peer(server.port)
                        try:
                            self.assertTrue(fresh.call("Hello")["ok"])
                            self.assertEqual(fresh.call("GetStatus", {"IncludeLEDBrightness":True})["result"], reset_status())
                        finally:
                            fresh.close()
                    finally:
                        server.shutdown()

    def wait_for(self, predicate, timeout=3):
        deadline = time.monotonic() + timeout
        while not predicate():
            self.assertLess(time.monotonic(), deadline)
            time.sleep(.01)
