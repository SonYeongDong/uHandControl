"""Everything behind the screen: models, confirmed gesture, pose prediction, health, robot sender."""
from __future__ import annotations

import copy
import os
import sys
import time

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))     # the source tree, not an installed copy

from uhand_emg_live import config                                           # noqa: E402
from uhand_emg_live.decide.stabilizer import Stabilizer                     # noqa: E402
from uhand_emg_live.engine import Engine                                    # noqa: E402
from uhand_emg_live.gestures import PUPPET                                  # noqa: E402
from uhand_emg_live.models import Decision, GestureModel, discover          # noqa: E402
from uhand_emg_live.motion.kalman import PoseKalman                         # noqa: E402
from uhand_emg_live.motion.poses import HI, LO, PoseTable                   # noqa: E402
from uhand_emg_live.robot.drivers import Command, FollowDriver, TheaterDriver   # noqa: E402
from uhand_emg_live.robot.scenes import load_scenes                         # noqa: E402
from uhand_emg_live.robot.sender import CONNECTED, RETRY, RobotSender       # noqa: E402
from uhand_emg_live.robot.sim import HandSim                                # noqa: E402
from uhand_emg_live.sensor.health import CH_FLAT, CH_OFFSET, CH_OK, CH_SATURATED, HealthMonitor   # noqa: E402
from uhand_emg_live.sensor.link import Link                                 # noqa: E402
from uhand_emg_live.sensor.protocol import LinkState                        # noqa: E402
from uhand_emg_live.sensor.stats import LinkSnapshot                        # noqa: E402
from tests.fake_uhand import FakeUHand                           # noqa: E402

CFG = config.load()
SPECS, PROBLEMS = discover(config.MODELS_DIR)


def signal(seconds: float, seed: int = 0):
    """Gap-free synthetic armband samples (times, raw 0..255)."""
    n = int(seconds * 500)
    rng = np.random.default_rng(seed)
    return 100.0 + np.arange(n) / 500.0, np.clip(np.rint(127 + rng.normal(0, 6, (n, 8))), 0, 255)


def feed_in_frames(model, t, x):
    out = []
    for a in range(0, len(t), 10):
        out += model.feed(t[a:a + 10], x[a:a + 10])
    return out


# ------------------------------------------------------------------ models
def rested(model):
    """A model that decides nothing before its rest calibration is given one."""
    if model.calibration_rest_s:
        t, x = signal(model.calibration_rest_s, seed=1)
        model.calibration_start()
        feed_in_frames(model, t - 50.0, x)
        assert model.calibration_finish()[0]
        model.reset()
    return model


def test_discover_finds_every_family():
    assert not PROBLEMS, PROBLEMS
    kinds = {s.kind for s in SPECS}
    assert kinds == {"CNN", "RF", "SVM"}
    files = [s.path for s in SPECS]
    assert len(files) == len(set(files))                        # the two .joblib families each take their own files


@pytest.mark.parametrize("spec", SPECS, ids=[s.title for s in SPECS])
def test_model_decides_every_100ms(spec):
    m = rested(spec.load())
    t, x = signal(3.0)
    out = feed_in_frames(m, t, x)
    n = round((3.0 - m.delay_s) / 0.1)
    assert len(out) == (n if spec.kind == "SVM" else n + 1)     # the SVM decides on a time grid, not at a sample count
    assert np.allclose(np.diff([d.t for d in out]), 0.1)
    for d in out:
        assert d.proba.shape == (len(m.gestures),) and abs(d.proba.sum() - 1) < 1e-6
    assert m.gestures[0] == "rest" and len(set(m.gestures)) == len(m.gestures)
    assert not PoseTable(CFG["poses"]).missing(m.gestures)      # every gesture has a robot pose


def test_model_restarts_its_window_after_a_dropout():
    for spec in SPECS:
        m = rested(spec.load())
        t, x = signal(2.0)
        t[600:] += 0.3                                           # 0.3 s of samples lost
        out = feed_in_frames(m, t, x)
        gap_end = t[600]
        assert not [d for d in out if gap_end <= d.t < gap_end + m.delay_s - 0.003], spec.title


