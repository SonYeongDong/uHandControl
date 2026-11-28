"""The only thread that talks to the robot hand.

It asks its driver (app.robot.drivers) for one command at a time and carries it out: a hand
motion, an LED colour, a buzzer tone or a pause. A motion or a timed tone occupies the robot for
its running time (the real hand needs at least 250 ms per move), so the next command is asked
for when that time is over, and it is always the newest one: nothing is queued or re-sent.

With no endpoint the same loop drives only the on-screen simulation, with the same timing. A
failed connection or command is retried every RETRY_S.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass

import numpy as np

import uhand_client_module as hand
from .drivers import Command, go_home
from .sim import HOME, HandSim

RETRY_S = 2.0
IDLE_S = 0.02

OFF, CONNECTING, CONNECTED, RETRY = "off", "connecting", "connected", "retry"


@dataclass(frozen=True)
class SenderStatus:
    state: str = OFF                    # off (simulation only) | connecting | connected | retry
    endpoint: str = ""
    sent: int = 0                       # commands the robot accepted
    failed: int = 0
    rate: float = 0.0                   # commands per second, last 2 s
    rtt_ms: float | None = None         # last command: send -> reply
    rtt_avg_ms: float | None = None
    last: tuple[int, ...] | None = None  # last pose commanded (also when only simulated)
    last_ms: int = 0
    last_age: float | None = None       # seconds since the last command of any kind
    last_text: str = ""                 # that command, in words
    error: str = ""


class _Attempt(threading.Thread):
    """One connection attempt. Connecting can take seconds (an unreachable robot times out after
    five), so it runs beside the send loop: the on-screen hand keeps moving meanwhile."""

    def __init__(self, endpoint: tuple[str, int]) -> None:
        super().__init__(name="robot-connect", daemon=True)
        self.endpoint = endpoint
        self.error: str | None = "연결 중"                       # None once connected

    def run(self) -> None:
        try:
            hand.Connect(*self.endpoint)
            self.error = None
        except hand.UHandError as e:
            self.error = str(e)


def describe(cmd: Command) -> str:
    if cmd.kind == "motion":
        return f"손동작 {cmd.args[6]} ms"
    if cmd.kind == "led":
        r, g, b, brightness = cmd.args
        return "LED 끔" if not (r or g or b) or not brightness else f"LED {r},{g},{b} · {brightness}%"
    if cmd.kind == "buzzer":
        hz, ms, continuous = cmd.args
        return "부저 끔" if not hz else (f"부저 {hz} Hz 연속" if continuous else f"부저 {hz} Hz {ms} ms")
    return f"대기 {cmd.args[0]} ms"


class RobotSender:
    def __init__(self, driver, sim: HandSim) -> None:
        self.sim = sim
        self._driver = driver
        self._new_driver = driver           # taken over (and reset) by the thread
        self._lock = threading.Lock()
        self._want: tuple[str, int] | None = None
        self._status = SenderStatus()
        self._times: deque[float] = deque()
        self._rtts: deque[float] = deque(maxlen=20)
        self._last: tuple[int, ...] | None = None
        self._last_ms = 0
        self._last_t: float | None = None
        self._last_text = ""
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="robot-sender", daemon=True)

    # ------------------------------------------------------------ control (any thread)
    def start(self) -> None:
        self._thread.start()

    def set_endpoint(self, endpoint: tuple[str, int] | None) -> None:
        """None = simulation only."""
        with self._lock:
            self._want = endpoint

    def set_driver(self, driver) -> None:
        """Hand the robot to another driver; it takes over when the current command is done."""
        with self._lock:
            self._new_driver = driver

    def close(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=3)

    def status(self) -> SenderStatus:
        now = time.perf_counter()
        with self._lock:
            while self._times and now - self._times[0] > 2.0:
                self._times.popleft()
            s = self._status
            return SenderStatus(s.state, s.endpoint, s.sent, s.failed, len(self._times) / 2.0, s.rtt_ms,
                                float(np.mean(self._rtts)) if self._rtts else None, self._last, self._last_ms,
                                None if self._last_t is None else now - self._last_t, self._last_text, s.error)

    def _set(self, **kw) -> None:
        with self._lock:
            self._status = SenderStatus(**{**self._status.__dict__, **kw})

    # ------------------------------------------------------------ the thread
    def _run(self) -> None:
        current: tuple[str, int] | None = None
        connected = False
        next_try = 0.0
        attempt: _Attempt | None = None                          # a connection being made, off this loop
        driver = None
        try:
            while not self._stop.is_set():
                with self._lock:
                    want, new_driver = self._want, self._new_driver
                if new_driver is not driver:                     # another driver takes over
                    driver = self._driver = new_driver
                    driver.reset()
                if want != current and attempt is None:          # endpoint changed: start over
                    if connected:
                        self._park()
                    hand.Disconnect()
                    connected, current, next_try = False, want, 0.0
                    driver.reset()
                    self._set(state=OFF if want is None else CONNECTING, error="",
                              endpoint="" if want is None else f"{want[0]}:{want[1]}")
                if current is not None and not connected and attempt is None and time.monotonic() >= next_try:
                    attempt = _Attempt(current)
                    attempt.start()
                if attempt is not None and not attempt.is_alive():
                    error, attempt = attempt.error, None
                    if error is None:
                        connected = True
                        self.sim.command(HOME, 0)                # the server homes itself on connect
                        self.sim.reset_outputs()
                        driver.reset()
                        self._set(state=CONNECTED, error="")
                    else:                                        # stays "retry" until a connection succeeds
                        hand.Disconnect()
                        next_try = time.monotonic() + RETRY_S
                        self._set(state=RETRY, error=error)
                cmd = driver.step()
                if cmd is None:
                    self._stop.wait(IDLE_S)
                    continue
                t0 = time.perf_counter()
                self._show(cmd, t0)
                if connected and cmd.kind != "wait":
                    try:
                        self._send(cmd)
                        rtt = 1000 * (time.perf_counter() - t0)
                        with self._lock:
                            self._times.append(time.perf_counter())
                            self._rtts.append(rtt)
                        self._set(sent=self._status.sent + 1, rtt_ms=rtt)
                    except hand.UHandError as e:
                        hand.Disconnect()
                        connected = False
                        next_try = time.monotonic() + RETRY_S
                        self._set(state=RETRY, error=str(e), failed=self._status.failed + 1)
                # one command at a time, whether the server waited for it or not
                self._stop.wait(max(0.0, cmd.takes_ms / 1000.0 - (time.perf_counter() - t0)))
        finally:
            if attempt is not None:
                attempt.join(timeout=6)
                connected = connected or attempt.error is None
            if connected:
                self._park()
            hand.Disconnect()
            self._set(state=OFF)

    def _show(self, cmd: Command, now: float) -> None:
        """Apply the command to the on-screen hand and remember it for the status panel."""
        if cmd.kind == "motion":
            self.sim.command(cmd.args[:6], cmd.args[6], now)
        elif cmd.kind == "led":
            self.sim.set_led(*cmd.args)
        elif cmd.kind == "buzzer":
            self.sim.set_buzzer(*cmd.args, now=now)
        with self._lock:
            if cmd.kind == "motion":
                self._last, self._last_ms = tuple(int(v) for v in cmd.args[:6]), int(cmd.args[6])
            self._last_t, self._last_text = now, describe(cmd)

    @staticmethod
    def _send(cmd: Command) -> None:
        if cmd.kind == "motion":
            hand.SetuHandPulse(*(int(v) for v in cmd.args))
        elif cmd.kind == "led":
            hand.SetuHandLED(*cmd.args)
        elif cmd.kind == "buzzer":
            hand.SetuHandBuzzer(*cmd.args)

    def _park(self) -> None:
        """Leave the hand at home, dark and silent, before letting go of the connection."""
        try:
            for cmd in go_home():
                self._send(cmd)
        except hand.UHandError:
            pass
