import json
from pathlib import Path
import subprocess
import sys
import unittest

from _peer import EMPTY, PULSES, Peer

ROOT = Path(__file__).resolve().parents[1]


class ExampleTests(unittest.TestCase):
    def run_example(self, filename):
        peer = Peer()
        try:
            result = subprocess.run(
                [sys.executable, "-I", "-S", "-B", str(ROOT / "examples" / filename), "--port", str(peer.port)],
                cwd=Path(sys.executable).parent, text=True, capture_output=True, timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout), peer.requests.copy()
        finally:
            peer.close()

    def test_read_only_example(self):
        result, requests = self.run_example("get_status.py")
        methods = [req["method"] for req in requests]
        self.assertEqual(result, EMPTY)
        self.assertEqual(methods, ["Hello", "GetStatus"])

    def test_sequence_example(self):
        result, requests = self.run_example("basic_sequence.py")
        methods = [req["method"] for req in requests]
        pulses = [req["params"] for req in requests if req["method"] == "SetuHandPulse"]
        self.assertEqual(len(pulses), 5)
        for number, params in enumerate(pulses, start=1):
            expected = [1000 if number == 5 else 2000]
            expected.extend(2000 if finger <= number else 1000 for finger in range(1, 5))
            self.assertEqual([params[name] for name in PULSES], expected + [1500])
            self.assertEqual(params["RunningTime"], 1200)
        self.assertEqual(result["TargetPulses"], [1000, 2000, 2000, 2000, 2000, 1500])
        self.assertEqual(result["PulseRunningTime"], 1200)
        self.assertEqual(result["BuzzerFrequency"], 1000)
        self.assertEqual(result["BuzzerRunningTime"], 500)
        self.assertEqual(result["LED"], [0, 255, 0])
        # A read-only heartbeat may arrive during a movement.
        self.assertEqual(methods[-1], "GetStatus")
        self.assertEqual([m for m in methods if m != "GetStatus"],
                         ["Hello"] + ["SetuHandPulse"] * 5 + ["SetuHandBuzzer", "SetuHandLED"])
