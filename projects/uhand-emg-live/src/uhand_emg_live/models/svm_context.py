"""SVM on features of the last 0.8 s (models/*.joblib holding a scaler + SVC pipeline, trained by
a teammate). The recipe is that of the emg_model.py that came with the model; fed the same
samples, this gives the same labels:

  samples minus 127 -> causal 5 Hz high-pass (4th-order Butterworth), restarted after a dropout
  -> 200 ms windows ending now and 100, 200, ... 600 ms ago
  -> per window 92 features: RMS and WL (log of the ratio to the wearer's resting level),
     WAMP, ZC and SSC at thresholds 1 and 2 (log1p), correlation of the 28 channel pairs
  -> 7 windows x 92 = 644 numbers -> StandardScaler -> SVC (RBF), classes 0..7 in the studio's
     "puppet" numbering
A decision every 100 ms, on the time grid of the first sample.

The resting level is measured on the wearer: without that calibration (about 8 s of a relaxed
arm, every time the band is put on) the model gives no decision at all.

The SVC has no probabilities, only a label. The probabilities reported here are the share of
the last SMOOTH labels (ours, as for the forest); Decision.raw is the newest label alone.

Its view shows how that label comes about. An SVC of this kind holds one decider per pair of
gestures (28 for 8 gestures); each compares the signal with the support vectors of its two
gestures, and the gesture that wins most of its duels is the label. Decision.view["duels"] is
the decision value of every duel: 0 is the boundary between the two gestures and -1 and +1 are
the margin, where that duel's support vectors lie. The label itself is still scikit-learn's
`predict`.

A .joblib file is a pickle, which can run code when loaded. It is read through an unpickler
that only accepts the scikit-learn pipeline, scaler, SVC and numpy array classes (safe_joblib).
"""
from __future__ import annotations

import glob
import os

import numpy as np
from scipy.signal import butter, sosfilt

from ..gestures import PUPPET
from . import safe_joblib
from .base import Decision, GestureModel, ModelSpec

FS = 500.0
N_WIN = 100                 # 200 ms
STRIDE_S = 0.1              # a decision, and a step back to the next older window, every 100 ms
LAGS = 6                    # older windows used besides the newest
GAP_S = 0.003               # a larger step between samples is a gap
CENTER = 127.0
THRESHOLDS = ((1.0, ""), (2.0, "_2"))       # ZC, SSC and WAMP thresholds, in ADC counts
KEEP_S = N_WIN / FS + LAGS * STRIDE_S + 0.1
SMOOTH = 3                  # labels the reported probabilities are the share of
REST_S = 8.0                # calibration: this long with a relaxed arm
REST_SKIP_S = 0.5           # ... of which the start is left out (the wearer is still settling)
MIN_REST_WINDOWS = 30
_PAIRS = np.triu_indices(8, 1)
_SOS = butter(4, 5, btype="highpass", fs=FS, output="sos")

_ALLOWED = {
    ("sklearn.pipeline", "Pipeline"),
    ("sklearn.preprocessing._data", "StandardScaler"),
    ("sklearn.svm._classes", "SVC"),
}


def window_at(t: np.ndarray, end: float) -> tuple[int, int] | None:
    """Rows of the N_WIN samples that end at time `end`; None when there are too few or a gap."""
    i1 = int(np.searchsorted(t, end, side="right"))
    i0 = i1 - N_WIN
    if i0 < 0 or np.any(np.diff(t[i0:i1]) > GAP_S) or end - t[i1 - 1] > GAP_S:
        return None
    return i0, i1


def raw_features(w: np.ndarray) -> dict[str, np.ndarray]:
    """Filtered window (100, 8) -> RMS, WL, the counts at both thresholds, channel correlations."""
    d = np.diff(w, axis=0)
    d1, d2 = d[:-1], d[1:]
    f = {"RMS": np.sqrt((w ** 2).mean(0)), "WL": np.abs(d).sum(0)}
    for thr, tag in THRESHOLDS:
        f["WAMP" + tag] = (np.abs(d) >= thr).sum(0).astype(float)
        f["ZC" + tag] = ((w[:-1] * w[1:] < 0) & (np.abs(d) >= thr)).sum(0).astype(float)
        f["SSC" + tag] = ((d1 * d2 < 0) & ((np.abs(d1) >= thr) | (np.abs(d2) >= thr))).sum(0).astype(float)
    z = w - w.mean(0)
    s = np.sqrt((z ** 2).sum(0)) + 1e-9
    f["CORR"] = ((z.T @ z) / np.outer(s, s))[_PAIRS]
    return f