def test_forest_matches_sklearn_and_reports_votes():
    spec = next(s for s in SPECS if s.kind == "RF")
    m = spec.load()
    from uhand_emg_live.models.rf_features import ROWS, features
    _, x = signal(0.5, seed=3)
    f = features(x[:ROWS] - 127.0)
    assert f.shape == (88,)
    p, votes = m.classify(f)
    assert np.allclose(p, m.forest.predict_proba(f.reshape(1, -1))[0])
    assert votes.shape == (m.n_trees,) and votes.max() < len(m.gestures)
    # the tree the view draws: the reported path runs parent to child and ends where scikit-learn says
    tree = m.view_data()["tree"]
    path = m.path(f)
    assert path[0] == 0 and path[-1] == m._trees[tree["index"]].apply(f.reshape(1, -1).astype(np.float32))[0]
    assert all(b in (tree["left"][a], tree["right"][a]) for a, b in zip(path, path[1:]))
    assert tree["left"][path[-1]] == -1 and votes[tree["index"]] == tree["answer"][path[-1]]


def test_forest_loader_refuses_other_pickles(tmp_path):
    import pickle
    from uhand_emg_live.models.rf_features import load_forest
    bad = tmp_path / "bad.joblib"
    bad.write_bytes(pickle.dumps(os.getcwd))                     # any callable outside the allowlist
    with pytest.raises(pickle.UnpicklingError):
        load_forest(str(bad))


def test_svm_decides_only_after_its_rest_calibration():
    m = next(s for s in SPECS if s.kind == "SVM").load()
    assert m.needs_calibration and not m.calibrated
    assert feed_in_frames(m, *signal(3.0)) == []                 # no resting level yet: no decision
    m.calibration_start()
    assert not m.calibration_finish()[0]                         # nothing arrived meanwhile
    m.calibration_start()
    t, x = signal(8.0, seed=1)
    feed_in_frames(m, t + 10.0, x)
    ok, note = m.calibration_finish()
    assert ok and m.calibrated and "보정됨" in note
    m.reset()                                                    # a restart of the stream keeps the calibration
    t, x = signal(2.0, seed=2)
    out = feed_in_frames(m, t + 30.0, x)
    assert len(out) == 12 and all(d.raw.max() == 1 and d.raw.sum() == 1 for d in out)     # one label per decision
    assert np.allclose(out[2].proba, np.mean([d.raw for d in out[:3]], axis=0))            # the share of the last three
    # a dropout: nothing is decided until 0.8 s of unbroken signal is there again
    again = feed_in_frames(m, t + 32.5, x)
    assert again and again[0].t >= t[0] + 32.5 + 0.8 - 1e-6


def test_svm_view_shows_the_duels_the_label_comes_from():
    import copy as _copy
    m = rested(next(s for s in SPECS if s.kind == "SVM").load())
    data = m.view_data()
    n, pairs = len(m.gestures), data["pairs"]
    assert m.view == "duels" and len(pairs) == n * (n - 1) // 2 == len(data["support"])
    assert all(0 < a <= data["total"] and 0 < b <= data["total"] for a, b in data["support"])
    svc = _copy.copy(m.model.steps[-1][1])
    svc.decision_function_shape = "ovo"                                  # scikit-learn's own pairwise margins
    rng = np.random.default_rng(3)
    for d in feed_in_frames(m, *signal(2.0, seed=4)):
        assert d.view["duels"].shape == (len(pairs),)
    # a duel's support vectors lie on its margin: decision value +1 for the first gesture's, -1 for the second's
    table = m._duels
    for p in (0, 13, 27):
        used = np.flatnonzero(table["weight"][p])
        x = table["sv"][used]
        k = np.exp(-table["gamma"] * ((x ** 2).sum(1)[:, None] + table["sq"][None, :] - 2 * x @ table["sv"].T))
        value = k @ table["weight"][p] + table["bias"][p]
        assert np.allclose(value, np.sign(table["weight"][p, used]), atol=2e-2)
    for _ in range(20):
        v = rng.normal(0, 1.5, 92 * 7)
        got = m.duels(v)["duels"]
        assert np.allclose(got, svc.decision_function(m.model[:-1].transform(v[None]))[0], atol=1e-3)
        wins = np.zeros(n, int)
        for (i, j), margin in zip(pairs, got):
            wins[i if margin > 0 else j] += 1
        assert m.gestures[int(wins.argmax())] == PUPPET[int(m.model.predict(v[None])[0])]    # most wins = the label


def test_cnn_calibration_changes_the_placement():
    m = next(s for s in SPECS if s.kind == "CNN").load()
    assert m.needs_calibration and not m.calibrated
    m.calibration_start()
    feed_in_frames(m, *signal(15.0))
    ok, _ = m.calibration_finish()
    assert ok and m.calibrated


