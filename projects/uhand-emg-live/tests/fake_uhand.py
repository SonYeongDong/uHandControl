"""A minimal stand-in for the uHand server (protocol version 2, one JSON object per line), for
tests and for trying the sender without the robot or uHandVirtualServer:

    python -m tests.fake_uhand            # listens on 127.0.0.1:5000 and prints each move

Like the real server it answers a move when the move is finished.
"""
from __future__ import annotations

import json
import socket
import threading
import time


class FakeUHand:
    def __init__(self, port: int = 0, verbose: bool = False) -> None:
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", port))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.moves: list[tuple[list[int], int]] = []
        self.commands: list[tuple[str, dict]] = []       # every output command, in order
        self.verbose = verbose
        self._stop = threading.Event()
        self._conn: socket.socket | None = None
        threading.Thread(target=self._serve, daemon=True).start()

    def close(self) -> None:
        self._stop.set()
        self.drop()
        self.sock.close()

    def drop(self) -> None:
        """Cut the current client off, as a cable pull would."""
        if self._conn is not None:
            try:
                self._conn.close()
            except OSError:
                pass

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            self._conn = conn
            try:
                self._client(conn)
            except OSError:
                pass
            finally:
                conn.close()

    def _client(self, conn: socket.socket) -> None:
        buf = b""
        target, ms = None, None
        while not self._stop.is_set():
            data = conn.recv(4096)
            if not data:
                return
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                req = json.loads(line)
                result = None
                if req["method"].startswith("Set"):
                    self.commands.append((req["method"], req["params"]))
                if req["method"] == "SetuHandBuzzer":
                    if self.verbose:
                        print(f"{time.strftime('%H:%M:%S')}  buzzer {req['params']}", flush=True)
                    if not req["params"].get("Continuous"):
                        time.sleep(req["params"]["RunningTime"] / 1000)
                elif req["method"] == "SetuHandLED":
                    if self.verbose:
                        print(f"{time.strftime('%H:%M:%S')}  led {req['params']}", flush=True)
                elif req["method"] == "SetuHandPulse":
                    p = req["params"]
                    target = [p[f"Finger{i}Pulse"] for i in range(1, 6)] + [p["WristPulse"]]
                    ms = p["RunningTime"]
                    self.moves.append((target, ms))
                    if self.verbose:
                        print(f"{time.strftime('%H:%M:%S')}  {target}  {ms} ms", flush=True)
                    time.sleep(ms / 1000)
                elif req["method"] == "GetStatus":
                    result = {"TargetPulses": target, "PulseRunningTime": ms, "BuzzerFrequency": None,
                              "BuzzerRunningTime": None, "BuzzerContinuous": None, "LED": None}
                    if req["params"].get("IncludeLEDBrightness"):
                        result["LEDBrightness"] = None
                reply = {"version": 2, "request_id": req["request_id"], "ok": True, "result": result}
                conn.sendall(json.dumps(reply).encode() + b"\n")


if __name__ == "__main__":
    server = FakeUHand(5000, verbose=True)
    print(f"가짜 uHand 서버: 127.0.0.1:{server.port} (Ctrl+C 로 종료)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server.close()
