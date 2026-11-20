"""Read state without issuing any output command. Start a compatible server first."""
import argparse
import json

import uhand_client_module as hand


def main():
    parser = argparse.ArgumentParser(description="Read the uHand server's last completed state.")
    parser.add_argument("--ip", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
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