# ------------------------------------------------------------------ confirmed gesture
def test_stabilizer_needs_a_run_of_confident_decisions():
    s = Stabilizer(0.6, 3)
    assert [s.update("fist", 0.9) for _ in range(3)] == [None, None, "fist"]
    assert s.update("open", 0.9) == "fist" and s.update("fist", 0.9) == "fist"      # run broken
    assert [s.update("open", 0.5) for _ in range(5)][-1] == "fist"                   # never confident
    assert [s.update("open", 0.7) for _ in range(3)][-1] == "open"


# ------------------------------------------------------------------ poses and prediction
def test_blend_leans_to_the_likeliest_gesture():
    table = PoseTable(CFG["poses"])
    g = ["rest", "fist", "open"]
    assert np.allclose(table.blend(g, [0, 1, 0]), table.pose("fist"))
    mixed = table.blend(g, [0.0, 0.7, 0.3], sharpen=2.0)
    plain = table.blend(g, [0.0, 0.7, 0.3], sharpen=1.0)
    assert abs(mixed[1] - table.pose("fist")[1]) < abs(plain[1] - table.pose("fist")[1])
    lo, hi = table.envelope(g, [0.05, 0.75, 0.2])
    assert lo[1] == 800 and hi[1] == 2000                        # rest (5%) is not a candidate


def test_pose_table_rejects_out_of_range_values():
    with pytest.raises(ValueError):
        PoseTable({"fist": [2300, 800, 800, 800, 800, 1500]})


def ramp(k: PoseKalman, a, b, seconds=0.5, hold=1.0):
    """Target moving from a to b over `seconds`, then held; decisions every 0.1 s."""
    t, rows = 0.0, []
    while t < seconds + hold + 1e-9:
        z = a + (b - a) * min(1.0, t / seconds)
        k.update(z, t)
        rows.append((t, z.copy(), k.position.copy(), k.predict(t, 0.25)))
        t += 0.1
    return rows


def test_prediction_leads_the_target_during_a_move_and_settles():
    m = CFG["motion"]
    k = PoseKalman(LO, HI, m["accel"], m["noise"])
    a, b = np.full(6, 1500.0), np.array([2200, 800, 800, 800, 800, 1500.0])
    k.reset(a)
    k.update(a, -0.1)
    rows = ramp(k, a, b)
    mid = [r for r in rows if 0.25 <= r[0] <= 0.45]
    for _, z, pos, pred in mid:                                  # index finger axis: 1500 -> 800
        assert pred[1] < z[1] - 20, "the prediction should be ahead of the measured target"
    final = rows[-1]
    assert np.allclose(final[2], b, atol=25) and np.allclose(final[3], b, atol=25)
    assert all(np.all(r[3] >= LO) and np.all(r[3] <= HI) for r in rows)


def test_prediction_stays_inside_the_candidate_poses():
    k = PoseKalman(LO, HI, 25.0, 0.25)
    a, b = np.full(6, 1500.0), np.full(6, 1200.0)
    k.reset(a)
    k.update(a, -0.1)
    for t, z, pos, _ in ramp(k, a, b, seconds=0.3, hold=0.6):
        lo, hi = np.minimum(a, b), np.maximum(a, b)
        p = k.predict(t, 0.25, (lo, hi))
        assert np.all(p >= lo - 1e-6) and np.all(p <= hi + 1e-6)


def test_low_confidence_slows_the_filter():
    out = []
    for conf in (1.0, 0.3):
        k = PoseKalman(LO, HI, 25.0, 0.25)
        k.reset(np.full(6, 1500.0))
        k.update(np.full(6, 1500.0), 0.0)
        k.update(np.full(6, 2000.0), 0.1, conf)
        out.append(k.position[1])
    assert out[1] < out[0]


# ------------------------------------------------------------------ health
def snap(**kw) -> LinkSnapshot:
    base = dict(source="COM4", state=LinkState.CONNECTED, error="", mode="hex", gen=1, uptime=10.0, idle=0.01,
                bytes_total=1, bps=4900.0, sps=500.0, frames_ok=500, resync_bytes=0, lost_frames=0, irregular_ts=0,
                last_ts=0, ts_mean=20.0, ts_min=20, ts_max=20, lines_ok=0, lines_bad=0, battery=80, imu=None,
                mode_changes=1, battery_history=(), rate_history=())
    return LinkSnapshot(**{**base, **kw})


def test_health_good_signal_is_ok():
    h = HealthMonitor(**CFG["health"]).check(snap(), signal(1.0)[1])
    assert h.ok and h.level == "ok" and not h.issues


