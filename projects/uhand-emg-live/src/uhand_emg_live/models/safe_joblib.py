"""Reading a .joblib model file without trusting it.

A .joblib file is a pickle, which can run code when loaded. `load` therefore reads it through
an unpickler that accepts only the classes a model family names, and `top_class` tells the
families' files apart from the first bytes alone, without unpickling anything.
"""
from __future__ import annotations

import pickle
import re
import warnings

# what joblib itself needs to restore the numpy arrays inside any model
ARRAYS = {
    ("joblib.numpy_pickle", "NumpyArrayWrapper"),
    ("numpy", "ndarray"), ("numpy", "dtype"),
    ("numpy.core.multiarray", "_reconstruct"), ("numpy._core.multiarray", "_reconstruct"),
    ("numpy.core.multiarray", "scalar"), ("numpy._core.multiarray", "scalar"),
}
_GLOBAL = re.compile(rb"\x8c.(sklearn[\w.]*)\x94\x8c.(\w+)\x94\x93|c(sklearn[\w.]*)\n(\w+)\n")


def load(path: str, allowed: set[tuple[str, str]]):
    """Unpickle `path`, refusing any class that is not in `allowed` (ARRAYS is always accepted)."""
    from joblib.numpy_pickle import NumpyUnpickler

    accepted = allowed | ARRAYS

    class Safe(NumpyUnpickler):
        def find_class(self, module, name):
            if (module, name) not in accepted:
                raise pickle.UnpicklingError(f"모델 파일에 허용되지 않은 내용이 있습니다: {module}.{name}")
            return super().find_class(module, name)

    with open(path, "rb") as fh, warnings.catch_warnings():
        warnings.simplefilter("ignore")              # saved with another scikit-learn version
        try:
            return Safe(path, fh, ensure_native_byte_order=False, mmap_mode=None).load()
        except TypeError:                            # older joblib: no ensure_native_byte_order
            fh.seek(0)
            return Safe(path, fh, mmap_mode=None).load()


def top_class(path: str) -> str | None:
    """Name of the first scikit-learn class the file mentions ("RandomForestClassifier",
    "Pipeline", ...), or None when the first bytes name none (a compressed file, say)."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(4096)
    except OSError:
        return None
    m = _GLOBAL.search(head)
    return (m.group(2) or m.group(4)).decode("ascii") if m else None
