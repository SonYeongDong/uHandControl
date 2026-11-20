import copy
import json
import time
import unittest
from unittest.mock import patch

import uhand_client_module as hand
from uhand_client_module import _transport
from _peer import Call, EMPTY, Peer, encoded, reply


class ProtocolFailureTests(unittest.TestCase):
    def setUp(self):
        hand.Disconnect()
        self.peers = []

    def tearDown(self):
        hand.Disconnect()
        for peer in self.peers:
            peer.close()

    def run_bad_response(self, transform):
        def handler(peer, channel, req):
            if req["method"] == "Hello":
                channel.send(reply(req))
            else:
                data = transform(reply(req, copy.deepcopy(EMPTY)))
                channel.raw(data)
        peer = Peer(handler)
        self.peers.append(peer)
        hand.Connect("127.0.0.1", peer.port)
        with self.assertRaises(hand.ProtocolError):
            hand.GetStatus()
        with self.assertRaises(hand.NotConnectedError):
            hand.GetStatus()
        hand.Disconnect()

    def test_malformed_frames(self):
        cases = [
            lambda value: b"not-json\n",
            lambda value: b"\xff\n",
            lambda value: b"\n",
            lambda value: b"[]\n",
            lambda value: b'{"version":2,"version":2}\n',
            lambda value: b'{"result":NaN}\n',
            lambda value: b'{"result":Infinity}\n',
            lambda value: b"[" * 2000 + b"]" * 2000 + b"\n",
            lambda value: b"x" * 65536,  # no LF, bounded buffer
            lambda value: b"x" * 65536 + b"\n",
        ]
        for case in cases:
            with self.subTest(case=cases.index(case)):
                self.run_bad_response(case)

    def test_invalid_response_envelopes(self):
        changes = [
            {"version": 99}, {"version": True}, {"request_id": True},
            {"request_id": 0}, {"request_id": 2**53}, {"request_id": 999},
            {"ok": 1}, {"extra": True}, {"error": {}},
        ]
        for change in changes:
            with self.subTest(change=change):
                self.run_bad_response(lambda value, c=change: encoded(dict(value, **c)))

    def test_inconsistent_status_rejected_instead_of_cached_or_coerced(self):
        variants = [
            dict(EMPTY, TargetPulses=[1500] * 6),
            dict(EMPTY, PulseRunningTime=100),
            dict(EMPTY, TargetPulses=[1500] * 5, PulseRunningTime=100),
            dict(EMPTY, TargetPulses=[True] * 6, PulseRunningTime=100),
            dict(EMPTY, TargetPulses=[2501] * 6, PulseRunningTime=100),
            dict(EMPTY, BuzzerFrequency=1000),
            dict(EMPTY, BuzzerFrequency=0, BuzzerRunningTime=100),
            dict(EMPTY, BuzzerFrequency=1000, BuzzerRunningTime=99),
            dict(EMPTY, LED=[1, 0, 0]),
            dict(EMPTY, LED=[False] * 2),
            dict(EMPTY, Connected=True),
            {},
            None,
        ]
        for status in variants:
            with self.subTest(status=status):
                self.run_bad_response(lambda value, s=status: encoded(dict(value, result=s)))

    def test_invalid_error_objects(self):
        for error in (
            None, {}, {"code": 1, "message": "error"},
            {"code": "BUSY", "message": None},
            {"code": "", "message": "error"},
            {"code": "BUSY", "message": "x" * 1025},
            {"code": "BUSY", "message": "error", "extra": 1},
        ):
            with self.subTest(error=error):
                self.run_bad_response(lambda value, e=error: encoded({
                    "version": 2, "request_id": value["request_id"], "ok": False, "error": e,
                }))

    def test_output_success_must_be_null(self):
        def handler(peer, channel, req):
            channel.send(reply(req, None if req["method"] == "Hello" else True))
        peer = Peer(handler)
        self.peers.append(peer)
        hand.Connect("127.0.0.1", peer.port)
        with self.assertRaises(hand.ProtocolError):
            hand.SetuHandLED(True, False, False)

    def test_eof_and_truncated_frame_unblock_waiters(self):
        for partial, error in ((b"", hand.DisconnectedError), (b'{"version":', hand.ProtocolError)):
            with self.subTest(partial=partial):
                def handler(peer, channel, req):
                    if req["method"] == "Hello":
                        channel.send(reply(req))
                    else:
                        channel.raw(partial)
                        channel.close()
                peer = Peer(handler)
                self.peers.append(peer)
                hand.Connect("127.0.0.1", peer.port)
                with self.assertRaises(error):
                    hand.GetStatus()
                hand.Disconnect()

    def test_timeout_unblocks_all_pending_callers(self):
        def handler(peer, channel, req):
            if req["method"] == "Hello":
                channel.send(reply(req))
        peer = Peer(handler)
        self.peers.append(peer)
        hand.Connect("127.0.0.1", peer.port)
        with patch.object(_transport, "RESPONSE_TIMEOUT", 0.1):
            running = Call(lambda: hand.SetuHandPulse(*([1500] * 6), 20000))
            deadline = time.monotonic() + 1
            while len(peer.requests) < 2 and time.monotonic() < deadline:
                time.sleep(0.005)
            with self.assertRaises(hand.RequestTimeoutError):
                hand.GetStatus()
            with self.assertRaises(hand.RequestTimeoutError):
                running.result()
        self.assertEqual(len(peer.requests), 3)

    def test_duplicate_response_closes_connection(self):
        def handler(peer, channel, req):
            if req["method"] == "Hello":
                channel.send(reply(req))
            else:
                frame = encoded(reply(req, copy.deepcopy(EMPTY)))
                channel.raw(frame + frame)
        peer = Peer(handler)
        self.peers.append(peer)
        hand.Connect("127.0.0.1", peer.port)
        # First matching reply may complete before the duplicate is consumed.
        self.assertEqual(hand.GetStatus(), EMPTY)
        deadline = time.monotonic() + 1
        while not hand._client._session.closed and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertTrue(hand._client._session.closed)
        with self.assertRaises(hand.NotConnectedError):
            hand.GetStatus()

    def test_no_cache_fallback_on_next_query_failure(self):
        count = 0
        def handler(peer, channel, req):
            nonlocal count
            if req["method"] == "Hello":
                channel.send(reply(req))
            elif count == 0:
                count += 1
                channel.send(reply(req, copy.deepcopy(EMPTY)))
            else:
                channel.close()
        peer = Peer(handler)
        self.peers.append(peer)
        hand.Connect("127.0.0.1", peer.port)
        self.assertEqual(hand.GetStatus(), EMPTY)
        with self.assertRaises(hand.DisconnectedError):
            hand.GetStatus()

    def test_utf8_error_split_inside_multibyte_character(self):
        def handler(peer, channel, req):
            if req["method"] == "Hello":
                channel.send(reply(req))
                return
            data = encoded(reply(req, error={"code": "DEVICE_ERROR", "message": "장치 오류"}))
            split = data.index("장".encode("utf-8")) + 1
            channel.raw(data[:split])
            channel.raw(data[split:])
        peer = Peer(handler)
        self.peers.append(peer)
        hand.Connect("127.0.0.1", peer.port)
        with self.assertRaises(hand.DeviceError) as result:
            hand.GetStatus()
        self.assertEqual(result.exception.message, "장치 오류")


if __name__ == "__main__":
    unittest.main()