@pytest.mark.parametrize("change, word", [
    (dict(state=LinkState.DISCONNECTED), "연결되지"),
    (dict(state=LinkState.ERROR, error="포트 없음"), "포트 없음"),
    (dict(idle=2.0), "끊겼습니다"),
    (dict(idle=None), "들어오지"),
    (dict(mode="ascii"), "ASCII"),
])
def test_health_errors_park_the_robot(change, word):
    h = HealthMonitor(**CFG["health"]).check(snap(**change), signal(1.0)[1])
    assert not h.ok and any(word in i.text for i in h.issues)


def test_health_warnings_do_not_park():
    mon = HealthMonitor(**CFG["health"])
    x = signal(1.0)[1]
    assert mon.check(snap(battery=10), x).level == "warn"
    assert mon.check(snap(sps=380.0), x).level == "warn"
    mon.check(snap(lost_frames=0), x)
    h = mon.check(snap(lost_frames=7), x)
    assert h.ok and any("7개 손실" in i.text for i in h.issues)


def test_health_names_the_bad_channels():
    x = signal(1.0)[1]
    x[:, 1] = 127                       # flat
    x[::3, 4] = 255                     # saturated a third of the time
    x[:, 6] += 60                       # offset
    mon = HealthMonitor(**CFG["health"])
    h = mon.check(snap(), x, now=0.0)
    assert h.channels == (CH_OK, CH_OK, CH_OK, CH_OK, CH_SATURATED, CH_OK, CH_OFFSET, CH_OK)   # quiet, not yet flat
    h = mon.check(snap(), x, now=CFG["health"]["flat_s"] + 1.0)
    assert h.channels == (CH_OK, CH_FLAT, CH_OK, CH_OK, CH_SATURATED, CH_OK, CH_OFFSET, CH_OK)
    assert h.ok and "CH2" in h.issues[0].text and "CH5" in h.issues[0].text and "CH7" in h.issues[0].text


def test_health_a_resting_arm_is_not_a_fault():
    mon = HealthMonitor(**CFG["health"])
    x = np.full((500, 8), 127.0)
    x[::50, :] = 128                    # all channels within one count, as at rest
    for now in (0.0, 10.0, 60.0):
        h = mon.check(snap(), x, now=now)
    assert h.level == "ok" and set(h.channels) == {CH_OK}


