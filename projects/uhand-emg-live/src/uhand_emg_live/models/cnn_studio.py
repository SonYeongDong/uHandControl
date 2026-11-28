"""The studio's CNN (models/*.npz, trained with `python -m studio.gesture.train`).

200 ms windows, a decision every 100 ms, averaged over the last 0.4 s. Needs a calibration of
the band placement (about 40 s, no labels): channel levels and BatchNorm statistics (AdaBN).
Its view is the t-SNE map of training windows stored in the model file.
"""
from __future__ import annotations

import glob
import os

import numpy as np

from .base import Decision, GestureModel, ModelSpec
from .cnn_net import CENTER, GestureNet, LiveDecoder


class StudioCNN(GestureModel):
    view = "bars"
    delay_s = 0.2
    needs_calibration = True

    def __init__(self, path: str) -> None:
        self.net = GestureNet.load(path)
        m = self.net.meta
        labels = m["labels"]
        self.gestures = [labels.get(str(c), str(c)) for c in self.net.classes]
        self.title = os.path.splitext(os.path.basename(path))[0]
        ev = m.get("eval_leave_one_wear_out", {}).get("mean")
        self.info = (f"CNN · {', '.join(m.get('people', []))} · 시도 {m.get('trials', '?')}개로 학습"
                     + (f" · 새로 찼을 때 예상 정확도 {100 * ev:.0f}%" if ev else ""))
        self.dec = LiveDecoder(self.net)
        if self.net.map is not None:
            self.view = "map"

    def reset(self) -> None:
        self.dec.reset()

    def feed(self, t: np.ndarray, x: np.ndarray) -> list[Decision]:
        out = self.dec.feed(t, np.asarray(x, np.float64) - CENTER)
        if not out:
            return []
        xy = self.net.map.place(np.stack([d.emb for d in out])) if self.net.map is not None else [None] * len(out)
        return [Decision(d.t, d.proba, d.raw, {"xy": p} if p is not None else {}) for d, p in zip(out, xy)]

    def view_data(self) -> dict:
        m = self.net.map
        if m is None:
            return {}
        labels = self.net.meta["labels"]
        return {"xy": m.xy, "keys": [labels.get(str(int(c)), str(int(c))) for c in m.label]}

    # ------------------------------------------------------------ calibration
    def calibration_start(self) -> None:
        self.dec.start_collecting()

    def calibration_cancel(self) -> None:
        self.dec.collecting = False
        self.dec.collected = []

    def calibration_finish(self) -> tuple[bool, str]:
        place = self.dec.finish_collecting()
        if place is None:
            return False, "보정 실패: 신호가 부족합니다 (연결과 밴드를 확인하세요)"
        return True, f"창 {place.windows}개로 보정됨"

    @property
    def calibrated(self) -> bool:
        return self.dec.placement.windows > 0


def find(models_dir: str) -> list[ModelSpec]:
    return [ModelSpec(os.path.splitext(os.path.basename(p))[0], "CNN", p, lambda p=p: StudioCNN(p))
            for p in sorted(glob.glob(os.path.join(models_dir, "*.npz")))]