def window_vector(f: dict[str, np.ndarray], rest: dict[str, np.ndarray]) -> np.ndarray:
    """One window -> 92 numbers, the amplitudes relative to the wearer's resting level."""
    amp = [np.log(f[k] / (rest[k] + 1e-3) + 1e-3) for k in ("RMS", "WL")]
    cnt = [np.log1p(f[k]) for k in ("WAMP", "ZC", "SSC", "WAMP_2", "ZC_2", "SSC_2")]
    return np.concatenate(amp + cnt + [f["CORR"]])


def sample_vector(x: np.ndarray, t: np.ndarray, end: float, rest: dict[str, np.ndarray]) -> np.ndarray | None:
    """The window ending at `end` and the LAGS before it -> 644 numbers; None when one is missing."""
    ws = [window_at(t, end - STRIDE_S * k) for k in range(LAGS + 1)]
    if any(w is None for w in ws):
        return None
    return np.concatenate([window_vector(raw_features(x[a:b]), rest) for a, b in ws])


def resting_level(x: np.ndarray, t: np.ndarray, t_start: float, t_end: float) -> tuple[dict[str, np.ndarray], int]:
    """Mean RMS and WL of the windows inside [t_start, t_end] -> (level, windows used)."""
    feats, end = [], t_start + N_WIN / FS
    while end <= t_end + 1e-9:
        w = window_at(t, end)
        if w:
            feats.append(raw_features(x[w[0]:w[1]]))
        end += STRIDE_S
    if not feats:
        return {}, 0
    return {k: np.mean([f[k] for f in feats], axis=0) for k in ("RMS", "WL")}, len(feats)