# ------------------------------------------------------------------ robot sender
def wait_for(cond, seconds=5.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_sender_sends_changes_only_and_reconnects():
    server = FakeUHand()
    pose = {"p": np.full(6, 1500.0)}
    sim = HandSim()
    s = RobotSender(FollowDriver(lambda ahead: pose["p"], step_ms=100, predict_ms=100, deadband=10), sim)
    s.start()
    try:
        s.set_endpoint(("127.0.0.1", server.port))
        assert wait_for(lambda: s.status().state == CONNECTED)
        assert wait_for(lambda: len(server.moves) == 1)          # the first pose
        time.sleep(0.4)
        assert len(server.moves) == 1                            # nothing new: nothing sent
        pose["p"] = np.array([2200, 800, 800, 800, 800, 1500.0])
        assert wait_for(lambda: len(server.moves) == 2)
        assert server.moves[-1] == ([2200, 800, 800, 800, 800, 1500], 100)
        assert wait_for(lambda: np.allclose(sim.position(), pose["p"]))
        # accepted so far: buzzer off and LED off when the driver took over, then the two poses
        assert wait_for(lambda: s.status().sent == 4)                # the reply comes when the move is done
        st = s.status()
        assert st.sent == 4 and st.rtt_ms is not None and st.rtt_ms >= 100 and st.last == (2200, 800, 800, 800, 800, 1500)
        server.drop()                                            # cable pulled
        pose["p"] = np.full(6, 1500.0)
        assert wait_for(lambda: s.status().state in (RETRY, CONNECTED) and s.status().failed >= 1, 8)
        assert wait_for(lambda: s.status().state == CONNECTED, 8)   # back by itself
        assert wait_for(lambda: server.moves[-1][0] == [1500] * 6)
    finally:
        s.close()
        server.close()


def test_sender_without_a_robot_still_moves_the_simulation():
    sim = HandSim()
    target = np.array([800, 2000, 2000, 2000, 2000, 1500.0])
    s = RobotSender(FollowDriver(lambda ahead: target, step_ms=100), sim)
    s.start()
    try:
        assert wait_for(lambda: np.allclose(sim.position(), target))
        assert s.status().state == "off" and s.status().sent == 0
    finally:
        s.close()


def test_sender_reports_an_unreachable_robot():
    s = RobotSender(FollowDriver(lambda ahead: np.full(6, 1500.0)), HandSim())
    s.start()
    try:
        s.set_endpoint(("127.0.0.1", 1))                         # nothing listens there
        assert wait_for(lambda: s.status().state == RETRY and s.status().error, 8)
    finally:
        s.close()


# ------------------------------------------------------------------ the whole pipeline
def test_engine_parks_until_signal_then_follows_and_parks_again():
    link = Link()
    eng = Engine(CFG, link)
    eng.start()
    try:
        assert eng.state().parked and eng.state().park_reason == "모델을 고르세요"
        eng.set_model(next(s for s in SPECS if s.kind == "RF").load())
        time.sleep(0.5)
        st = eng.state()
        assert st.parked and not st.health.ok                    # no armband yet
        assert np.allclose(eng.pose_ahead(0.25), eng.poses.home)
        link.open_demo("hex")
        assert wait_for(lambda: not eng.state().parked, 6), eng.state().park_reason
        st = eng.state()
        assert st.health.ok and st.proba is not None and st.predicted is not None
        assert wait_for(lambda: eng.state().rate > 5, 4)             # about ten decisions a second
        assert eng.decisions_since(0) and "votes" in eng.decisions_since(0)[-1][1].view
        eng.set_hold(True)                                       # the stop button, with a good signal
        assert eng.state().parked and eng.state().park_reason == "정지 버튼"
        assert np.allclose(eng.pose_ahead(0.25), eng.poses.home) and eng.scene_request() is None
        eng.set_hold(False)
        assert not eng.held
        assert wait_for(lambda: not eng.state().parked, 3), eng.state().park_reason
        link.close()                                             # armband lost
        assert wait_for(lambda: eng.state().parked, 3)
        assert np.allclose(eng.pose_ahead(0.25), eng.poses.home)
    finally:
        eng.close()


def test_engine_guides_a_calibration_and_parks_the_robot_meanwhile(monkeypatch):
    import uhand_emg_live.engine as eng_mod
    monkeypatch.setattr(eng_mod, "CALIB_REST_S", 5.0)        # short, but still over the 100 windows a placement needs
    monkeypatch.setattr(eng_mod, "CALIB_HOLD_S", 0.5)
    monkeypatch.setattr(eng_mod, "CALIB_GAP_S", 0.4)
    link = Link()
    eng = Engine(CFG, link)
    eng.start()
    try:
        eng.set_model(next(s for s in SPECS if s.kind == "CNN").load())
        link.open_demo("hex")
        assert wait_for(lambda: not eng.state().parked, 6)
        assert not eng.state().calibrated
        assert eng.start_calibration()
        st = eng.state()
        assert st.calib is not None and st.calib.gesture == "rest" and st.parked and st.park_reason == "착용 보정 중"
        seen = set()
        assert wait_for(lambda: seen.add(getattr(eng.state().calib, "gesture", None)) or eng.state().calib is None, 25)
        assert {"rest", "fist", "open"} <= seen                  # walked through the gestures
        st = eng.state()
        assert st.calibrated and "보정됨" in st.calib_note
        assert wait_for(lambda: not eng.state().parked, 3)
        # a model without calibration refuses politely
        eng.set_model(next(s for s in SPECS if s.kind == "RF").load())
        assert not eng.start_calibration()
    finally:
        eng.close()


def test_engine_calibrates_a_rest_only_model_with_rest_alone():
    link = Link()
    eng = Engine(CFG, link)
    eng.start()
    try:
        m = next(s for s in SPECS if s.kind == "SVM").load()
        m.calibration_rest_s = 4.0                               # short, but still over the 30 windows it asks for
        eng.set_model(m)
        link.open_demo("hex")
        assert wait_for(lambda: eng.state().park_reason == "판정 대기", 6)       # signal, but no decision before calibration
        assert not eng.state().calibrated and eng.start_calibration()
        seen = set()
        assert wait_for(lambda: seen.add(getattr(eng.state().calib, "gesture", None)) or eng.state().calib is None, 8)
        assert seen - {None} == {"rest"}                         # no walk through the gestures
        st = eng.state()
        assert st.calibrated and "보정됨" in st.calib_note
        assert wait_for(lambda: not eng.state().parked, 4)
    finally:
        eng.close()


# ------------------------------------------------------------------ puppet show: scene files
IDS = CFG["theater"]["ids"]
A, B, C = [2200, 800, 800, 800, 800, 1500], [800, 2000, 2000, 2000, 2000, 1500], [1500, 1500, 1500, 1500, 1500, 900]


def scene_file(folder, number, cards, version=2):
    import json
    doc = {"format": "uhand-motion-sequence", "schema_version": version,
           "units": {"pulse": "us", "running_time": "ms", "frequency": "Hz"}, "cards": cards}
    (folder / f"action_{number:02d}.uhjson").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def motion(pulses, ms=100, name="동작"):
    return {"name": name, "kind": "motion", "pulses": pulses, "running_time": ms}


def test_scene_files_load_like_the_theater_program(tmp_path):
    scene_file(tmp_path, IDS["fist"], [
        {"name": "초록", "kind": "led", "red": 0, "green": 255, "blue": 0, "brightness": 40},
        {"name": "삐", "kind": "buzzer", "frequency": 440, "running_time": 200, "continuous": False},
        motion(A, 300), motion(B, 300)])
    scene_file(tmp_path, IDS["open"], [{"name": "빨강", "kind": "led", "red": True, "green": False, "blue": False}], version=1)
    scene_file(tmp_path, IDS["index"], [motion([2300, 800, 800, 800, 800, 1500])])      # thumb out of range
    (tmp_path / f"action_{IDS['rest']:02d}.uhjson").write_text("not json", encoding="utf-8")
    got = load_scenes(str(tmp_path), IDS)
    fist = got.scenes["fist"]
    assert [c.kind for c in fist.cards] == ["led", "buzzer", "motion", "motion"] and fist.repeat_from == 0
    assert fist.cards[0].args == (0, 255, 0, 40) and fist.cards[2].args == (*A, 300) and not fist.missing
    assert got.scenes["open"].cards[0].args == (255, 0, 0, 100)          # schema 1: on/off channels, full brightness
    assert got.scenes["open"].repeat_from is None                        # nothing timed: shown once
    assert set(got.damaged) == {"index", "rest"} and "카드 1" in got.damaged["index"]
    # no file: the stand-in of that program (red light, the action's tone, fingers = the number in binary)
    ulnar = got.scenes["ulnar_dev"]
    assert ulnar.missing and ulnar.repeat_from == 2 and ulnar.cards[0].args == (255, 0, 0, 50)
    assert ulnar.cards[2].args == (800, 2000, 800, 800, 800, 1500, 300)  # 7 = 0111: middle, ring, little bent
    assert got.file_name("fist") == "action_06.uhjson"


def play(driver, n):
    return [driver.step() for _ in range(n)]


def test_engine_adds_a_scene_file_from_anywhere(tmp_path):
    cfg = copy.deepcopy(CFG)
    scenes, elsewhere = tmp_path / "scenes", tmp_path / "elsewhere"
    scenes.mkdir()
    elsewhere.mkdir()
    cfg["theater"].update(folder=str(scenes), library="")
    eng = Engine(cfg, Link())
    scene_file(elsewhere, 3, [motion(A, 300)])
    made = elsewhere / "action_03.uhjson"
    wave = elsewhere / "인사.uhjson"
    wave.write_bytes(made.read_bytes())
    added = eng.add_scene_file(str(wave))
    assert os.path.dirname(added) == str(scenes) and os.path.basename(added) == "인사.uhjson"
    assert ("인사", added) in eng.scene_library()
    assert eng.add_scene_file(str(wave)) == added and eng.add_scene_file(added) == added      # no second copy
    assert len(list(scenes.glob("*.uhjson"))) == 1
    # a file named like a gesture's default must not become that default
    assert os.path.basename(eng.add_scene_file(str(made))) == "added_action_03.uhjson"
    # the scene folder's own defaults are not listed, but a library of action_NN files is
    scene_file(scenes, 5, [motion(A, 300)])
    cfg["theater"]["library"] = str(elsewhere)
    names = [os.path.basename(p) for _, p in eng.scene_library()]
    assert "action_05.uhjson" not in names and "action_03.uhjson" in names
    cfg["theater"]["library"] = ""
    # the same name with other content gets its own copy
    other = tmp_path / "인사.uhjson"
    scene_file(elsewhere, 4, [motion(B, 500)])
    other.write_bytes((elsewhere / "action_04.uhjson").read_bytes())
    assert os.path.basename(eng.add_scene_file(str(other))) == "인사 (2).uhjson"
    # not a scene file: refused, nothing copied
    bad = tmp_path / "bad.uhjson"
    bad.write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError):
        eng.add_scene_file(str(bad))
    assert not (scenes / "bad.uhjson").exists()
    eng.set_scene_file("fist", added)
    eng.set_mode("theater")
    try:
        fist = next(r for r in eng.scene_report() if r.key == "fist")
        assert fist.state == "ok" and fist.file == "인사.uhjson" and fist.cards == 1 and fist.picked == added
    finally:
        eng.close()


