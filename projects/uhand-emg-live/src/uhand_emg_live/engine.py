"""The pipeline, without any screen: armband -> health -> model -> confirmed gesture ->
robot. One worker thread pulls new samples from the Link and pushes them through; the screen
(or a test) reads `state()`.

The robot is driven in one of two modes (app.robot.drivers):
  follow   the hand copies the wearer: the sender asks `pose_ahead` for the Kalman-predicted pose
  theater  puppet show: the sender plays the scene file of the gesture `scene_request` returns

    sensor.Link ──samples──> models.GestureModel ──Decision──> decide.Stabilizer   (confirmed gesture)
         │                                             └─────> motion.PoseTable.blend -> motion.PoseKalman
         └─ sensor.HealthMonitor ── error ──> park the robot           robot.RobotSender <── pose_ahead()
"""
from __future__ import annotations

import filecmp
import json
import os
import re
import shutil
import threading
import time
from collections import deque
from dataclasses import dataclass, field, replace

import numpy as np

from . import gestures
from .decide.stabilizer import Stabilizer
from .models import Decision, GestureModel
from .motion.kalman import PoseKalman
from .motion.poses import HI, LO, PoseTable
from . import config as config_mod
from .robot.drivers import FollowDriver, TheaterDriver
from .robot.scenes import SceneSet, load_scenes, read_cards
from .robot.sender import RobotSender, SenderStatus
from .robot.sim import HandSim
from .sensor.health import Health, HealthMonitor
from .sensor.link import Link

TICK_S = 0.02
DEFAULT_NAME = re.compile(r"action_\d\d\.uhjson", re.IGNORECASE)     # a gesture's default scene file
SET_FILE = re.compile(r"(?:action_)?(\d{1,2})(?:[_\-. ].*)?\.uhjson", re.IGNORECASE)    # in a set folder: its action number
DEFAULT_SET = "기본 동작"    # the set that is the scene folder's own action_NN.uhjson files
HEALTH_S = 0.2
STALE_S = 1.0               # no decision for this long: the model output is not current
ERROR_HOLD_S = 3.0          # after a fault in the pipeline the robot stays parked this long
CALIB_REST_S, CALIB_HOLD_S, CALIB_GAP_S = 4.0, 3.0, 2.0


@dataclass(frozen=True)
class RobotView:
    """The simulated robot right now: servo positions, LED colour, buzzer tone (0 = silent)."""
    position: np.ndarray
    led: tuple[int, int, int]
    tone: int


@dataclass(frozen=True)
class SceneInfo:
    """One gesture's puppet-show scene, as the screen lists it."""
    key: str
    number: int                 # the theater program's action number
    file: str                   # name of the file it plays (picked, else action_NN.uhjson)
    state: str                  # "ok" | "missing" (the stand-in plays) | "damaged"
    cards: int = 0
    problem: str = ""           # what is wrong with a damaged file
    picked: str | None = None   # path of a file picked instead of the default


@dataclass(frozen=True)
class CalibStep:
    text: str
    gesture: str
    remaining: float
    progress: float             # 0..1 of the whole calibration


@dataclass(frozen=True)
class EngineState:
    health: Health = field(default_factory=Health)
    model_title: str = ""
    gestures: tuple[str, ...] = ()
    proba: np.ndarray | None = None         # latest decision
    top: str | None = None                  # its likeliest gesture
    confirmed: str | None = None            # what the stabilizer shows
    confidence: float = 0.0
    stale: bool = True                      # no fresh decision
    parked: bool = True                     # the robot is held at home (bad signal or no decision)
    park_reason: str = ""
    target: np.ndarray | None = None        # probability-weighted pose (the Kalman measurement)
    filtered: np.ndarray | None = None      # Kalman position
    predicted: np.ndarray | None = None     # pose the sender would get now (follow mode only)
    mode: str = "follow"                    # "follow" | "theater"
    scene: str | None = None                # theater: gesture whose scene is playing
    scene_card: tuple[int, int] = (0, 0)    # theater: card number, cards in the scene
    scene_missing: bool = False             # theater: the stand-in for a missing file is playing
    rate: float = 0.0                       # decisions per second
    cost_ms: float = 0.0                    # model time per decision
    calib: CalibStep | None = None
    calib_note: str = ""
    calibrated: bool = True
    error: str = ""                         # a fault inside the pipeline itself (shown, robot parked)
    seq: int = 0                            # number of decisions so far (see `decisions_since`)


