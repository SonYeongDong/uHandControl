"""What the robot is told to do next. The sender thread asks its driver for one command at a
time and carries it out; the two drivers are the two ways this program moves the hand.

  FollowDriver    따라 하기: the pose the Kalman filter predicts, as one short move after another
  TheaterDriver   인형극: the cards of the scene that belongs to the confirmed gesture

A driver's `reset` is called when it takes over and after every (re)connection, when the robot
is at home with whatever lights and tones the last scene left on.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Callable

import numpy as np

from ..motion.poses import HI, LO
from .scenes import Card, Scene, SceneSet

HOME_MS = 500


@dataclass(frozen=True)
class Command:
    kind: str               # "motion" | "led" | "buzzer" | "wait"
    args: tuple             # motion: six pulses + ms; led: r, g, b, brightness; buzzer: Hz, ms, continuous; wait: ms

    @property
    def takes_ms(self) -> int:
        """How long the robot is busy with it."""
        if self.kind == "motion":
            return int(self.args[6])
        if self.kind == "buzzer":
            return 0 if self.args[2] else int(self.args[1])
        return int(self.args[0]) if self.kind == "wait" else 0


def outputs_off() -> list[Command]:
    return [Command("buzzer", (0, 100, True)), Command("led", (0, 0, 0, 100))]


def go_home() -> list[Command]:
    return outputs_off() + [Command("motion", (1500, 1500, 1500, 1500, 1500, 1500, HOME_MS))]


class FollowDriver:
    name = "follow"

    def __init__(self, pose_ahead: Callable[[float], np.ndarray], step_ms: int = 250, predict_ms: int = 250,
                 deadband: int = 10) -> None:
        self.pose_ahead = pose_ahead        # seconds ahead -> pose (6,)
        self.step_ms = int(np.clip(step_ms, 100, 20000))
        self.predict_ms = int(predict_ms)
        self.deadband = deadband
        self._last: np.ndarray | None = None
        self._queue: deque[Command] = deque()

    def reset(self) -> None:
        self._last = None
        self._queue = deque(outputs_off())          # no light or tone left over from a scene

    def step(self) -> Command | None:
        if self._queue:
            return self._queue.popleft()
        p = np.rint(np.clip(self.pose_ahead(self.predict_ms / 1000.0), LO, HI)).astype(int)
        if self._last is not None and np.max(np.abs(p - self._last)) < self.deadband:
            return None                              # not moving: nothing to send
        self._last = p
        return Command("motion", (*(int(v) for v in p), self.step_ms))


class TheaterDriver:
    """Plays the scene of the requested gesture, card after card, and repeats it. A new request
    takes effect between cards. No request (bad signal, no decision yet) or a gesture without a
    playable scene sends the hand home with light and sound off."""

    name = "theater"

    def __init__(self, request: Callable[[], str | None], scenes: SceneSet, led: bool = True, buzzer: bool = True) -> None:
        self.request = request              # -> gesture key, or None to stand by at home
        self.scenes = scenes
        self.led, self.buzzer = led, buzzer
        self.active: str | None = None
        self.scene: Scene | None = None
        self.index: int | None = None
        self.shown = 0                      # number of the card being played (1-based), for the screen
        self._queue: deque[Command] = deque()

    def reset(self) -> None:
        self.active, self.scene, self.index, self.shown = None, None, None, 0
        self._queue = deque(go_home())

    def step(self) -> Command | None:
        while True:
            if self._queue:
                return self._queue.popleft()
            target = self.request()
            if target not in self.scenes.scenes:
                target = None
            if target != self.active:
                leaving = self.scene
                self.active = target
                self.scene = self.scenes.scenes.get(target) if target else None
                self.index, self.shown = (0 if self.scene else None), 0
                if target is None:
                    self._queue += go_home()
                elif leaving is not None and leaving.missing:
                    self._queue += outputs_off()     # the stand-in's red light and tone must not carry over
                continue
            if self.index is None:
                return None                          # at home, or a scene without timed cards that has been shown
            card = self.scene.cards[self.index]
            self.shown = self.index + 1
            self.index += 1
            if self.index == len(self.scene.cards):
                self.index = self.scene.repeat_from
            cmd = self._command(card)
            if cmd is not None:
                return cmd

    def _command(self, card: Card) -> Command | None:
        if card.kind == "led" and not self.led:
            return None
        if card.kind == "buzzer" and not self.buzzer:
            return None if card.args[2] else Command("wait", (card.args[1],))    # keep the scene's timing
        return Command(card.kind, card.args)

    def status(self) -> tuple[str | None, int, int, bool]:
        """(gesture whose scene is playing, card number, cards in the scene, stand-in for a missing file)."""
        scene = self.scene
        return (self.active, self.shown, len(scene.cards), scene.missing) if scene else (None, 0, 0, False)
