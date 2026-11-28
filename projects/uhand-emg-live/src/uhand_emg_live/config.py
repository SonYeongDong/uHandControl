"""Settings: built-in defaults, overridden section by section by config.toml in the project folder.

The project folder (`ROOT`) holds what a person edits or replaces: config.toml, models/ and
sequences/. It is projects/uhand-emg-live of the uHandControl checkout the program was started
in (the launcher starts every program there), or UHAND_EMG_HOME when that is set."""
from __future__ import annotations

import copy
import os
import tomllib



def _home() -> str:
    """The project folder: UHAND_EMG_HOME exactly as given when it is set; else
    projects/uhand-emg-live of the checkout the program was started in; else the source tree
    this file sits in (src/uhand_emg_live/config.py -> two levels up)."""
    given = os.environ.get("UHAND_EMG_HOME", "").strip()
    if given:
        return os.path.abspath(given)
    checkout = os.path.join(os.getcwd(), "projects", "uhand-emg-live")
    if os.path.isfile(os.path.join(checkout, "config.toml")):
        return os.path.abspath(checkout)
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


ROOT = _home()
MODELS_DIR = os.path.join(ROOT, "models")
CONFIG_PATH = os.path.join(ROOT, "config.toml")

DEFAULTS: dict = {
    "sensor": {"port": "auto"},
    "robot": {"virtual": "127.0.0.1:5000", "real": "192.168.61.1:5000", "step_ms": 250, "predict_ms": 250,
              "deadband": 10},
    "motion": {"accel": 12.0, "noise": 0.5, "sharpen": 2.0},
    "decide": {"min_prob": 0.6, "hold": 3},
    "theater": {"folder": "sequences", "library": "../uhand-motion-creator/examples/sequences", "led": True, "buzzer": True,
                # EMGRobotHandTheater's action numbers: scene file action_NN.uhjson
                "ids": {"rest": 0, "index": 1, "radial_dev": 2, "wrist_ext": 3, "wrist_flex": 4, "open": 5,
                        "fist": 6, "ulnar_dev": 7}},
    "health": {"stall_s": 0.5, "min_rate": 450, "battery_warn": 20, "flat_std": 0.3, "flat_s": 15, "saturated": 0.2,
               "offset": 40},
    "poses": {
        "home": [1500, 1500, 1500, 1500, 1500, 1500],
        "rest": [1500, 1500, 1500, 1500, 1500, 1500],
        "fist": [2200, 800, 800, 800, 800, 1500],
        "open": [800, 2000, 2000, 2000, 2000, 1500],
        "index": [2200, 2000, 800, 800, 800, 1500],
    },
}


def load(path: str = CONFIG_PATH) -> dict:
    """-> settings dict. A missing file gives the defaults; a broken one raises ValueError."""
    cfg = copy.deepcopy(DEFAULTS)
    try:
        with open(path, "rb") as fh:
            user = tomllib.load(fh)
    except FileNotFoundError:
        return cfg
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"config.toml 형식 오류: {e}") from e
    for section, values in user.items():
        if isinstance(values, dict) and isinstance(cfg.get(section), dict):
            cfg[section].update(values)
        else:
            cfg[section] = values
    return cfg


def endpoint(text: str) -> tuple[str, int]:
    """'192.168.61.1:5000' -> ('192.168.61.1', 5000)."""
    ip, _, port = text.rpartition(":")
    if not ip or not port.isdigit():
        raise ValueError(f"로봇 주소는 'IP:포트' 형식이어야 합니다: {text!r}")
    return ip, int(port)
