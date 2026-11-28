"""The confirmed gesture: switches only after a new gesture has been the decision `hold` times
in a row with probability >= `min_prob`. Stops flicker between two close gestures at the cost
of (hold - 1) more decisions of delay."""
from __future__ import annotations


class Stabilizer:
    def __init__(self, min_prob: float = 0.6, hold: int = 3) -> None:
        self.min_prob, self.hold = float(min_prob), max(1, int(hold))
        self.reset()

    def reset(self) -> None:
        self.shown: str | None = None
        self._cand: str | None = None
        self._n = 0

    def update(self, gesture: str, prob: float) -> str | None:
        if gesture == self.shown:
            self._cand, self._n = None, 0
        elif prob >= self.min_prob:
            self._n = self._n + 1 if gesture == self._cand else 1
            self._cand = gesture
            if self._n >= self.hold:
                self.shown, self._cand, self._n = gesture, None, 0
        else:
            self._cand, self._n = None, 0
        return self.shown
