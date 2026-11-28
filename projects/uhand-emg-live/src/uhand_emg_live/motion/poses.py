"""Robot poses: one six-servo pose per gesture, and how class probabilities mix them.

A pose is [thumb, index, middle, ring, little, wrist] in servo pulses. The limits are the
uHand's (uhand_client_module._validation.PULSE_LIMITS)."""
from __future__ import annotations

import numpy as np

AXES = ["엄지", "검지", "중지", "약지", "소지", "손목"]
LO = np.array([800, 800, 800, 800, 800, 500], float)
HI = np.array([2200, 2000, 2000, 2000, 2000, 2500], float)


class PoseTable:
    def __init__(self, poses: dict[str, list[int]]) -> None:
        self.poses: dict[str, np.ndarray] = {}
        for key, p in poses.items():
            a = np.asarray(p, float)
            if a.shape != (6,):
                raise ValueError(f"[poses] {key}: 값 6개가 필요합니다")
            if np.any(a < LO) or np.any(a > HI):
                raise ValueError(f"[poses] {key}: 서보 범위를 벗어났습니다 (엄지 800~2200, 손가락 800~2000, 손목 500~2500)")
            self.poses[key] = a
        self.home = self.poses.get("home", np.full(6, 1500.0))

    def pose(self, key: str) -> np.ndarray:
        """The pose of a gesture; a gesture without one keeps the hand at home."""
        return self.poses.get(key, self.home)

    def missing(self, gestures: list[str]) -> list[str]:
        return [g for g in gestures if g not in self.poses]

    def blend(self, gestures: list[str], proba: np.ndarray, sharpen: float = 2.0) -> np.ndarray:
        """Probability-weighted pose. `sharpen` > 1 leans towards the likeliest gesture, so two
        unrelated candidates do not average into a pose that means nothing."""
        w = np.asarray(proba, float) ** sharpen
        s = w.sum()
        if s <= 0:
            return self.home.copy()
        return sum(wi * self.pose(g) for wi, g in zip(w / s, gestures))

    def envelope(self, gestures: list[str], proba: np.ndarray, min_prob: float = 0.1):
        """(low, high) per axis over the poses of the plausible gestures: where a predicted
        pose may go. Always includes the likeliest gesture."""
        p = np.asarray(proba, float)
        keep = [g for g, pi in zip(gestures, p) if pi >= min_prob] or []
        keep.append(gestures[int(p.argmax())])
        ps = np.stack([self.pose(g) for g in keep])
        return ps.min(axis=0), ps.max(axis=0)