def test_engine_switches_every_gesture_to_a_set_of_scene_files(tmp_path):
    cfg = copy.deepcopy(CFG)
    scenes = tmp_path / "scenes"
    puppet = scenes / "인형 동작"
    puppet.mkdir(parents=True)
    (scenes / "_old").mkdir()                                            # not a set: the name starts with _
    (scenes / "빈 폴더").mkdir()                                          # not a set: no numbered scene file
    cfg["theater"].update(folder=str(scenes), library="")
    scene_file(scenes, IDS["fist"], [motion(A, 100)])
    scene_file(puppet, IDS["fist"], [motion(B, 300), motion(A, 300)])    # action_06.uhjson
    rest = puppet / f"{IDS['rest']}_초기동작.uhjson"
    rest.write_bytes((puppet / "action_06.uhjson").read_bytes())
    note = puppet / "메모.uhjson"                                         # no number: in the lists, not in the set
    note.write_bytes(rest.read_bytes())
    eng = Engine(cfg, Link())
    try:
        assert [name for name, _ in eng.scene_sets()] == ["기본 동작", "인형 동작"]
        assert eng.scene_set() == "기본 동작"
        assert ("메모", str(note)) in eng.scene_library()
        eng.set_mode("theater")
        eng.set_scene_set("인형 동작")
        report = {r.key: r for r in eng.scene_report()}
        assert report["fist"].cards == 2 and report["rest"].file == rest.name and report["open"].state == "missing"
        assert eng.scene_set() == "인형 동작"
        again = Engine(cfg, Link())                                      # saved: the next run starts with it
        assert again.scene_set() == "인형 동작"
        again.close()
        eng.set_scene_file("open", str(note))
        assert eng.scene_set() is None                                   # picked one by one: no set
        eng.set_scene_set("기본 동작")
        assert eng.scene_files == {} and next(r for r in eng.scene_report() if r.key == "fist").cards == 1
        with pytest.raises(ValueError):
            eng.set_scene_set("없는 세트")
    finally:
        eng.close()


