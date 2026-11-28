"""Gesture models. Every module in this package that defines `find(models_dir)` is a model
family; `discover` asks each of them which model files it can run."""
from __future__ import annotations

import importlib
import pkgutil

from .base import Decision, GestureModel, ModelSpec

__all__ = ["Decision", "GestureModel", "ModelSpec", "discover"]


def discover(models_dir: str) -> tuple[list[ModelSpec], list[str]]:
    """-> (models found, problems). A family that cannot be imported (a missing library, say)
    is reported and skipped, so the others still work."""
    specs: list[ModelSpec] = []
    problems: list[str] = []
    for mod in pkgutil.iter_modules(__path__):
        if mod.name in ("base", "cnn_net"):
            continue
        try:
            module = importlib.import_module(f"{__name__}.{mod.name}")
            find = getattr(module, "find", None)
            if find is not None:
                specs += find(models_dir)
        except Exception as e:                       # noqa: BLE001 - a broken family must not stop the app
            problems.append(f"{mod.name}: {e}")
    return sorted(specs, key=lambda s: (s.kind, s.title)), problems
