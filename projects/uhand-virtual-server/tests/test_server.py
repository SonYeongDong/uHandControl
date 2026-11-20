import copy
import json
import socket
import threading
import time
import unittest

import uhand_client_module as hand
from uhand_client_module._transport import _Client
from uhand_server_lifecycle import reset_status
from uhand_virtual_server.protocol import CommandError
from uhand_virtual_server.server import VirtualServer


class TestAudio:
    def __init__(self):
        self.calls = []
        self.error = None
    def play(self, frequency, duration, cancel):
        if self.error:
            raise self.error
        self.calls.append((frequency, duration))
        cancel.wait(duration/1000)


class Call:
    def __init__(self, fn):
        self.error = None
        self.value = None
        self.done = threading.Event()
        def run():
            try:
                self.value = fn()
            except Exception as exc:
                self.error = exc
            finally:
                self.done.set()
        threading.Thread(target=run, daemon=True).start()
    def result(self, timeout=3):
        if not self.done.wait(timeout):
            raise AssertionError("Call did not finish")
        if self.error:
            raise self.error
        return self.value


class Wire:
    def __init__(self, port):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=5)
        self.reader = self.sock.makefile("rb")
        self.next = 1
    def request(self, method, params=None, **overrides):
        value = dict(version=2, request_id=self.next, method=method, params=params or {})
        self.next += 1
        value.update(overrides)
        self.sock.sendall(json.dumps(value).encode() + b"\n")
        return json.loads(self.reader.readline())
    def close(self):
        self.reader.close()
        self.sock.close()


