"""Execute sample outputs on the specified server; localhost is the default."""
import argparse
import json
from pathlib import Path
import sys

# When run from the repository, use its matching client source.
source_dir = Path(__file__).resolve().parents[1] / "src"
if (source_dir / "uhand_client_module" / "__init__.py").is_file():
    sys.path.insert(0, str(source_dir))

import uhand_client_module as hand


def main():
    parser = argparse.ArgumentParser(description="Run pulse, buzzer and LED commands on a uHand server.")
    parser.add_argument("--ip", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000, help="Server port (default: 5000)")
    args = parser.parse_args()
    try:
        hand.Connect(args.ip, args.port)
        hand.SetuHandPulse(1500, 1200, 1800, 1500, 1400, 1600, 1000)
        hand.SetuHandBuzzer(1000, 500)
        hand.SetuHandLED(False, True, False)
        print(json.dumps(hand.GetStatus(), indent=2, ensure_ascii=False))
    except hand.UHandError as exc:
        parser.exit(1, f"{type(exc).__name__}: {exc}\n")
    finally:
        hand.Disconnect()


if __name__ == "__main__":
    main()
