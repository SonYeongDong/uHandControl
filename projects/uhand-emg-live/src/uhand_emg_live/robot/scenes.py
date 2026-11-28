"""Puppet-show scenes: the files a teammate makes with uHandMotionCreator, one per gesture.

The files and their rules are those of EMGRobotHandTheater (its robot_thread/sequence_loader.py),
so a scene made for that program plays the same here:
  - sequences/action_NN.uhjson, NN = that program's action number for the gesture ([theater.ids]);
    a different file can be picked for a gesture on the screen (see Engine.set_scene_file)
  - a scene is a list of cards: a hand motion (six servo pulses + time), a buzzer tone, an LED colour
  - a scene with at least one timed card (motion, or a tone that is not continuous) repeats
  - a missing file plays that program's stand-in: red LED, a tone per action, fingers showing the
    action number in binary
  - a damaged file is not played at all (the hand goes home) and is reported
Only data is read from a file; nothing in it is executed.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from uhand_client_module._validation import buzzer_params, led_params, pulse_params

NOTES = (131, 147, 165, 175, 196, 220, 247, 262, 294, 330, 349, 392, 440, 494, 523, 587)
UNITS = {"pulse": "us", "running_time": "ms", "frequency": "Hz"}
MAX_BYTES = 5 * 1024 * 1024


@dataclass(frozen=True)
class Card:
    kind: str               # "motion" | "buzzer" | "led"
    args: tuple             # motion: six pulses + ms; buzzer: Hz, ms, continuous; led: r, g, b, brightness

    @property
    def timed(self) -> bool:
        return self.kind == "motion" or (self.kind == "buzzer" and not self.args[2])


@dataclass(frozen=True)
class Scene:
    key: str                # gesture key
    action_id: int
    file: str
    cards: tuple[Card, ...]
    repeat_from: int | None     # card to continue from after the last one; None = play once
    missing: bool = False       # the stand-in for a file that is not there


@dataclass
class SceneSet:
    scenes: dict[str, Scene] = field(default_factory=dict)       # playable, by gesture key
    damaged: dict[str, str] = field(default_factory=dict)        # gesture key -> what is wrong with its file
    ids: dict[str, int] = field(default_factory=dict)
    folder: str = ""
    chosen: dict[str, str] = field(default_factory=dict)         # gesture key -> a file picked instead of the default

    def default_name(self, key: str) -> str:
        return f"action_{self.ids[key]:02d}.uhjson"

    def file_name(self, key: str) -> str:
        """The file this gesture plays: the one picked for it, else action_NN.uhjson."""
        return os.path.basename(self.chosen[key]) if key in self.chosen else self.default_name(key)


def _card(row, version: int) -> Card:
    if not isinstance(row, dict):
        raise ValueError("카드 객체 필요")
    name = row["name"]
    if not isinstance(name, str) or not name.strip() or len(name) > 60 or any(ord(c) < 32 for c in name):
        raise ValueError("유효하지 않은 카드 이름")
    kind = row["kind"]
    if kind == "motion":
        pulses, ms = row["pulses"], row["running_time"]
        if not isinstance(pulses, list):
            raise ValueError("펄스 배열 필요")
        pulse_params(pulses, ms)
        return Card(kind, (*pulses, ms))
    if kind == "buzzer":
        args = (row["frequency"], row["running_time"], row["continuous"])
        buzzer_params(*args)
        return Card(kind, args)
    if kind == "led":
        rgb = tuple(row[channel] for channel in ("red", "green", "blue"))
        required = bool if version == 1 else int
        if any(type(channel) is not required for channel in rgb):
            raise ValueError("LED 채널 자료형 확인")
        if version == 1:
            if "brightness" in row:
                raise ValueError("스키마 1 LED에는 밝기가 없습니다")
            args = (*[255 * value for value in rgb], 100)
        else:
            args = (*rgb, row["brightness"])
        led_params(*args)
        return Card(kind, args)
    raise ValueError(f"지원하지 않는 카드 종류 {kind}")


def _unique_keys(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f"중복 JSON 키 {key}")
        obj[key] = value
    return obj


def read_cards(path: str) -> tuple[tuple[Card, ...], int | None]:
    """-> (cards, repeat_from). Raises ValueError for anything that is not a valid scene file."""
    with open(path, "rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("5 MiB 초과")
    try:
        doc = json.loads(data.decode("utf-8-sig"), object_pairs_hook=_unique_keys)
    except UnicodeDecodeError as exc:
        raise ValueError("UTF-8 파일이 아닙니다") from exc
    if not isinstance(doc, dict) or doc.get("format") != "uhand-motion-sequence":
        raise ValueError("uHandMotionCreator 파일 형식이 아닙니다")
    version = doc.get("schema_version")
    if type(version) is not int or version not in (1, 2) or doc.get("units") != UNITS:
        raise ValueError("스키마 버전 또는 단위 확인")
    rows = doc.get("cards")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 5000:
        raise ValueError("동작 카드 1~5000개 필요")
    cards = []
    for number, row in enumerate(rows, 1):
        try:
            cards.append(_card(row, version))
        except (KeyError, ValueError, TypeError) as exc:
            raise ValueError(f"카드 {number}: {exc}") from exc
    return tuple(cards), (0 if any(c.timed for c in cards) else None)


def stand_in(action_id: int) -> tuple[tuple[Card, ...], int]:
    """What plays for a missing file: red LED at half brightness, a tone that names the action,
    and the fingers toggling between the action number in binary and an open hand."""
    if not 0 <= action_id < len(NOTES):
        raise ValueError("누락 표시 범위 0~15를 벗어났습니다")
    if action_id == 0:
        first = (2200, 800, 800, 800, 800, 500)
        second = (*first[:5], 2500)
    else:
        fingers = tuple(800 if action_id & mask else 2000 for mask in (8, 4, 2, 1))
        first = (800, *fingers, 1500)
        second = (800, 2000, 2000, 2000, 2000, 1500)
    return (Card("led", (255, 0, 0, 50)), Card("buzzer", (NOTES[action_id], 300, True)),
            Card("motion", (*first, 300)), Card("motion", (*second, 300))), 2


def load_scenes(folder: str, ids: dict[str, int], chosen: dict[str, str] | None = None) -> SceneSet:
    """`chosen` maps a gesture key to the path of a scene file picked for it on the screen; the
    other gestures play folder/action_NN.uhjson as in the theater program."""
    out = SceneSet(ids=dict(ids), folder=folder, chosen={k: v for k, v in (chosen or {}).items() if k in ids})
    for key, action_id in ids.items():
        name = out.file_name(key)
        path = out.chosen.get(key) or os.path.join(folder, name)
        try:
            try:
                cards, repeat = read_cards(path)
                out.scenes[key] = Scene(key, action_id, name, cards, repeat)
            except FileNotFoundError:
                cards, repeat = stand_in(action_id)
                out.scenes[key] = Scene(key, action_id, name, cards, repeat, missing=True)
        except (OSError, ValueError, RecursionError) as exc:
            out.damaged[key] = str(exc)
    return out
