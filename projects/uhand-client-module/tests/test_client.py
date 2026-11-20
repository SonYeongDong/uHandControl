import copy
import inspect
import json
import socket
import threading
import time
import unittest
from unittest.mock import patch

import uhand_client_module as hand
from uhand_client_module import _transport
from _peer import Call, EMPTY, Peer, encoded, reply


class ClientTests(unittest.TestCase):
    def setUp(self):
        hand.Disconnect()
        self.peers = []

    def tearDown(self):
        hand.Disconnect()
        for peer in self.peers:
            peer.close()

    def peer(self, handler=None, connect=True):
        peer = Peer(handler)
        self.peers.append(peer)
        if connect:
            hand.Connect("127.0.0.1", peer.port)
        return peer

    def test_public_signatures(self):
        expected = {
            "Connect": ["IP", "Port"], "Disconnect": [], "GetStatus": [],
            "SetuHandPulse": [f"Finger{i}Pulse" for i in range(1, 6)] + ["WristPulse", "RunningTime"],
            "SetuHandBuzzer": ["Frequency", "RunningTime", "Continuous"],
            "SetuHandLED": ["Red", "Green", "Blue", "Brightness", "legacy"],
        }
        for name, params in expected.items():
            self.assertEqual(list(inspect.signature(getattr(hand, name)).parameters), params)
        self.assertFalse(hasattr(hand, "Stop"))

    def test_connect_only_sends_handshake_and_initial_status_is_none(self):
        peer = self.peer()
        self.assertEqual([r["method"] for r in peer.requests], ["Hello"])
        self.assertEqual(hand.GetStatus(), EMPTY)

    def test_pulse_boundaries_and_status(self):
        self.peer()
        pulses = [800, 2000, 1500, 1200, 1800, 2500]
        start = time.monotonic()
        self.assertIsNone(hand.SetuHandPulse(*pulses, 100))
        self.assertGreaterEqual(time.monotonic() - start, 0.09)
        status = hand.GetStatus()
        self.assertEqual(status["TargetPulses"], pulses)
        self.assertEqual(status["PulseRunningTime"], 100)
        self.assertIsNone(status["BuzzerFrequency"])
        status["TargetPulses"][0] = 999
        self.assertEqual(hand.GetStatus()["TargetPulses"], pulses)

    def test_buzzer_preserves_last_completed_and_led_is_independent(self):
        self.peer()
        hand.SetuHandBuzzer(1000, 100)
        hand.SetuHandLED(True, False, True)
        status = hand.GetStatus()
        self.assertEqual(status["BuzzerFrequency"], 1000)
        self.assertEqual(status["BuzzerRunningTime"], 100)
        self.assertEqual(status["LED"], [255, 0, 255])
        self.assertIsNone(status["TargetPulses"])

    def test_all_led_combinations(self):
        self.peer()
        for bits in range(8):
            values = [bool(bits & (1 << i)) for i in range(3)]
            self.assertIsNone(hand.SetuHandLED(*values))
            self.assertEqual(hand.GetStatus()["LED"], [255 * v for v in values])

    def test_status_and_busy_while_pulse_runs(self):
        peer = self.peer()
        hand.SetuHandPulse(*([1200] * 6), 100)
        peer.started.clear()
        running = Call(lambda: hand.SetuHandPulse(*([1800] * 6), 600))
        self.assertTrue(peer.started.wait(1))
        start = time.monotonic()
        status = hand.GetStatus()
        self.assertLess(time.monotonic() - start, 0.4)
        self.assertFalse(running.done.is_set())
        self.assertEqual(status["TargetPulses"], [1200] * 6)
        self.assertEqual(status["PulseRunningTime"], 100)
        for function in (
            lambda: hand.SetuHandPulse(*([1500] * 6), 100),
            lambda: hand.SetuHandBuzzer(1000, 100),
            lambda: hand.SetuHandLED(False, False, False),
        ):
            with self.assertRaises(hand.BusyError):
                function()
        running.result()
        self.assertEqual(hand.GetStatus()["TargetPulses"], [1800] * 6)
        self.assertEqual(hand.GetStatus()["PulseRunningTime"], 600)

    def test_buzzer_running_returns_previous_frequency_time_pair(self):
        peer = self.peer()
        hand.SetuHandBuzzer(1000, 100)
        peer.started.clear()
        running = Call(lambda: hand.SetuHandBuzzer(1900, 500))
        self.assertTrue(peer.started.wait(1))
        status = hand.GetStatus()
        self.assertEqual((status["BuzzerFrequency"], status["BuzzerRunningTime"]), (1000, 100))
        self.assertFalse(running.done.is_set())
        running.result()
        self.assertEqual(hand.GetStatus()["BuzzerFrequency"], 1900)

    def test_maximum_running_time_waits_for_server_completion(self):
        self.peer()
        start = time.monotonic()
        hand.SetuHandPulse(*([1500] * 6), 20000)
        elapsed = time.monotonic() - start
        self.assertGreaterEqual(elapsed, 19.9)
        self.assertLess(elapsed, 25)
        self.assertEqual(hand.GetStatus()["PulseRunningTime"], 20000)

    def test_sequential_commands_need_no_extra_sleep(self):
        peer = self.peer()
        start = time.monotonic()
        hand.SetuHandPulse(*([1500] * 6), 100)
        hand.SetuHandBuzzer(1000, 100)
        hand.SetuHandLED(False, True, False)
        self.assertGreaterEqual(time.monotonic() - start, 0.19)
        self.assertEqual([r["method"] for r in peer.requests][1:],
                         ["SetuHandPulse", "SetuHandBuzzer", "SetuHandLED"])

    def test_invalid_pulses_are_rejected_without_transmission(self):
        peer = self.peer()
        count = len(peer.requests)
        for index in range(6):
            for value in (499, 2501, True, 1500.0, "1500", None):
                with self.subTest(index=index, value=value):
                    pulses = [1500] * 6
                    pulses[index] = value
                    with self.assertRaises(hand.InputValidationError):
                        hand.SetuHandPulse(*pulses, 100)
        self.assertEqual(len(peer.requests), count)

    def test_invalid_running_times(self):
        peer = self.peer()
        for value in (0, 99, 20001, -1, True, 100.0, "100", None):
            with self.subTest(value=value):
                with self.assertRaises(hand.InputValidationError):
                    hand.SetuHandPulse(*([1500] * 6), value)
                with self.assertRaises(hand.InputValidationError):
                    hand.SetuHandBuzzer(1000, value)
        self.assertEqual(len(peer.requests), 1)

    def test_invalid_frequency_and_led_types(self):
        peer = self.peer()
        for value in (-1, 10001, 65536, True, 1000.0, "1000", None):
            with self.assertRaises(hand.InputValidationError):
                hand.SetuHandBuzzer(value, 100)
        for index in range(3):
            for value in (-1, 256, "True", None):
                args = [True] * 3
                args[index] = value
                with self.assertRaises(hand.InputValidationError):
                    hand.SetuHandLED(*args)
        self.assertEqual(len(peer.requests), 1)

    def test_buzzer_frequency_boundaries(self):
        self.peer()
        for value in (0, 1, 99, 100, 10000):
            hand.SetuHandBuzzer(value, 100)
            self.assertEqual(hand.GetStatus()["BuzzerFrequency"], value)

    def test_invalid_endpoints(self):
        for ip in ("localhost", "", " 127.0.0.1", "999.1.1.1", None, 127, "fe80::1%3"):
            with self.subTest(ip=ip), self.assertRaises(hand.InputValidationError):
                hand.Connect(ip, 5000)
        for port in (0, 65536, -1, True, 5000.0, "5000"):
            with self.assertRaises(hand.InputValidationError):
                hand.Connect("127.0.0.1", port)

    def test_disconnected_calls(self):
        self.assertIsNone(hand.Disconnect())
        for function in (
            hand.GetStatus, lambda: hand.SetuHandPulse(*([1500] * 6), 100),
            lambda: hand.SetuHandBuzzer(1000, 100), lambda: hand.SetuHandLED(True, False, False),
        ):
            with self.assertRaises(hand.NotConnectedError):
                function()

    def test_duplicate_connect_does_not_replace_session(self):
        peer = self.peer()
        with self.assertRaises(hand.AlreadyConnectedError):
            hand.Connect("127.0.0.1", peer.port)
        self.assertEqual(hand.GetStatus(), EMPTY)
        self.assertEqual(sum(r["method"] == "Hello" for r in peer.requests), 1)

    def test_second_client_is_rejected_without_losing_first(self):
        peer = self.peer()
        other = _transport._Client()
        try:
            with self.assertRaises(hand.BusyError):
                other.connect("127.0.0.1", peer.port)
            self.assertEqual(hand.GetStatus(), EMPTY)
        finally:
            other.disconnect()

    def test_disconnect_unblocks_waiter_and_server_finishes_without_retry(self):
        peer = self.peer()
        running = Call(lambda: hand.SetuHandPulse(*([1700] * 6), 500))
        self.assertTrue(peer.started.wait(1))
        hand.Disconnect()
        with self.assertRaises(hand.DisconnectedError):
            running.result()
        self.assertTrue(peer.owner_released.wait(1))
        hand.Connect("127.0.0.1", peer.port)
        with self.assertRaises(hand.BusyError):
            hand.SetuHandLED(True, False, False)
        deadline = time.monotonic() + 2
        while hand.GetStatus()["TargetPulses"] is None and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertEqual(hand.GetStatus()["TargetPulses"], [1700] * 6)
        self.assertEqual(sum(r["method"] == "SetuHandPulse" for r in peer.requests), 1)

    def test_connection_refused(self):
        with socket.socket() as reserved:
            reserved.bind(("127.0.0.1", 0))
            with self.assertRaises(hand.ConnectionFailedError):
                hand.Connect("127.0.0.1", reserved.getsockname()[1])

    def test_timeout_closes_connection_and_does_not_resend(self):
        def handler(peer, channel, req):
            if req["method"] == "Hello":
                channel.send(reply(req))
        peer = self.peer(handler)
        with patch.object(_transport, "RESPONSE_TIMEOUT", 0.1):
            with self.assertRaises(hand.RequestTimeoutError):
                hand.GetStatus()
        with self.assertRaises(hand.NotConnectedError):
            hand.GetStatus()
        self.assertEqual([r["method"] for r in peer.requests], ["Hello", "GetStatus"])

    def test_handshake_timeout_does_not_publish_connection(self):
        peer = self.peer(lambda *args: None, connect=False)
        with patch.object(_transport, "CONNECT_TIMEOUT", 0.1):
            with self.assertRaises(hand.RequestTimeoutError):
                hand.Connect("127.0.0.1", peer.port)
        with self.assertRaises(hand.NotConnectedError):
            hand.GetStatus()

    def test_remote_error_mapping_and_connection_survives(self):
        codes = iter(["BUSY", "DEVICE_ERROR", "UNSUPPORTED_FREQUENCY", "FUTURE_ERROR", "INVALID_ARGUMENT"])
        def handler(peer, channel, req):
            if req["method"] == "Hello":
                channel.send(reply(req))
            else:
                channel.send(reply(req, error={"code": next(codes), "message": "테스트 오류"}))
        self.peer(handler)
        for error in (hand.BusyError, hand.DeviceError, hand.UnsupportedFrequencyError, hand.RemoteError, hand.RemoteError):
            with self.assertRaises(error) as context:
                hand.GetStatus()
            self.assertEqual(context.exception.message, "테스트 오류")

    def test_fragmented_response_and_out_of_order_coalesced_frames(self):
        waiting = []
        def handler(peer, channel, req):
            if req["method"] == "Hello":
                data = encoded(reply(req))
                channel.raw(data[:5])
                channel.raw(data[5:])
            else:
                waiting.append(req)
                if len(waiting) == 2:
                    second = reply(waiting[1], copy.deepcopy(EMPTY))
                    first = reply(waiting[0])
                    channel.raw(encoded(second) + encoded(first))
        self.peer(handler)
        running = Call(lambda: hand.SetuHandPulse(*([1500] * 6), 100))
        deadline = time.monotonic() + 1
        while not waiting and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertEqual(hand.GetStatus(), EMPTY)
        self.assertIsNone(running.result())

    def test_many_concurrent_queries_match_request_ids(self):
        self.peer()
        calls = [Call(hand.GetStatus) for _ in range(50)]
        for call in calls:
            self.assertEqual(call.result(), EMPTY)

    def test_repeated_disconnect_reconnect_retains_server_status(self):
        peer = self.peer()
        hand.SetuHandLED(True, False, True)
        for _ in range(10):
            hand.Disconnect()
            self.assertTrue(peer.owner_released.wait(1))
            hand.Connect("127.0.0.1", peer.port)
            self.assertEqual(hand.GetStatus()["LED"], [255, 0, 255])

    def test_disconnect_during_connect_is_serialized(self):
        peer = self.peer(lambda *args: None, connect=False)
        with patch.object(_transport, "CONNECT_TIMEOUT", 0.15):
            connecting = Call(lambda: hand.Connect("127.0.0.1", peer.port))
            deadline = time.monotonic() + 1
            while not peer.requests and time.monotonic() < deadline:
                time.sleep(0.005)
            disconnecting = Call(hand.Disconnect)
            with self.assertRaises(hand.RequestTimeoutError):
                connecting.result()
            self.assertIsNone(disconnecting.result())
        with self.assertRaises(hand.NotConnectedError):
            hand.GetStatus()


if __name__ == "__main__":
    unittest.main()
