"""What a gesture model must provide. To add a model family, add one module to this package
that defines `find(models_dir) -> list[ModelSpec]`; it is picked up automatically (see __init__).

A model receives the armband's samples exactly as received (0..255, physical channel order,
500 Hz) with their times, and returns a Decision whenever it has a new one. It reports gestures
by key (app.gestures), in the order of `gestures`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np


@dataclass
class Decision:
    t: float                              # time of the newest sample the decision used
    proba: np.ndarray                     # probability per gesture, in `GestureModel.gestures` order
    raw: np.ndarray | None = None         # the newest window alone, before the model's own averaging
    view: dict = field(default_factory=dict)   # extra data for the model's own view (map position, votes, ...)


class GestureModel:
    title: str = ""
    info: str = ""                        # one line shown under the model name
    gestures: list[str] = []
    view: str = "bars"                    # which view the screen shows: "map", "votes" or "bars"
    delay_s: float = 0.2                  # signal the model looks back on (shown as a hint)
    needs_calibration: bool = False

    def reset(self) -> None:
        """Forget the signal seen so far (the stream restarted or changed mode)."""

    def feed(self, t: np.ndarray, x: np.ndarray) -> list[Decision]:
        """t (n,) sample times, x (n, 8) samples as received. -> new decisions, oldest first."""
        raise NotImplementedError

    def view_data(self) -> dict:
        """Static data for the view (e.g. the map's reference points)."""
        return {}

    # calibration of a band placement, for models that need one
    def calibration_start(self) -> None:
        pass

    def calibration_cancel(self) -> None:
        pass

    def calibration_finish(self) -> tuple[bool, str]:
        """-> (succeeded, message for the screen)."""
        return True, ""

    @property
    def calibrated(self) -> bool:
        return True


@dataclass
class ModelSpec:
    title: str                            # shown in the model list
    kind: str                             # model family, e.g. "CNN", "RF"
    path: str
    load: Callable[[], GestureModel]      # may be slow; called when the model is chosen
