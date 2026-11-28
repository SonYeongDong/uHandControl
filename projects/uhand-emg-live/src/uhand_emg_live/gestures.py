"""Gesture keys shared by every stage. Models report gestures by key, never by number, so
models trained with different numberings can drive the same pose table and screen."""
from __future__ import annotations

NAMES = {
    "rest": "휴식",
    "fist": "주먹", "open": "손 펴기", "index": "검지 펴기",
    "wrist_flex": "손목 굽히기", "wrist_ext": "손목 젖히기",
    "radial_dev": "엄지 쪽 꺾기", "ulnar_dev": "새끼 쪽 꺾기",
    "scissors": "가위", "rock": "주먹", "paper": "보",
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
}

# the studio's "puppet" numbering (0..7), which the recordings and both model families use
PUPPET = ["rest", "fist", "open", "index", "wrist_flex", "wrist_ext", "radial_dev", "ulnar_dev"]

_PALETTE = ["#868e96", "#4dabf7", "#ff922b", "#20c997", "#fcc419", "#f783ac", "#51cf66", "#9775fa",
            "#ff6b6b", "#3bc9db", "#e599f7", "#a9e34b"]
_ORDER = PUPPET + ["scissors", "paper", "one", "two", "three", "four", "five", "rock"]
_COLOR = {k: _PALETTE[i % len(_PALETTE)] for i, k in enumerate(_ORDER)}
_COLOR["rock"] = _COLOR["fist"]
_COLOR["one"] = _COLOR["index"]
_COLOR["five"] = _COLOR["paper"] = _COLOR["open"]


def name(key: str | None) -> str:
    return NAMES.get(key, key) if key else "–"


def colour(key: str | None) -> str:
    return _COLOR.get(key, "#868e96")