class ContextSVM(GestureModel):
    view = "bars"               # "duels" once the SVC is found to be one the view can redo
    delay_s = N_WIN / FS + LAGS * STRIDE_S
    needs_calibration = True
    calibration_rest_s = REST_S
    calibration_hint = f"휴식 {REST_S:.0f}초"
    uncalibrated_note = "보정 전에는 판정하지 않습니다. 팔에 힘을 빼고 보정을 시작하세요"

    def __init__(self, path: str) -> None:
        bundle = safe_joblib.load(path, _ALLOWED)
        model = bundle.get("model") if isinstance(bundle, dict) else bundle
        steps = getattr(model, "steps", None)
        svc = steps[-1][1] if steps else None
        classes = [int(c) for c in getattr(svc, "classes_", [])]
        n = getattr(svc, "n_features_in_", None)
        if n != 92 * (LAGS + 1) or not classes or any(not 0 <= c < len(PUPPET) for c in classes):
            raise ValueError(f"이 형식의 모델이 아닙니다 (특징 {n}개, 클래스 {classes})")
        self.model = model
        self.gestures = [PUPPET[c] for c in classes]
        self._duels = self._duel_table(model, svc)
        self.view = "duels" if self._duels else "bars"
        self._index = {c: i for i, c in enumerate(classes)}
        self.title = os.path.splitext(os.path.basename(path))[0]
        meta = bundle if isinstance(bundle, dict) else {}
        windows = meta.get("n_train_windows")
        self.info = ("SVM · 지난 0.8초의 특징 644개"
                     + (f" · 학습 창 {windows:,}개" if isinstance(windows, int) else "")
                     + f" · 착용 보정 필요(휴식 {REST_S:.0f}초)")
        self.rest: dict[str, np.ndarray] | None = None       # the wearer's resting level; kept across restarts
        self._collect: list[tuple[np.ndarray, np.ndarray]] | None = None
        self.reset()

    @staticmethod
    def _duel_table(model, svc) -> dict | None:
        """What the view needs to redo the SVC's pairwise decisions; None for a kernel it does
        not know (the model then works without a view of its own)."""
        gamma = getattr(svc, "_gamma", None)
        if getattr(svc, "kernel", None) != "rbf" or gamma is None or not isinstance(svc.support_vectors_, np.ndarray):
            return None
        sv = np.ascontiguousarray(svc.support_vectors_, dtype=np.float32)     # single precision: a picture, not the label
        start = np.r_[0, np.cumsum(svc.n_support_)]
        n = len(svc.n_support_)
        pairs = [(i, j) for i in range(n) for j in range(i + 1, n)]
        weight = np.zeros((len(pairs), len(sv)), np.float32)     # per duel: the weight of every support vector in it
        for p, (i, j) in enumerate(pairs):
            weight[p, start[i]:start[i + 1]] = svc.dual_coef_[j - 1, start[i]:start[i + 1]]
            weight[p, start[j]:start[j + 1]] = svc.dual_coef_[i, start[j]:start[j + 1]]
        support = [(int(np.count_nonzero(weight[p, start[i]:start[i + 1]])),
                    int(np.count_nonzero(weight[p, start[j]:start[j + 1]]))) for p, (i, j) in enumerate(pairs)]
        return {"pre": model[:-1], "sv": sv, "sq": (sv ** 2).sum(axis=1), "gamma": float(gamma), "weight": weight,
                "bias": np.asarray(svc.intercept_, np.float32), "pairs": pairs, "support": support, "total": len(sv)}

    def duels(self, v: np.ndarray) -> dict:
        """644 features -> the decision value of every duel (> 0: the first gesture of the pair wins)."""
        d = self._duels
        x = d["pre"].transform(v[None])[0].astype(np.float32)
        k = np.exp(-d["gamma"] * (d["sq"] + x @ x - 2 * (d["sv"] @ x)))     # likeness to every support vector
        return {"duels": (d["weight"] @ k + d["bias"]).astype(float)}

    def view_data(self) -> dict:
        """The duels (pairs of gesture indices), how many support vectors each side of a duel
        has, and how many there are in all."""
        d = self._duels
        return {"pairs": d["pairs"], "support": d["support"], "total": d["total"]} if d else {}

    def reset(self) -> None:
        self._zi = np.zeros((_SOS.shape[0], 2, 8))
        self._t = np.zeros(0)
        self._x = np.zeros((0, 8))
        self._last_t: float | None = None
        self._next_end: float | None = None
        self._hist: list[np.ndarray] = []

    def feed(self, t: np.ndarray, x: np.ndarray) -> list[Decision]:
        t = np.asarray(t, np.float64)
        if not len(t):
            return []
        raw = np.asarray(x, np.float64) - CENTER
        # filter, restarting at dropouts (also against the previous call's last sample)
        prev = self._last_t if self._last_t is not None else t[0]
        cuts = np.flatnonzero(np.diff(np.r_[prev, t]) > GAP_S)
        y = np.empty_like(raw)
        bounds = np.r_[0, cuts, len(t)]
        for a, b in zip(bounds[:-1], bounds[1:]):
            if a in cuts:
                self._zi[:] = 0
            if b > a:
                y[a:b], self._zi = sosfilt(_SOS, raw[a:b], axis=0, zi=self._zi)
        self._last_t = float(t[-1])
        if self._collect is not None:
            self._collect.append((t.copy(), y.copy()))
        if self._next_end is None:
            self._next_end = float(t[0]) + N_WIN / FS + LAGS * STRIDE_S
        keep = np.searchsorted(self._t, self._next_end - KEEP_S, side="left")    # what the ends still to come look back on
        self._t = np.r_[self._t[keep:], t]
        self._x = np.vstack([self._x[keep:], y])
        out: list[Decision] = []
        dropout = t[0] - prev > STRIDE_S
        while self._next_end <= self._last_t + 1e-9:
            if dropout and self._next_end < t[0]:                # no decision for the time of a dropout, nor a late
                self._next_end += STRIDE_S                       # one for the moment just before it (emg_model.py
                self._hist = []                                  # has dropped those samples by then); stepping on
                continue                                         # by adding keeps the grid that of emg_model.py
            v = sample_vector(self._x, self._t, self._next_end, self.rest) if self.rest is not None else None
            if v is None:
                self._hist = []                                  # not a run of decisions any more
            else:
                one = np.zeros(len(self.gestures))
                one[self._index[int(self.model.predict(v[None])[0])]] = 1.0
                self._hist = (self._hist + [one])[-SMOOTH:]
                out.append(Decision(self._next_end, np.mean(self._hist, axis=0), one,
                                    self.duels(v) if self._duels else {}))
            self._next_end += STRIDE_S
        return out

    # ------------------------------------------------------------ calibration: the wearer's resting level
    def calibration_start(self) -> None:
        self._collect = []

    def calibration_cancel(self) -> None:
        self._collect = None

    def calibration_finish(self) -> tuple[bool, str]:
        got, self._collect = self._collect or [], None
        if not got:
            return False, "보정 실패: 신호가 없습니다 (연결과 밴드를 확인하세요)"
        t = np.concatenate([g[0] for g in got])
        x = np.vstack([g[1] for g in got])
        rest, windows = resting_level(x, t, t[0] + REST_SKIP_S, t[-1])
        if windows < MIN_REST_WINDOWS:
            return False, "보정 실패: 신호가 부족합니다 (연결과 밴드를 확인하세요)"
        self.rest = rest
        self._hist = []
        return True, f"휴식 창 {windows}개로 보정됨"

    @property
    def calibrated(self) -> bool:
        return self.rest is not None


def find(models_dir: str) -> list[ModelSpec]:
    return [ModelSpec(os.path.splitext(os.path.basename(p))[0], "SVM", p, lambda p=p: ContextSVM(p))
            for p in sorted(glob.glob(os.path.join(models_dir, "*.joblib")))
            if safe_joblib.top_class(p) == "Pipeline"]
