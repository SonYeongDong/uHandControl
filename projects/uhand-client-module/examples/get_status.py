"""Read state without issuing any output command. Start a compatible server first."""
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
    parser = argparse.ArgumentParser(description="Read the uHand server's last completed state.")
    parser.add_argument("--ip", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000, help="Server port (default: 5000)")
    args = parser.parse_args()
    try:
        hand.Connect(args.ip, args.port)
        print(json.dumps(hand.GetStatus(), indent=2, ensure_ascii=False))
    except hand.UHandError as exc:
        parser.exit(1, f"{type(exc).__name__}: {exc}\n")
    finally:
        hand.Disconnect()


if __name__ == "__main__":
    main()
