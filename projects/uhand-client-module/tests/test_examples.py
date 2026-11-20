import json
from pathlib import Path
import subprocess
import sys
import unittest

from _peer import EMPTY, Peer

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
            return json.loads(result.stdout), [r["method"] for r in peer.requests]
        finally:
            peer.close()

    def test_read_only_example(self):
        result, methods = self.run_example("get_status.py")
        self.assertEqual(result, EMPTY)
        self.assertEqual(methods, ["Hello", "GetStatus"])

    def test_sequence_example(self):
        result, methods = self.run_example("basic_sequence.py")
        self.assertEqual(result["TargetPulses"], [1500, 1200, 1800, 1500, 1400, 1600])
        self.assertEqual(result["PulseRunningTime"], 1000)
        self.assertEqual(result["BuzzerFrequency"], 1000)
        self.assertEqual(result["BuzzerRunningTime"], 500)
        self.assertEqual(result["LED"], [0, 255, 0])
        # An independent read-only heartbeat can fall inside the 1000 ms pulse.
        self.assertEqual(methods[-1], "GetStatus")
        self.assertEqual([m for m in methods if m != "GetStatus"],
                         ["Hello", "SetuHandPulse", "SetuHandBuzzer", "SetuHandLED"])
