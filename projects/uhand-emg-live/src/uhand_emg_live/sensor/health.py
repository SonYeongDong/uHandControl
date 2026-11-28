"""Is the armband signal fit to drive the robot?

Looks at the link counters and at the last second of raw samples and lists what is wrong.
An "error" means the decisions cannot be trusted (no signal, wrong mode): the engine then parks
the robot. A "warn" is shown but does not stop anything.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

import numpy as np

from .protocol import LinkState
from .stats import LinkSnapshot

CH_OK, CH_FLAT, CH_SATURATED, CH_OFFSET = "ok", "flat", "saturated", "offset"
ACTIVE_STD = 2.0            # a channel this lively shows the wearer is moving
CH_TEXT = {CH_OK: "정상", CH_FLAT: "평탄 (접촉 불량·신호 없음)", CH_SATURATED: "포화 (0 또는 255에 붙음)",
           CH_OFFSET: "오프셋 (중심이 127에서 벗어남)"}


@dataclass(frozen=True)
class Issue:
    level: str          # "error" | "warn"
    text: str


@dataclass(frozen=True)
class Health:
    issues: tuple[Issue, ...] = ()
    channels: tuple[str, ...] = (CH_OK,) * 8
    state: str = "disconnected"         # LinkState value
    mode: str | None = None
    rate: float = 0.0                   # samples per second
    battery: int | None = None
    lost_frames: int = 0
    source: str = ""

    @property
    def ok(self) -> bool:
        """No error: the signal may drive the robot."""
        return not any(i.level == "error" for i in self.issues)

    @property
    def level(self) -> str:
        if not self.ok:
            return "error"
        return "warn" if self.issues else "ok"


@dataclass
class HealthMonitor:
    stall_s: float = 0.5
    min_rate: float = 450
    battery_warn: int = 20
    flat_std: float = 0.3
    flat_s: float = 15
    saturated: float = 0.2
    offset: float = 40
    _lost: deque = field(default_factory=lambda: deque(maxlen=64))     # (time, lost frames, resync bytes)
    _quiet_since: list = field(default_factory=lambda: [None] * 8)     # per channel: quiet from when
    _active_at: list = field(default_factory=lambda: [None] * 8)       # per channel: last time it was lively

    def check(self, snap: LinkSnapshot, recent: np.ndarray, replay_finished: bool = False,
              now: float | None = None) -> Health:
        """recent: the last second or so of raw samples (n, 8), as received."""
        now = time.monotonic() if now is None else now
        issues: list[Issue] = []
        channels = [CH_OK] * 8
        st = snap.state
        if st is LinkState.DISCONNECTED:
            issues.append(Issue("error", "암밴드가 연결되지 않았습니다"))
        elif st is LinkState.ERROR:
            issues.append(Issue("error", f"연결 오류: {snap.error}"))
        elif st is LinkState.CONNECTING:
            issues.append(Issue("error", "연결하는 중입니다"))
        elif replay_finished:
            issues.append(Issue("error", "녹화 재생이 끝났습니다"))
        elif snap.idle is None:
            if snap.uptime > 2.0:
                issues.append(Issue("error", "신호가 들어오지 않습니다. 밴드 전원과 USB 수신기를 확인하세요"))
            else:
                issues.append(Issue("error", "신호를 기다리는 중입니다"))
        elif snap.idle > self.stall_s:
            issues.append(Issue("error", f"신호가 끊겼습니다 ({snap.idle:.1f}초째 수신 없음)"))
        elif snap.mode is None:
            issues.append(Issue("error", "신호 형식을 확인하는 중입니다"))
        elif snap.mode != "hex":
            issues.append(Issue("error", "밴드가 ASCII 모드입니다. 버튼을 1번 눌러 HEX(500 Hz) 모드로 바꾸세요"))
        else:
            if snap.uptime > 2.0 and snap.sps < self.min_rate:
                issues.append(Issue("warn", f"수신 속도가 낮습니다 ({snap.sps:.0f} Hz, 정상 500 Hz)"))
            self._lost.append((now, snap.lost_frames, snap.resync_bytes))
            while self._lost and now - self._lost[0][0] > 5.0:
                self._lost.popleft()
            lost = snap.lost_frames - self._lost[0][1]
            junk = snap.resync_bytes - self._lost[0][2]
            if lost > 0 or junk > 0:
                issues.append(Issue("warn", f"최근 5초 동안 프레임 {max(lost, 0)}개 손실"
                                    + (f", 깨진 바이트 {junk}개" if junk > 0 else "")))
            channels = self.channel_states(recent, now)
            bad = [f"CH{i + 1} {CH_TEXT[c].split(' ')[0]}" for i, c in enumerate(channels) if c != CH_OK]
            if bad:
                issues.append(Issue("warn", "채널 이상: " + ", ".join(bad)))
        if snap.battery is not None and snap.battery < self.battery_warn and st is LinkState.CONNECTED:
            issues.append(Issue("warn", f"배터리가 부족합니다 ({snap.battery}%)"))
        return Health(tuple(issues), tuple(channels), st.value, snap.mode, snap.sps, snap.battery,
                      snap.lost_frames, snap.source)

    def channel_states(self, recent: np.ndarray, now: float = 0.0) -> list[str]:
        """A resting forearm is nearly silent on this 8-bit band (half the channels of a normal
        recording stay within one count for seconds), so a quiet channel is only called flat when
        it has been quiet for `flat_s` while another channel was lively: the arm moved and this
        channel did not see it."""
        if len(recent) < 100:
            self._quiet_since, self._active_at = [None] * 8, [None] * 8
            return [CH_OK] * 8
        x = np.asarray(recent, float)
        std = x.std(axis=0)
        sat = np.mean((x <= 1) | (x >= 254), axis=0)
        off = np.abs(np.median(x, axis=0) - 127.0)
        for c in range(x.shape[1]):
            if std[c] >= ACTIVE_STD:
                self._active_at[c] = now
            if std[c] >= self.flat_std:
                self._quiet_since[c] = None
            elif self._quiet_since[c] is None:
                self._quiet_since[c] = now
        out = []
        for c in range(x.shape[1]):
            if sat[c] > self.saturated:
                out.append(CH_SATURATED)
            elif self._flat(c, std, now):
                out.append(CH_FLAT)
            elif off[c] > self.offset:
                out.append(CH_OFFSET)
            else:
                out.append(CH_OK)
        return out

    def _flat(self, c: int, std: np.ndarray, now: float) -> bool:
        since = self._quiet_since[c]
        if since is None or now - since < self.flat_s:
            return False
        return any(a is not None and a > since for i, a in enumerate(self._active_at) if i != c)
