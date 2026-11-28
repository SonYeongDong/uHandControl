"""Random forest on hand-made features (models/*.joblib, trained by a teammate).

Recipe, from the sample.py that came with the model:
  the last 500 ms of raw samples (about 250 rows x 8 channels), minus 127, no filter, no scaling
  -> 11 features per channel, laid out feature by feature (IEMG ch1..8, MAV ch1..8, ...) = 88
  -> RandomForestClassifier, classes 0..7 in the studio's "puppet" numbering
A decision every 100 ms, averaged over the last SMOOTH decisions (the averaging is ours, not in
sample.py; raw output flips about three times as often as the gesture really changes).

Several features are sums and counts that grow with the number of rows, so the window is always
exactly ROWS gap-free samples; after a dropout the model waits until it has that again.

Its view is the vote of the individual trees: Decision.view["votes"] holds, per tree, the index
of the gesture that tree chose. One tree (the smallest, so it can be drawn whole) is also shown
as it really is: view_data()["tree"] is its structure and Decision.view["path"] the nodes the
current window passed through, root to leaf.

A .joblib file is a pickle, which can run code when loaded. It is therefore read through an
unpickler that only accepts the scikit-learn forest and numpy array classes.
"""
from __future__ import annotations

import glob
import os
import pickle
import warnings

import numpy as np

from ..gestures import PUPPET
from .base import Decision, GestureModel, ModelSpec

FS = 500.0
ROWS = 250                  # 500 ms
STEP = 50                   # a decision every 100 ms
SMOOTH = 3                  # decisions averaged
MAX_STEP_S = 1.5 / FS       # a larger step between samples is a gap
CENTER = 127.0
FEATURES = ("IEMG", "MAV", "MAV1", "MAV2", "RMS", "SSI", "VAR", "WL", "ZC", "SSC", "WAMP")
THRESHOLD = 1.0             # ZC, SSC and WAMP threshold, in ADC counts

_ALLOWED = {
    ("sklearn.ensemble._forest", "RandomForestClassifier"),
    ("sklearn.tree._classes", "DecisionTreeClassifier"),
    ("sklearn.tree._tree", "Tree"),
    ("joblib.numpy_pickle", "NumpyArrayWrapper"),
    ("numpy", "ndarray"), ("numpy", "dtype"),
    ("numpy.core.multiarray", "_reconstruct"), ("numpy._core.multiarray", "_reconstruct"),
    ("numpy.core.multiarray", "scalar"), ("numpy._core.multiarray", "scalar"),
}


def features(x: np.ndarray) -> np.ndarray:
    """x (n, 8) centred samples -> (88,), the same numbers as sample.py's extract_features."""
    n = len(x)
    a = np.abs(x)
    ss = np.sum(x ** 2, axis=0)
    pos = np.arange(1, n + 1, dtype=np.float64) / n
    w1 = np.where((pos >= 0.25) & (pos <= 0.75), 1.0, 0.5)
    w2 = np.where(pos < 0.25, 4 * pos, np.where(pos > 0.75, 4 * (1 - pos), 1.0))
    d = np.abs(np.diff(x, axis=0))
    slope = (x[1:-1] - x[:-2]) * (x[1:-1] - x[2:])
    return np.concatenate([
        a.sum(axis=0),                                           # IEMG
        a.mean(axis=0),                                          # MAV
        (w1[:, None] * a).mean(axis=0),                          # MAV1
        (w2[:, None] * a).mean(axis=0),                          # MAV2
        np.sqrt(ss / n),                                         # RMS
        ss,                                                      # SSI
        ss / (n - 1),                                            # VAR
        d.sum(axis=0),                                           # WL
        ((x[:-1] * x[1:] < 0) & (d >= THRESHOLD)).sum(axis=0),   # ZC
        ((slope > 0) & (slope >= THRESHOLD)).sum(axis=0),        # SSC
        (d >= THRESHOLD).sum(axis=0),                            # WAMP
    ]).astype(np.float64)


def load_forest(path: str):
    """Unpickle a forest, refusing any class that is not part of one."""
    from joblib.numpy_pickle import NumpyUnpickler

    class Safe(NumpyUnpickler):
        def find_class(self, module, name):
            if (module, name) not in _ALLOWED:
                raise pickle.UnpicklingError(f"모델 파일에 허용되지 않은 내용이 있습니다: {module}.{name}")
            return super().find_class(module, name)

    with open(path, "rb") as fh, warnings.catch_warnings():
        warnings.simplefilter("ignore")              # saved with another scikit-learn version
        try:
            return Safe(path, fh, ensure_native_byte_order=False, mmap_mode=None).load()
        except TypeError:                            # older joblib: no ensure_native_byte_order
            fh.seek(0)
            return Safe(path, fh, mmap_mode=None).load()


