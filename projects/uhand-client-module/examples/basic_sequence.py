"""Count from one to five on the hand, then sound the buzzer and light the LEDs."""
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
    parser = argparse.ArgumentParser(description="Count from one to five on a uHand server.")
    parser.add_argument("--ip", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000, help="Server port (default: 5000)")
    args = parser.parse_args()
    try:
        hand.Connect(args.ip, args.port)
        # 엄지, 검지, 중지, 약지, 소지, 손목 순서입니다. 각 자세로 1.2초 동안 이동합니다.
        hand.SetuHandPulse(2000, 2000, 1000, 1000, 1000, 1500, 1200)  # 1: 검지
        hand.SetuHandPulse(2000, 2000, 2000, 1000, 1000, 1500, 1200)  # 2: 중지 추가
        hand.SetuHandPulse(2000, 2000, 2000, 2000, 1000, 1500, 1200)  # 3: 약지 추가
        hand.SetuHandPulse(2000, 2000, 2000, 2000, 2000, 1500, 1200)  # 4: 소지 추가
        hand.SetuHandPulse(1000, 2000, 2000, 2000, 2000, 1500, 1200)  # 5: 엄지 추가
        hand.SetuHandBuzzer(1000, 500)
        hand.SetuHandLED(False, True, False)
        print(json.dumps(hand.GetStatus(), indent=2, ensure_ascii=False))
    except hand.UHandError as exc:
        parser.exit(1, f"{type(exc).__name__}: {exc}\n")
    finally:
        hand.Disconnect()


if __name__ == "__main__":
    main()