def test_theater_driver_plays_repeats_and_switches_between_cards(tmp_path):
    scene_file(tmp_path, IDS["fist"], [{"name": "초록", "kind": "led", "red": 0, "green": 255, "blue": 0, "brightness": 100},
                                       motion(A), motion(B)])
    scene_file(tmp_path, IDS["open"], [motion(C)])
    scenes = load_scenes(str(tmp_path), IDS)
    want = {"g": None}
    d = TheaterDriver(lambda: want["g"], scenes)
    d.reset()
    home = Command("motion", (1500,) * 6 + (500,))
    off = [Command("buzzer", (0, 100, True)), Command("led", (0, 0, 0, 100))]
    assert play(d, 4) == off + [home, None]                              # goes home first, then stands by
    want["g"] = "fist"
    led, a, b, c = Command("led", (0, 255, 0, 100)), Command("motion", (*A, 100)), Command("motion", (*B, 100)), \
        Command("motion", (*C, 100))
    assert play(d, 5) == [led, a, b, led, a] and d.status() == ("fist", 2, 3, False)     # repeats from the top
    want["g"] = "open"                                                   # asked in the middle of the fist scene
    assert play(d, 2) == [c, c] and d.status()[0] == "open"              # the next card is already the new scene
    want["g"] = "ulnar_dev"                                              # no file: the stand-in
    assert [x.kind for x in play(d, 4)] == ["led", "buzzer", "motion", "motion"] and d.status()[3]
    want["g"] = "fist"                                                   # leaving the stand-in: its light and tone go off
    assert play(d, 3) == off + [led]
    want["g"] = None                                                     # signal lost
    assert play(d, 4) == off + [home, None] and d.status()[0] is None
    want["g"] = "scissors"                                               # a gesture without a scene: stay home
    assert d.step() is None


