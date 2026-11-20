"""Exercise Windows system notification sounds with a controllable driver completion flag."""
import ctypes
import json
import socket
import threading
import time
import unittest

import numpy as np

from uhand_virtual_server._waveout import SAMPLE_RATE, WHDR_DONE, WindowsAudio as WaveOutput
from uhand_virtual_server.audio import WindowsAudio
from uhand_virtual_server.server import VirtualServer


class ControlledDevice:
    def __init__(self):
        self.buffers = []
        self.reset_headers = []
        self.silence = threading.Event()
        self.melody = threading.Event()

    def open(self):
        return 1

    def prepare(self, handle, header):
        pass

    def write(self, handle, header):
        pcm = ctypes.string_at(header.data, header.length)
        self.buffers.append((time.monotonic(), header, pcm))
        (self.melody if any(pcm) else self.silence).set()

    def reset(self, handle):
        self.reset_headers.append(self.buffers[-1][1])
        self.buffers[-1][1].flags |= WHDR_DONE

    def unprepare(self, handle, header):
        pass

    def close(self, handle):
        pass


class StartupAudioTests(unittest.TestCase):
    def setUp(self):
        self.device = ControlledDevice()
        audio = WindowsAudio()
        audio._output = WaveOutput(self.device)
        self.server = VirtualServer(port=0, audio=audio)
        self.addCleanup(self.server.shutdown)

    def assert_melody(self, pcm, notes):
        samples = np.frombuffer(pcm, dtype="<i2")
        length = SAMPLE_RATE * 175 // 1000
        step = SAMPLE_RATE // 4
        self.assertEqual(len(samples), (len(notes) - 1) * step + length)
        for index, hz in enumerate(notes):
            offset = index * step
            tone = samples[offset:offset + length]
            peak = np.argmax(np.abs(np.fft.rfft(tone))) * SAMPLE_RATE / length
            self.assertAlmostEqual(peak, hz, delta=4)
            self.assertFalse(samples[offset + length:offset + step].any())

    def finish_transition(self, phase, notes):
        self.assertTrue(self.device.melody.wait(2))
        (start, _, silence), (onset, header, pcm) = self.device.buffers[-2:]
        self.assertEqual(silence, bytes(SAMPLE_RATE))
        self.assertGreaterEqual(onset - start, .49)
        self.assertLess(onset - start, .85)
        self.assert_melody(pcm, notes)
        time.sleep((len(notes) - 1) * .25 + .22)
        self.assertEqual(self.server.snapshot()["phase"], phase)
        self.assertNotIn(header, self.device.reset_headers)
        header.flags |= WHDR_DONE
        deadline = time.monotonic() + 1
        while self.server.lifecycle.phase and time.monotonic() < deadline:
            time.sleep(.005)
        self.assertIsNone(self.server.lifecycle.phase)
        self.assertIsNone(self.server.lifecycle.error)
        self.assertNotIn(header, self.device.reset_headers)
        self.device.melody.clear()

    def test_connected_client_and_socket_close_use_buffered_notices(self):
        self.server.start(background=True)
        self.finish_transition("startup", (523, 659, 784))
        with socket.create_connection(("127.0.0.1", self.server.port), 3) as client:
            client.sendall(b'{"version":2,"request_id":1,"method":"Hello","params":{}}\n')
            self.finish_transition("connect", (659, 880))
            with client.makefile("rb") as reader:
                self.assertTrue(json.loads(reader.readline())["ok"])
        self.finish_transition("disconnect", (440, 370, 294))
        self.assertEqual(len(self.device.buffers), 6)

    def test_cold_start_waits_for_home_and_driver_completion(self):
        self.server.start(background=True)
        self.assertTrue(self.device.silence.wait(2))
        self.assertEqual(self.server.snapshot()["pulses"], [1500] * 6)
        self.assertEqual(self.server.lifecycle.phase, "startup")
        self.assertTrue(self.device.melody.wait(2))
        (start, _, silence), (first_note, header, pcm) = self.device.buffers
        self.assertEqual(silence, bytes(SAMPLE_RATE))
        self.assertGreaterEqual(first_note - start, .49)
        self.assertLess(first_note - start, .85)  # catches a duplicate 500 ms wait
        self.assert_melody(pcm, (523, 659, 784))
        time.sleep(.8)
        self.assertEqual(self.server.lifecycle.phase, "startup")
        self.assertNotIn(header, self.device.reset_headers)
        header.flags |= WHDR_DONE
        deadline = time.monotonic() + 1
        while self.server.lifecycle.phase and time.monotonic() < deadline:
            time.sleep(.005)
        self.assertIsNone(self.server.lifecycle.phase)
        self.assertFalse(self.server.lifecycle.error)
        self.assertNotIn(header, self.device.reset_headers)
        self.assertEqual(len(self.device.buffers), 2)

    def test_power_cut_during_prime_and_melody_then_restart(self):
        self.server.start(background=True)
        self.assertTrue(self.device.silence.wait(2))
        self.server.stop_listening()
        self.assertEqual(len(self.device.buffers), 1)
        self.assertIn(self.device.buffers[-1][1], self.device.reset_headers)
        self.server.start(background=True)
        self.assertTrue(self.device.melody.wait(2))
        self.server.stop_listening()
        self.assertEqual(len(self.device.buffers), 3)
        self.assertIn(self.device.buffers[-1][1], self.device.reset_headers)
        self.assertIsNone(self.server.snapshot()["buzzer_output"])
        self.device.melody.clear()
        self.server.start(background=True)
        self.assertTrue(self.device.melody.wait(2))
        self.assertEqual(len(self.device.buffers), 5)
        self.assertEqual(self.device.buffers[-1][2], self.device.buffers[2][2])
