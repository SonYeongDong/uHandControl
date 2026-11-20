"""Client liveness when the TCP stream stays open but stops delivering replies."""
import threading
import time
import unittest

import uhand_client_module as hand
from _peer import Call, Peer, reply


class ClientLinkLoss(unittest.TestCase):
    def test_silent_peer_unblocks_idle_and_motion_and_allows_reconnect(self):
        for moving in (False, True):
            with self.subTest(moving=moving):
                pulse_received = threading.Event()
                def silent(peer, channel, request):
                    if request["method"] == "Hello":
                        channel.send(reply(request))
                    elif request["method"] == "SetuHandPulse":
                        pulse_received.set()

                peer = Peer(silent)
                try:
                    hand.Connect("127.0.0.1", peer.port)
                    started = time.monotonic()
                    if moving:
                        call = Call(lambda: hand.SetuHandPulse(*[1500]*6, 20000))
                        self.assertTrue(pulse_received.wait(1))
                        with self.assertRaises(hand.RequestTimeoutError):
                            call.result(5)
                    self.assertTrue(self._wait_closed(5))
                    self.assertLess(time.monotonic() - started, 4.5)
                    with self.assertRaises(hand.NotConnectedError):
                        hand.GetStatus()
                    peer.handler = None
                    hand.Connect("127.0.0.1", peer.port)
                    self.assertIsNone(hand.GetStatus()["TargetPulses"])
                    self.assertEqual(sum(r["method"] == "SetuHandPulse" for r in peer.requests),
                                     int(moving))
                finally:
                    hand.Disconnect()
                    peer.close()

    @staticmethod
    def _wait_closed(timeout):
        deadline = time.monotonic() + timeout
        while not hand._client._session.closed and time.monotonic() < deadline:
            time.sleep(0.02)
        return hand._client._session.closed