def test_theater_driver_can_mute_light_and_sound_but_keeps_the_timing(tmp_path):
    scene_file(tmp_path, IDS["fist"], [
        {"name": "초록", "kind": "led", "red": 0, "green": 255, "blue": 0, "brightness": 100},
        {"name": "삐", "kind": "buzzer", "frequency": 440, "running_time": 200, "continuous": False},
        {"name": "계속", "kind": "buzzer", "frequency": 330, "running_time": 100, "continuous": True},
        motion(A)])
    d = TheaterDriver(lambda: "fist", load_scenes(str(tmp_path), IDS), led=False, buzzer=False)
    d.reset()
    play(d, 3)                                                           # home
    assert play(d, 2) == [Command("wait", (200,)), Command("motion", (*A, 100))]


def test_sender_carries_out_a_scene_on_the_robot(tmp_path):
    scene_file(tmp_path, IDS["fist"], [
        {"name": "파랑", "kind": "led", "red": 0, "green": 0, "blue": 255, "brightness": 50},
        {"name": "삐", "kind": "buzzer", "frequency": 440, "running_time": 100, "continuous": False},
        motion(A, 100), motion(B, 100)])
    server = FakeUHand()
    sim = HandSim()
    want = {"g": None}
    s = RobotSender(TheaterDriver(lambda: want["g"], load_scenes(str(tmp_path), IDS)), sim)
    s.start()
    try:
        s.set_endpoint(("127.0.0.1", server.port))
        assert wait_for(lambda: s.status().state == CONNECTED)
        want["g"] = "fist"
        assert wait_for(lambda: len(server.moves) >= 4)                  # home, A, B, and A again
        names = [m for m, _ in server.commands]
        i = names.index("SetuHandLED", 2)                                # after the two "off" commands of going home
        assert names[i:i + 4] == ["SetuHandLED", "SetuHandBuzzer", "SetuHandPulse", "SetuHandPulse"]
        assert server.commands[i][1] == {"Red": 0, "Green": 0, "Blue": 255, "Brightness": 50}
        assert server.commands[i + 1][1] == {"Frequency": 440, "RunningTime": 100, "Continuous": False}
        assert [m[0] for m in server.moves[1:3]] == [A, B]
        assert sim.led == (0, 0, 127) and s.status().last_text
        want["g"] = None                                                 # stop: lights out, hand home
        assert wait_for(lambda: server.moves[-1] == ([1500] * 6, 500))
        assert wait_for(lambda: sim.led == (0, 0, 0) and sim.tone() == 0)
    finally:
        s.close()
        server.close()


class SureModel(GestureModel):
    """Says one gesture with 90% every 100 ms, whatever the signal: for tests of what follows a decision."""
    title = "sure"
    gestures = ["rest", "fist", "open"]

    def __init__(self) -> None:
        self.say, self.n = "fist", 0

    def reset(self) -> None:
        self.n = 0

    def feed(self, t, x):
        out = []
        for ti in t:
            self.n += 1
            if self.n % 50 == 0:
                p = np.full(len(self.gestures), 0.05)
                p[self.gestures.index(self.say)] = 0.9
                out.append(Decision(float(ti), p))
        return out


def test_engine_theater_mode_plays_the_confirmed_gesture_and_goes_home_without_signal():
    link = Link()
    eng = Engine(CFG, link)
    eng.start()
    try:
        model = SureModel()
        eng.set_model(model)
        eng.set_mode("theater")
        st = eng.state()
        assert st.mode == "theater" and st.predicted is None and st.scene is None and st.parked
        assert set(eng.scenes.ids) == set(IDS)
        report = eng.scene_report()                              # what the screen lists, in action-number order
        assert [r.number for r in report] == sorted(IDS.values())
        assert all(r.state in ("ok", "missing", "damaged") and r.file.endswith(".uhjson") for r in report)
        assert not eng.input_open and eng.replay_prompt() is None
        eng.open_input("demo")
        assert eng.input_open
        assert wait_for(lambda: eng.state().scene == "fist", 8), eng.state().park_reason
        view = eng.robot_view()
        assert view.position.shape == (6,) and len(view.led) == 3 and eng.robot_status().state == "off"
        st = eng.state()
        assert st.confirmed == "fist" and st.scene_card[1] > 0 and not st.parked
        model.say = "open"                                               # the wearer changes gesture
        assert wait_for(lambda: eng.state().scene == "open", 4)
        link.close()                                                     # armband lost: stand by at home
        assert wait_for(lambda: eng.state().scene is None, 4)
        assert wait_for(lambda: np.allclose(eng.sim.position(), eng.poses.home), 4)
        assert eng.sim.led == (0, 0, 0) and eng.sim.tone() == 0
        eng.set_mode("follow")
        assert eng.state().mode == "follow" and eng.state().predicted is not None
    finally:
        eng.close()
