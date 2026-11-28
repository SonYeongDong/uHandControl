"""A stand-in for the robot hand: each motion command moves the six servos in a straight line
from where they are to the target over its running time, as the real hand does, and the LED and
buzzer hold what they were last told. The screen draws this, and it runs the same whether or
not a robot is connected."""
from __future__ import annotations

import threading
import time

import numpy as np

HOME = np.full(6, 1500.0)


class HandSim:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._from = HOME.copy()
        self._to = HOME.copy()
        self._t0 = 0.0
        self._dur = 0.0
        self._led = (0, 0, 0)
        self._tone, self._tone_until = 0, 0.0        # Hz; until = inf for a continuous tone

    # ------------------------------------------------------------ servos
    def command(self, pulses, ms: float, now: float | None = None) -> None:
        now = time.perf_counter() if now is None else now
        with self._lock:
            self._from = self._at(now)
            self._to = np.asarray(pulses, float).copy()
            self._t0, self._dur = now, max(ms, 0.0) / 1000.0

    def _at(self, now: float) -> np.ndarray:
        if self._dur <= 0:
            return self._to.copy()
        k = min(1.0, max(0.0, (now - self._t0) / self._dur))
        return self._from + (self._to - self._from) * k

    def position(self, now: float | None = None) -> np.ndarray:
        with self._lock:
            return self._at(time.perf_counter() if now is None else now)

    @property
    def target(self) -> np.ndarray:
        with self._lock:
            return self._to.copy()

    # ------------------------------------------------------------ LED and buzzer
    def set_led(self, red: int, green: int, blue: int, brightness: int = 100) -> None:
        with self._lock:
            self._led = tuple(int(c * brightness / 100) for c in (red, green, blue))

    def set_buzzer(self, frequency: int, ms: float, continuous: bool, now: float | None = None) -> None:
        now = time.perf_counter() if now is None else now
        with self._lock:
            self._tone = int(frequency)
            self._tone_until = float("inf") if continuous else now + ms / 1000.0

    def reset_outputs(self) -> None:
        with self._lock:
            self._led, self._tone, self._tone_until = (0, 0, 0), 0, 0.0

    @property
    def led(self) -> tuple[int, int, int]:
        """The LED's colour as shown (brightness applied); (0, 0, 0) = off."""
        with self._lock:
            return self._led

    def tone(self, now: float | None = None) -> int:
        """The frequency sounding now, 0 = silent."""
        now = time.perf_counter() if now is None else now
        with self._lock:
            return self._tone if now < self._tone_until else 0