class Engine:
    def __init__(self, cfg: dict, link: Link | None = None) -> None:
        self.cfg = cfg
        self.link = link or Link()
        self.poses = PoseTable(cfg["poses"])
        self.health_monitor = HealthMonitor(**cfg["health"])
        m = cfg["motion"]
        self.kalman = PoseKalman(LO, HI, m["accel"], m["noise"])
        self.kalman.reset(self.poses.home)
        self.sharpen = float(m["sharpen"])
        self.stab = Stabilizer(cfg["decide"]["min_prob"], cfg["decide"]["hold"])
        self.sim = HandSim()
        r = cfg["robot"]
        self.follow = FollowDriver(self.pose_ahead, r["step_ms"], r["predict_ms"], r["deadband"])
        self.mode = "follow"
        self.scenes = SceneSet()
        self.scene_files = self._read_scene_choices()   # gesture key -> scene file picked on the screen
        self.theater: TheaterDriver | None = None
        self.sender = RobotSender(self.follow, self.sim)

        self._lock = threading.RLock()
        self._model: GestureModel | None = None
        self._gen, self._pos = -1, 0
        self._health = Health()
        self._last: Decision | None = None
        self._bounds: tuple[np.ndarray, np.ndarray] | None = None
        self._target: np.ndarray | None = None
        self._recent: deque[tuple[int, Decision, str | None]] = deque(maxlen=200)
        self._seq = 0
        self._n_rate, self._t_rate, self._rate, self._cost = 0, time.monotonic(), 0.0, 0.0
        self._calib: list[tuple[str, str, float]] | None = None       # (text, gesture, end time)
        self._calib_t0 = 0.0
        self._calib_note = ""
        self._error, self._error_t = "", 0.0
        self._hold = False                   # the stop button: the robot stays parked until released
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="engine", daemon=True)

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        self._thread.start()
        self.sender.start()

    def close(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=3)
        self.sender.close()
        self.link.close()

    # ------------------------------------------------------------ control
    # Everything the screen does goes through the methods of this class; it never reaches into
    # the engine's parts (link, sender, sim, scenes, poses).

    def open_input(self, kind: str, value: str | None = None) -> None:
        """Start receiving: "serial" (value = port), "demo" (value = mode, default "hex") or
        "replay" (value = session folder)."""
        if kind == "serial":
            self.link.open_serial(value)
        elif kind == "demo":
            self.link.open_demo(value or "hex")
        elif kind == "replay":
            self.link.open_replay(value)
        else:
            raise ValueError(f"모르는 입력 종류입니다: {kind}")

    def close_input(self) -> None:
        self.link.close()

    @property
    def input_open(self) -> bool:
        """An input is connected or being connected."""
        return self.link.state.value != "disconnected"

    def replay_prompt(self) -> tuple[str, str, float] | None:
        """While a recording plays: what its screen asked for at this moment (kind, gesture name,
        seconds since). None for any other input or after the recording ended."""
        rp = self.link.replay
        return rp.prompt() if rp is not None and not rp.finished else None

    def set_hold(self, on: bool) -> None:
        """The stop button: park the robot (home pose, light and sound off) until released."""
        with self._lock:
            self._hold = bool(on)

    @property
    def held(self) -> bool:
        return self._hold

    @property
    def robot_addresses(self) -> dict[str, str]:
        """'virtual' and 'real' -> 'IP:port', from the settings."""
        r = self.cfg["robot"]
        return {"virtual": r["virtual"], "real": r["real"]}

    def set_robot(self, which: str | None) -> None:
        """Where commands go: "virtual", "real", or None for the on-screen simulation only."""
        self.sender.set_endpoint(None if which is None else config_mod.endpoint(self.robot_addresses[which]))

    def robot_status(self) -> SenderStatus:
        return self.sender.status()

    def robot_view(self) -> RobotView:
        return RobotView(self.sim.position(), self.sim.led, self.sim.tone())

    def unposed(self, model: GestureModel) -> list[str]:
        """Gestures of `model` that have no robot pose (the home pose stands in for them)."""
        return self.poses.missing(model.gestures)

    def set_model(self, model: GestureModel | None) -> None:
        with self._lock:
            self._model = model
            self._gen = -1                       # start reading from the newest sample
            self._last = None
            self._recent.clear()
            self._calib, self._calib_note = None, ""
            self.stab.reset()
            self.kalman.reset(self.kalman.position)

    @property
    def model(self) -> GestureModel | None:
        return self._model

    @property
    def predict_ms(self) -> int:
        return self.follow.predict_ms

    @predict_ms.setter
    def predict_ms(self, ms: int) -> None:
        self.follow.predict_ms = int(ms)

    def set_mode(self, mode: str) -> None:
        """"follow" or "theater". Entering the theater reads the scene files again, so files
        added or replaced since the last time are picked up."""
        if mode == "theater":
            t = self.cfg["theater"]
            folder = os.path.join(config_mod.ROOT, t["folder"])
            scenes = load_scenes(folder, t["ids"], self.scene_files)
            driver = TheaterDriver(self.scene_request, scenes, t["led"], t["buzzer"])
            with self._lock:
                self.scenes, self.theater, self.mode = scenes, driver, "theater"
            self.sender.set_driver(driver)
        else:
            with self._lock:
                self.mode = "follow"
                self.kalman.reset(self.poses.home)       # the scene left the hand anywhere: start from home
            self.sender.set_driver(self.follow)

    # ------------------------------------------------------------ which scene file a gesture plays
    @property
    def scene_folder(self) -> str:
        return os.path.join(config_mod.ROOT, self.cfg["theater"]["folder"])

    def scene_report(self) -> list[SceneInfo]:
        """Every gesture of the puppet show in action-number order, with the state of its file
        as last read (on entering theater mode or picking a file)."""
        with self._lock:
            scenes = self.scenes
        out = []
        for key, number in sorted(self.cfg["theater"]["ids"].items(), key=lambda kv: kv[1]):
            name = (os.path.basename(self.scene_files[key]) if key in self.scene_files
                    else f"action_{number:02d}.uhjson")
            scene = scenes.scenes.get(key)
            if key in scenes.damaged:
                info = SceneInfo(key, number, name, "damaged", problem=scenes.damaged[key])
            elif scene is None or scene.missing:
                info = SceneInfo(key, number, name, "missing")
            else:
                info = SceneInfo(key, number, name, "ok", cards=len(scene.cards))
            out.append(replace(info, picked=self.scene_files.get(key)))
        return out

    def _choices_path(self) -> str:
        return os.path.join(config_mod.ROOT, self.cfg["theater"]["folder"], "_chosen.json")

    def _read_scene_choices(self) -> dict[str, str]:
        """The picks saved by an earlier run; a pick whose file is gone is dropped."""
        try:
            with open(self._choices_path(), encoding="utf-8") as fh:
                saved = json.load(fh)
        except (OSError, ValueError):
            return {}
        if not isinstance(saved, dict):
            return {}
        out = {}
        for key, rel in saved.items():
            path = os.path.normpath(os.path.join(config_mod.ROOT, str(rel)))
            if key in self.cfg["theater"]["ids"] and os.path.isfile(path):
                out[key] = path
        return out

    def _set_folders(self) -> list[str]:
        """The subfolders of the scene folder, by name. Each can be a set of scene files."""
        try:
            with os.scandir(self.scene_folder) as it:
                return sorted(e.path for e in it if e.is_dir() and not e.name.startswith(("_", ".")))
        except OSError:
            return []

    def scene_library(self) -> list[tuple[str, str]]:
        """(name, path) of every scene file that can be picked: the scene folder itself, then its
        set folders, then the library folder. The scene folder's own action_NN.uhjson files are
        not listed: they are the defaults every list already offers as "기본". A name that is
        already in the list is followed by its folder."""
        t = self.cfg["theater"]
        folders = [(True, self.scene_folder)] + [(False, f) for f in self._set_folders()]
        if t.get("library", ""):
            folders.append((False, os.path.normpath(os.path.join(config_mod.ROOT, t["library"]))))
        found, seen, labels = [], set(), set()
        for own, folder in folders:
            try:
                names = sorted(n for n in os.listdir(folder) if n.lower().endswith(".uhjson")
                               and not (own and DEFAULT_NAME.fullmatch(n)))
            except OSError:
                continue
            for n in names:
                path = os.path.join(folder, n)
                if path not in seen:
                    seen.add(path)
                    label = os.path.splitext(n)[0]
                    if label in labels:
                        label = f"{label} ({os.path.basename(folder)})"
                    labels.add(label)
                    found.append((label, path))
        return found

    def scene_sets(self) -> list[tuple[str, dict[str, str]]]:
        """(name, {gesture key: file}) of every set: scene files for all gestures that are
        switched to at once. The first is the scene folder's own action_NN.uhjson files (no file
        is picked). The others are its subfolders: there a file belongs to the gesture whose
        action number its name starts with (3_제자리걸음.uhjson or action_03.uhjson -> 3). A
        gesture the folder has no file for keeps its action_NN.uhjson."""
        by_number = {number: key for key, number in self.cfg["theater"]["ids"].items()}
        sets: list[tuple[str, dict[str, str]]] = [(DEFAULT_SET, {})]
        for folder in self._set_folders():
            files: dict[str, str] = {}
            try:
                names = sorted(os.listdir(folder))
            except OSError:
                continue
            for n in names:
                m = SET_FILE.fullmatch(n)
                key = by_number.get(int(m.group(1))) if m else None
                if key is not None and key not in files:
                    files[key] = os.path.join(folder, n)
            if files:
                sets.append((os.path.basename(folder), files))
        return sets

    def scene_set(self) -> str | None:
        """The set the gestures play now, or None when the files were picked one by one into
        something that is no set."""
        def same(a: dict[str, str]) -> dict[str, str]:
            return {k: os.path.normcase(os.path.normpath(p)) for k, p in a.items()}
        now = same(self.scene_files)
        return next((name for name, files in self.scene_sets() if same(files) == now), None)

    def set_scene_set(self, name: str) -> None:
        """Switch every gesture to the files of this set. Saved and applied like single picks."""
        files = dict(self.scene_sets()).get(name)
        if files is None:
            raise ValueError(f"없는 공연 세트입니다: {name}")
        self.scene_files = {k: os.path.normpath(p) for k, p in files.items()}
        self._apply_scene_choices()

    def add_scene_file(self, path: str) -> str:
        """Make a scene file from anywhere pickable. The file is checked first (ValueError or
        OSError says what is wrong with it), then copied into the scene folder, unless the list
        already shows it. -> the path to pick with `set_scene_file`."""
        path = os.path.normpath(os.path.abspath(path))
        read_cards(path)
        same = os.path.normcase(path)
        for _, known in self.scene_library():
            if os.path.normcase(known) == same:
                return known
        folder = self.scene_folder
        os.makedirs(folder, exist_ok=True)
        stem, ext = os.path.splitext(os.path.basename(path))
        if DEFAULT_NAME.fullmatch(stem + ext):
            stem = "added_" + stem                   # action_NN is a gesture's default: never take its place
        target, n = os.path.join(folder, stem + ext), 2
        while os.path.exists(target):
            if filecmp.cmp(path, target, shallow=False):
                return target                        # the same file was added before
            target, n = os.path.join(folder, f"{stem} ({n}){ext}"), n + 1
        shutil.copyfile(path, target)
        return target

    def set_scene_file(self, key: str, path: str | None) -> None:
        """Pick the scene file `key` plays (None = back to action_NN.uhjson). The pick is saved
        next to the scene files; in theater mode the scenes are read again at once."""
        if key not in self.cfg["theater"]["ids"]:
            raise ValueError(f"인형극에 없는 동작입니다: {key}")
        if path is None:
            self.scene_files.pop(key, None)
        else:
            self.scene_files[key] = os.path.normpath(path)
        self._apply_scene_choices()

    def _apply_scene_choices(self) -> None:
        saved = {k: os.path.relpath(p, config_mod.ROOT) if os.path.splitdrive(p)[0] == os.path.splitdrive(config_mod.ROOT)[0]
                 else p for k, p in self.scene_files.items()}
        try:
            with open(self._choices_path(), "w", encoding="utf-8") as fh:
                json.dump(saved, fh, ensure_ascii=False, indent=1)
        except OSError:
            pass                                     # the pick still holds for this run
        if self.mode == "theater":
            self.set_mode("theater")

    def start_calibration(self) -> bool:
        """Guide the wearer through rest and every gesture once, collecting unlabelled signal; or
        through rest alone, for a model that asks for that (`calibration_rest_s`)."""
        with self._lock:
            m = self._model
            if m is None or not m.needs_calibration:
                return False
            t = time.monotonic()
            rest_only = m.calibration_rest_s > 0
            end = t + (m.calibration_rest_s if rest_only else CALIB_REST_S)
            seq = [("힘을 빼고 쉬세요", "rest", end)]
            for g in ([] if rest_only else m.gestures):
                if g == "rest":
                    continue
                end += CALIB_HOLD_S
                seq.append((gestures.name(g), g, end))
                end += CALIB_GAP_S
                seq.append(("쉬세요", "rest", end))
            self._calib, self._calib_t0, self._calib_note = seq, t, ""
            m.calibration_start()
            return True

    def cancel_calibration(self) -> None:
        with self._lock:
            if self._calib is not None and self._model is not None:
                self._model.calibration_cancel()
                self._calib, self._calib_note = None, "보정을 취소했습니다"

    # ------------------------------------------------------------ the worker
    def _run(self) -> None:
        next_health = 0.0
        while not self._stop.is_set():
            now = time.monotonic()
            try:
                if now >= next_health:
                    next_health = now + HEALTH_S
                    self._check_health()
                with self._lock:
                    self._step()
                    self._calib_step()
            except Exception as e:                   # noqa: BLE001 - keep the worker alive, park the robot, say so
                with self._lock:
                    self._error, self._error_t = f"{type(e).__name__}: {e}", now
                    self._gen = -1                   # skip the samples that broke it
            self._stop.wait(TICK_S)

    def _check_health(self) -> None:
        rp = self.link.replay
        h = self.health_monitor.check(self.link.snapshot(), self.link.emg.last(500),
                                      replay_finished=bool(rp is not None and rp.finished))
        with self._lock:
            self._health = h

    def _step(self) -> None:
        m = self._model
        if self._gen == -1:                          # (re)start at the newest sample
            self._gen, self._pos = self.link.gen, self.link.emg.total
            if m is not None:
                m.reset()
            return
        gen, raw, t, pos = self.link.read_since(self._gen, self._pos)
        if gen != self._gen and m is not None:
            m.reset()
        self._gen, self._pos = gen, pos
        if m is None or not len(t) or self.link.mode != "hex":
            return
        t0 = time.perf_counter()
        out = m.feed(t, raw)
        if not out:
            return
        self._cost = 1000 * (time.perf_counter() - t0) / len(out)
        for d in out:
            top = int(np.argmax(d.proba))
            conf = float(d.proba[top])
            confirmed = self.stab.update(m.gestures[top], conf)
            self._seq += 1
            self._recent.append((self._seq, d, confirmed))
            if self._calib is None and self._health.ok:
                # The robot follows the newest window alone: the Kalman filter does the smoothing,
                # so the pose does not also wait for the model's own averaging (measured on
                # recordings: about 0.2 s sooner at the new pose, at the price of more wobble).
                p = d.proba if d.raw is None else d.raw
                self._target = self.poses.blend(m.gestures, p, self.sharpen)
                self._bounds = self.poses.envelope(m.gestures, p)
                self.kalman.update(self._target, d.t, float(np.max(p)))
        self._last = out[-1]
        self._n_rate += len(out)
        now = time.monotonic()
        if now - self._t_rate >= 1.0:
            self._rate, self._n_rate, self._t_rate = self._n_rate / (now - self._t_rate), 0, now

    def _calib_step(self) -> None:
        if self._calib is None:
            return
        if time.monotonic() >= self._calib[-1][2]:
            ok, note = self._model.calibration_finish()
            self._calib = None
            self._calib_note = f"{note} ({time.strftime('%H:%M')})" if ok else note
            self.stab.reset()

    # ------------------------------------------------------------ what the robot should do
    def _parked(self) -> str:
        """Why the robot is held at home, or '' when it may follow the hand."""
        if self._hold:
            return "정지 버튼"
        if self._error and time.monotonic() - self._error_t < ERROR_HOLD_S:
            return "내부 오류"
        if self._model is None:
            return "모델을 고르세요"
        if not self._health.ok:
            return "암밴드 신호 이상"
        if self._calib is not None:
            return "착용 보정 중"
        if self._last is None or time.perf_counter() - self._last.t > STALE_S:
            return "판정 대기"
        return ""

    def pose_ahead(self, ahead: float) -> np.ndarray:
        """The pose expected `ahead` seconds from now: the Kalman prediction while the signal is
        good, the home pose otherwise. Called by the robot sender."""
        with self._lock:
            if self._parked():
                home = self.poses.home
                self.kalman.reset(home)              # start from rest when the signal returns
                return home.copy()
            return self.kalman.predict(time.perf_counter(), ahead, self._bounds)

    def scene_request(self) -> str | None:
        """The gesture whose scene should play: the confirmed gesture while the signal is good,
        None (stand by at home) otherwise. Called by the theater driver."""
        with self._lock:
            return None if self._parked() else self.stab.shown

    # ------------------------------------------------------------ what the screen shows
    def state(self) -> EngineState:
        with self._lock:
            m, d = self._model, self._last
            calib = None
            if self._calib is not None:
                now = time.monotonic()
                cur = next((s for s in self._calib if now < s[2]), self._calib[-1])
                total = self._calib[-1][2] - self._calib_t0
                calib = CalibStep(cur[0], cur[1], max(0.0, cur[2] - now), min(1.0, (now - self._calib_t0) / total))
            reason = self._parked()
            if self.mode == "theater" and not reason and self.stab.shown is None:
                reason = "동작 확정 대기"
            scene = self.theater.status() if self.mode == "theater" and self.theater else (None, 0, 0, False)
            stale = d is None or time.perf_counter() - d.t > STALE_S
            top = m.gestures[int(np.argmax(d.proba))] if (m and d is not None) else None
            return EngineState(
                health=self._health, model_title=m.title if m else "", gestures=tuple(m.gestures) if m else (),
                proba=None if d is None else d.proba, top=top, confirmed=self.stab.shown,
                confidence=0.0 if d is None else float(np.max(d.proba)), stale=stale,
                parked=bool(reason), park_reason=reason,
                target=None if self._target is None else self._target.copy(),
                filtered=self.kalman.position,
                predicted=None if self.mode == "theater" else self.poses.home.copy() if reason
                else self.kalman.predict(time.perf_counter(), self.follow.predict_ms / 1000.0, self._bounds),
                mode=self.mode, scene=scene[0], scene_card=(scene[1], scene[2]), scene_missing=scene[3],
                rate=self._rate, cost_ms=self._cost, calib=calib, calib_note=self._calib_note,
                calibrated=m.calibrated if m else True,
                error=self._error if time.monotonic() - self._error_t < 30 else "", seq=self._seq)

    def decisions_since(self, seq: int) -> list[tuple[int, Decision, str | None]]:
        """Decisions newer than `seq`, each with the gesture confirmed at that moment: for views
        that draw every decision (the map's trail)."""
        with self._lock:
            return [r for r in self._recent if r[0] > seq]

    def raw_last(self, n: int) -> np.ndarray:
        return self.link.emg.last(n)