class ServerTests(unittest.TestCase):
    def setUp(self):
        hand.Disconnect()
        self.audio = TestAudio()
        self.server = VirtualServer(port=0, audio=self.audio)
        self.server.start()
        self.wires = []
        hand.Connect("127.0.0.1", self.server.port)
    def tearDown(self):
        hand.Disconnect()
        for wire in self.wires:
            wire.close()
        self.server.shutdown()
        self.assertFalse(any(t.is_alive() for t in self.server.threads))

    def wait_for(self, predicate, timeout=4):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.005)
        self.fail("Condition timed out")

    def wire(self):
        hand.Disconnect()
        self.wait_for(lambda: self.server.owner is None and self.server.lifecycle.phase is None)
        wire = Wire(self.server.port)
        self.wires.append(wire)
        self.assertTrue(wire.request("Hello")["ok"])
        return wire

    def test_power_cut_freezes_moving_pose_and_interrupts_client(self):
        hand.SetuHandLED(True, False, False)
        previous = hand.GetStatus()
        before = self.audio.calls[:]
        pending = Call(lambda: hand.SetuHandPulse(*([1900]*6), 4000))
        self.wait_for(lambda: self.server.snapshot()["pulses"][0] > 1503)
        self.server.stop_listening()
        with self.assertRaises(hand.DisconnectedError):
            pending.result()
        off = self.server.snapshot()
        self.assertTrue(off["powered_off"])
        self.assertFalse(off["busy"] or off["connected"] or off["listening"])
        self.assertLess(1500, off["pulses"][0])
        self.assertLess(off["pulses"][0], 1900)
        self.assertEqual(off["status"], previous)
        time.sleep(.12)
        self.assertEqual(self.server.snapshot()["pulses"], off["pulses"])
        self.assertEqual(self.audio.calls, before)
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1",self.server.port), timeout=.5)
        self.server.stop_listening()
        self.server.start()
        hand.Connect("127.0.0.1",self.server.port)
        self.assertEqual(hand.GetStatus(), reset_status())
        self.assertEqual(self.audio.calls[len(before):], [(f,175) for f in (523,659,784,659,880)])

    def test_power_cut_interrupts_finite_audio_without_disconnect_chime(self):
        previous = hand.GetStatus()
        pending = Call(lambda: hand.SetuHandBuzzer(440, 20000))
        self.wait_for(lambda: (440, 20000) in self.audio.calls)
        start = time.monotonic()
        self.server.stop_listening()
        self.assertLess(time.monotonic() - start, 1)
        with self.assertRaises(hand.DisconnectedError):
            pending.result()
        self.assertIsNone(self.server.snapshot()["buzzer_output"])
        self.assertEqual(self.audio.calls[-1], (440, 20000))
        self.assertEqual(self.server.snapshot()["status"], previous)

    def test_power_cut_cancels_startup_and_pending_handshake(self):
        self.server.stop_listening()
        self.server.start(background=True)
        self.wait_for(lambda: self.server.motion is not None)
        before = self.audio.calls[:]
        self.server.stop_listening()
        self.assertEqual(self.audio.calls, before)
        self.server.start()
        pending = Call(lambda: hand.Connect("127.0.0.1", self.server.port))
        self.wait_for(lambda: self.server.lifecycle.phase == "connect")
        self.server.stop_listening()
        with self.assertRaises(hand.DisconnectedError):
            pending.result()
        self.assertIsNone(self.server.lifecycle.phase)
        self.assertFalse(self.server.threads)
        self.assertEqual(self.audio.calls[-3:], [(523,175),(659,175),(784,175)])

    def test_completed_home_and_chimes_on_connect(self):
        self.assertEqual(hand.GetStatus(), reset_status())
        self.assertEqual(self.server.snapshot()["pulses"], [1500]*6)
        self.assertEqual(self.audio.calls, [(f,175) for f in (523,659,784,659,880)])
        self.assertFalse(self.server.busy)

    def test_pulse_moves_interpolates_and_commits_after_duration(self):
        target = [800,2000,1200,1800,900,1700]
        start = time.monotonic()
        running = Call(lambda: hand.SetuHandPulse(*target, 500))
        self.wait_for(lambda: self.server.motion is not None)
        time.sleep(0.08)
        snapshot = self.server.snapshot()
        self.assertNotEqual(snapshot["pulses"], target)
        self.assertNotEqual(snapshot["pulses"], [1500]*6)
        self.assertEqual(hand.GetStatus(), reset_status())
        running.result()
        self.assertGreaterEqual(time.monotonic()-start, 0.49)
        self.assertEqual(hand.GetStatus()["TargetPulses"], target)
        self.assertEqual(self.server.snapshot()["pulses"], target)

    def test_previous_completed_state_during_next_move(self):
        hand.SetuHandPulse(*([800]*6), 100)
        running = Call(lambda: hand.SetuHandPulse(*([2000]*6), 500))
        self.wait_for(lambda: self.server.motion is not None)
        self.assertEqual(hand.GetStatus()["TargetPulses"], [800]*6)
        self.assertEqual(hand.GetStatus()["PulseRunningTime"], 100)
        self.assertFalse(running.done.is_set())
        running.result()
        self.assertEqual(hand.GetStatus()["PulseRunningTime"], 500)

    def test_maximum_20000ms_is_supported(self):
        start = time.monotonic()
        hand.SetuHandPulse(*([1500]*6), 20000)
        self.assertGreaterEqual(time.monotonic()-start, 19.9)
        self.assertEqual(hand.GetStatus()["PulseRunningTime"], 20000)

    def test_buzzer_frequency_time_and_previous_status(self):
        hand.SetuHandBuzzer(1000,100)
        running = Call(lambda: hand.SetuHandBuzzer(1900,500))
        self.wait_for(lambda: self.server.busy)
        status = hand.GetStatus()
        self.assertEqual((status["BuzzerFrequency"],status["BuzzerRunningTime"]), (1000,100))
        running.result()
        self.assertEqual(hand.GetStatus()["BuzzerFrequency"], 1900)
        self.assertEqual(self.audio.calls[-2:], [(1000,100),(1900,500)])

    def test_led_all_combinations_and_independent_records(self):
        hand.SetuHandBuzzer(1000,100)
        for i in range(8):
            rgb = [bool(i & (1<<j)) for j in range(3)]
            hand.SetuHandLED(*rgb)
            status = hand.GetStatus()
            self.assertEqual(status["LED"], [255 * v for v in rgb])
            self.assertEqual(status["BuzzerFrequency"],1000)
            self.assertEqual(status["TargetPulses"], [1500]*6)

    def test_busy_output_but_status_does_not_wait(self):
        running = Call(lambda: hand.SetuHandPulse(*([1700]*6),600))
        self.wait_for(lambda: self.server.busy)
        for fn in (lambda: hand.SetuHandPulse(*([1500]*6),100),
                   lambda: hand.SetuHandBuzzer(1000,100),
                   lambda: hand.SetuHandLED(True,False,False)):
            with self.assertRaises(hand.BusyError):
                fn()
        start = time.monotonic()
        self.assertEqual(hand.GetStatus(), reset_status())
        self.assertLess(time.monotonic()-start, 0.3)
        running.result()

    def test_disconnect_cancels_old_motion_and_resets(self):
        running = Call(lambda: hand.SetuHandPulse(*([2000]*6),20000))
        self.wait_for(lambda: self.server.busy)
        hand.Disconnect()
        with self.assertRaises(hand.DisconnectedError):running.result()
        self.wait_for(lambda: self.server.owner is None and self.server.lifecycle.phase is None)
        self.assertEqual(self.audio.calls[-3:],[(440,175),(370,175),(294,175)])
        hand.Connect("127.0.0.1", self.server.port)
        self.assertEqual(hand.GetStatus(), reset_status())

    def test_single_client_ownership(self):
        other = _Client()
        try:
            with self.assertRaises(hand.BusyError):
                other.connect("127.0.0.1",self.server.port)
            self.assertEqual(hand.GetStatus(), reset_status())
        finally:
            other.disconnect()

    def test_audio_failure_does_not_commit_or_stick_busy(self):
        hand.SetuHandBuzzer(1000,100)
        self.audio.error = CommandError("DEVICE_ERROR","Output unavailable")
        with self.assertRaises(hand.DeviceError):
            hand.SetuHandBuzzer(1900,100)
        self.assertEqual(hand.GetStatus()["BuzzerFrequency"],1000)
        self.assertFalse(self.server.busy)
        self.audio.error = None
        hand.SetuHandLED(True,False,False)
        self.assertEqual(hand.GetStatus()["LED"],[255,0,0])

    def test_unsupported_frequency_preserves_state(self):
        self.audio.error = CommandError("UNSUPPORTED_FREQUENCY","Above Nyquist")
        with self.assertRaises(hand.UnsupportedFrequencyError):
            hand.SetuHandBuzzer(10000,100)
        self.assertEqual(hand.GetStatus()["BuzzerFrequency"],0)

    def test_unexpected_audio_exception_maps_to_device_error(self):
        self.audio.error = RuntimeError("backend failed")
        with self.assertRaises(hand.DeviceError):
            hand.SetuHandBuzzer(1000,100)
        self.assertFalse(self.server.busy)

    def test_many_queries_and_independent_snapshot_copies(self):
        calls = [Call(hand.GetStatus) for _ in range(40)]
        for call in calls:
            self.assertEqual(call.result(), reset_status())
        returned = self.server.snapshot()
        returned["status"]["LED"] = [True]*3
        self.assertEqual(hand.GetStatus()["LED"], [False]*3)

    def test_restart_resets_records(self):
        hand.SetuHandLED(True,True,True)
        hand.Disconnect()
        self.server.shutdown()
        self.server = VirtualServer(port=0,audio=self.audio)
        self.server.start()
        hand.Connect("127.0.0.1",self.server.port)
        self.assertEqual(hand.GetStatus(), reset_status())

    def test_existing_port_is_not_silently_replaced(self):
        other = VirtualServer(port=self.server.port)
        with self.assertRaises(OSError):
            other.start()
        self.assertEqual(hand.GetStatus(), reset_status())

    def test_drain_preserves_inflight_command(self):
        running = Call(lambda: hand.SetuHandPulse(*([900]*6),400))
        self.wait_for(lambda: self.server.busy)
        self.server.drain()
        with self.assertRaises(hand.DisconnectedError):
            running.result()
        self.wait_for(lambda: not self.server.busy)
        self.assertEqual(self.server.status["TargetPulses"],[900]*6)

    def test_raw_invalid_inputs_rejected_without_output(self):
        wire = self.wire()
        valid = dict(Finger1Pulse=1500,Finger2Pulse=1500,Finger3Pulse=1500,
                     Finger4Pulse=1500,Finger5Pulse=1500,WristPulse=1500,RunningTime=100)
        for key in valid:
            for value in (True,None,"1500",0,99999):
                params = dict(valid, **{key:value})
                with self.subTest(key=key,value=value):
                    response = wire.request("SetuHandPulse",params)
                    self.assertEqual(response["error"]["code"],"INVALID_ARGUMENT")
        self.assertEqual(wire.request("GetStatus", {"IncludeLEDBrightness":True})["result"],reset_status())
        self.assertFalse(self.server.busy)

    def test_unknown_method_and_bad_keys(self):
        wire = self.wire()
        for method,params,code in (
            ("Stop",{},"UNKNOWN_METHOD"),("GetStatus",{"x":1},"INVALID_ARGUMENT"),
            ("SetuHandLED",{"RedEnable":1,"GreenEnable":False,"BlueEnable":False},"INVALID_ARGUMENT"),
            ("SetuHandBuzzer",{"Frequency":-1,"RunningTime":100},"INVALID_ARGUMENT"),
        ):
            self.assertEqual(wire.request(method,params)["error"]["code"],code)
        self.assertEqual(wire.request("GetStatus", {"IncludeLEDBrightness":True})["result"],reset_status())

    def test_version_and_extra_field_rejection(self):
        wire = self.wire()
        self.assertEqual(wire.request("GetStatus",version=1)["error"]["code"],"UNSUPPORTED_VERSION")
        self.assertEqual(wire.request("GetStatus",extra=1)["error"]["code"],"INVALID_ARGUMENT")

    def test_request_ids_may_arrive_out_of_order(self):
        wire = self.wire()
        self.assertTrue(wire.request("GetStatus",request_id=100)["ok"])
        self.assertTrue(wire.request("GetStatus",request_id=50)["ok"])

    def test_duplicate_id_closes_without_reexecuting(self):
        wire = self.wire()
        self.assertTrue(wire.request("GetStatus",request_id=50)["ok"])
        wire.sock.sendall(b'{"version":2,"request_id":50,"method":"GetStatus","params":{}}\n')
        self.assertEqual(wire.reader.readline(),b"")

    def test_bad_frame_closes_and_next_client_can_connect(self):
        for frame in (b"\xff\n",b"[]\n",b'{"request_id":2,"request_id":2}\n',b"x"*65536):
            wire = self.wire()
            wire.sock.sendall(frame)
            self.assertEqual(wire.reader.readline(),b"")
            self.wait_for(lambda: self.server.owner is None and self.server.lifecycle.phase is None)
            hand.Connect("127.0.0.1",self.server.port)
            self.assertEqual(hand.GetStatus(),reset_status())

    def test_fragmented_and_multiple_requests(self):
        wire = self.wire()
        first=b'{"version":2,"request_id":10,"method":"GetStatus","params":{}}\n'
        second=b'{"version":2,"request_id":11,"method":"GetStatus","params":{}}\n'
        wire.sock.sendall(first[:15])
        wire.sock.sendall(first[15:]+second)
        self.assertEqual(json.loads(wire.reader.readline())["request_id"],10)
        self.assertEqual(json.loads(wire.reader.readline())["request_id"],11)


if __name__ == "__main__":
    unittest.main()
