"""Predictive pose tracking: a constant-velocity Kalman filter per servo axis.

Every decision gives a measured target pose (the probability-weighted pose). The filter keeps a
position and a velocity per axis, so while the probabilities are still drifting from one gesture
to the next it already knows which way the hand is going, and `predict` extrapolates that to the
moment the robot will finish its next move. It cannot foresee a gesture before the muscle signal
changes; what it buys is an earlier start and a smooth path.

Axes are tracked in normalised units (-1..1 over the servo range), so one `accel` and `noise`
fit thumb, fingers and wrist alike. The six axes share F, Q and R, hence one 2x2 covariance.
"""
from __future__ import annotations

import numpy as np

MAX_DT = 0.5              # a longer pause between measurements restarts the velocity
MAX_AHEAD = 0.6           # never extrapolate further than this (s)


class PoseKalman:
    def __init__(self, lo: np.ndarray, hi: np.ndarray, accel: float = 12.0, noise: float = 0.5) -> None:
        self.lo, self.hi = np.asarray(lo, float), np.asarray(hi, float)
        self.mid, self.half = (self.lo + self.hi) / 2, (self.hi - self.lo) / 2
        self.accel, self.noise = float(accel), float(noise)
        self.reset()

    def reset(self, pulses: np.ndarray | None = None) -> None:
        self.x = None if pulses is None else np.c_[self._norm(pulses), np.zeros(6)]    # (6, 2) pos, vel
        self.P = np.diag([self.noise ** 2, 1.0])
        self.t: float | None = None

    def _norm(self, pulses) -> np.ndarray:
        return (np.asarray(pulses, float) - self.mid) / self.half

    def _pulses(self, u: np.ndarray) -> np.ndarray:
        return np.clip(u * self.half + self.mid, self.lo, self.hi)

    def update(self, target: np.ndarray, t: float, confidence: float = 1.0) -> np.ndarray:
        """One measurement at time t. A low `confidence` (0..1) makes the filter trust it less,
        so the hand moves slowly while the model is unsure. -> filtered pose (pulses)."""
        z = self._norm(target)
        if self.x is None:                           # first measurement: start there, at rest
            self.x = np.c_[z, np.zeros(6)]
            self.P = np.diag([self.noise ** 2, 1.0])
            self.t = t
            return self.position
        dt = t - self.t if self.t is not None else 0.0
        if 0 < dt <= MAX_DT:
            F = np.array([[1.0, dt], [0.0, 1.0]])
            g = np.array([dt * dt / 2, dt])
            self.x = self.x @ F.T
            self.P = F @ self.P @ F.T + np.outer(g, g) * self.accel ** 2
        else:                                        # after a pause: keep the position, drop the velocity
            self.x[:, 1] = 0.0
            self.P = np.diag([self.noise ** 2, 1.0])
        self._correct(z, confidence)
        self.t = t
        return self.position

    def _correct(self, z: np.ndarray, confidence: float) -> None:
        r = (self.noise / max(float(confidence), 0.05)) ** 2
        s = self.P[0, 0] + r
        k = self.P[:, 0] / s                         # (2,)
        self.x = self.x + np.outer(z - self.x[:, 0], k)
        self.P = self.P - np.outer(k, self.P[0])

    @property
    def position(self) -> np.ndarray:
        return self._pulses(self.x[:, 0])

    @property
    def velocity(self) -> np.ndarray:
        """Pulses per second."""
        return self.x[:, 1] * self.half

    def predict(self, t: float, ahead: float = 0.0, bounds: tuple[np.ndarray, np.ndarray] | None = None) -> np.ndarray:
        """Pose expected at time t + ahead. `bounds` (low, high pulses per axis) keeps the
        extrapolation inside the poses the hand could be heading for; the current position is
        always allowed, so a bound never makes the hand jump."""
        if self.x is None:
            return self.mid.copy()
        d = 0.0 if self.t is None else float(np.clip(t - self.t + ahead, 0.0, MAX_AHEAD))
        p = self._pulses(self.x[:, 0] + self.x[:, 1] * d)
        if bounds is not None:
            cur = self.position
            p = np.clip(p, np.minimum(bounds[0], cur), np.maximum(bounds[1], cur))
        return p