class FeatureForest(GestureModel):
    view = "votes"
    delay_s = ROWS / FS
    needs_calibration = False

    def __init__(self, path: str) -> None:
        f = load_forest(path)
        classes = [int(c) for c in f.classes_]
        if f.n_features_in_ != len(FEATURES) * 8 or any(not 0 <= c < len(PUPPET) for c in classes):
            raise ValueError(f"이 형식의 모델이 아닙니다 (특징 {f.n_features_in_}개, 클래스 {classes})")
        f.n_jobs = 1
        self.forest = f
        self.gestures = [PUPPET[c] for c in classes]
        self.title = os.path.splitext(os.path.basename(path))[0]
        self.n_trees = len(f.estimators_)
        # per tree: the class distribution of every leaf, so one `apply` gives votes and probabilities
        self._leaf = []
        self._trees = [e.tree_ for e in f.estimators_]       # asked one by one: no thread-pool overhead per decision
        self.shown_tree = int(np.argmin([t.node_count for t in self._trees]))    # the one the view draws
        t = self._trees[self.shown_tree]
        self._shown = (t.children_left.copy(), t.children_right.copy(), t.feature.copy(), t.threshold.copy())
        for e in f.estimators_:
            v = e.tree_.value[:, 0, :]
            self._leaf.append(v / np.maximum(v.sum(axis=1, keepdims=True), 1e-12))
        self.info = (f"랜덤포레스트 · 나무 {self.n_trees}그루 · 500 ms 창 · 학습 샘플 {getattr(f, '_n_samples', '?')}개"
                     f" · 착용 보정 없음")
        self.reset()

    def reset(self) -> None:
        self._buf = np.zeros((0, 8))
        self._last_t: float | None = None
        self._since = 0
        self._hist: list[np.ndarray] = []

    def feed(self, t: np.ndarray, x: np.ndarray) -> list[Decision]:
        out: list[Decision] = []
        t = np.asarray(t, np.float64)
        if not len(t):
            return out
        x = np.asarray(x, np.float64) - CENTER
        # split at dropouts (also against the previous call's last sample)
        prev = np.r_[self._last_t if self._last_t is not None else t[0], t[:-1]]
        cut = np.flatnonzero(t - prev > MAX_STEP_S)
        for a, b in zip(np.r_[0, cut], np.r_[cut, len(t)]):
            if a in cut:
                self.reset()                         # start a fresh window after the gap
            out += self._run(t[a:b], x[a:b])
        self._last_t = float(t[-1])
        return out

    def _run(self, t: np.ndarray, x: np.ndarray) -> list[Decision]:
        if not len(t):
            return []
        buf = np.vstack([self._buf, x])
        base = len(buf) - len(x)
        ends = [base + j + 1 for j in range(len(x)) if (self._since + j + 1) % STEP == 0]
        self._since = (self._since + len(x)) % STEP
        self._buf = buf[-ROWS:]
        out = []
        for e in ends:
            if e < ROWS:
                continue
            feat = features(buf[e - ROWS:e])
            p, votes = self.classify(feat)
            self._hist = (self._hist + [p])[-SMOOTH:]
            out.append(Decision(float(t[e - base - 1]), np.mean(self._hist, axis=0), p,
                                {"votes": votes, "path": self.path(feat)}))
        return out

    def classify(self, feat: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """(88,) features -> (probabilities, the gesture index each tree voted for). The
        probabilities equal predict_proba: the mean of the trees' leaf distributions."""
        x = np.ascontiguousarray(feat.reshape(1, -1), dtype=np.float32)      # what scikit-learn feeds its trees
        dist = np.stack([leaf[tree.apply(x)[0]] for leaf, tree in zip(self._leaf, self._trees)])
        return dist.mean(axis=0), dist.argmax(axis=1)

    def path(self, feat: np.ndarray) -> np.ndarray:
        """Nodes the shown tree visits for these features, root first, leaf last."""
        left, right, feature, threshold = self._shown
        x = feat.astype(np.float32)                              # scikit-learn compares float32 inputs
        node, out = 0, [0]
        while left[node] != -1:
            node = int(left[node] if x[feature[node]] <= threshold[node] else right[node])
            out.append(node)
        return np.array(out)

    def view_data(self) -> dict:
        left, right, _, _ = self._shown
        return {"tree": {"index": self.shown_tree, "of": self.n_trees, "left": left, "right": right,
                         "answer": self._leaf[self.shown_tree].argmax(axis=1)}}     # per node: gesture index


def find(models_dir: str) -> list[ModelSpec]:
    return [ModelSpec(os.path.splitext(os.path.basename(p))[0], "RF", p, lambda p=p: FeatureForest(p))
            for p in sorted(glob.glob(os.path.join(models_dir, "*.joblib")))]
