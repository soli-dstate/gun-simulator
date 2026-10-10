"""Rotary guns: Gatling clusters and a revolver cannon, turned by a motor, hydraulics, their gas or their recoil."""

import math
import tomllib
from pathlib import Path

import numpy as np
import pytest

from gun_sim import action, lumped, rotary
from gun_sim.config import Gun
from gun_sim.sound import mechanical
from gun_sim.ui import api

CONFIGS = Path(__file__).resolve().parents[1] / "configs"
M134 = CONFIGS / "m134_minigun.toml"
M61 = CONFIGS / "m61_vulcan.toml"
GAU8 = CONFIGS / "gau8_avenger.toml"
GSH = CONFIGS / "gsh623.toml"
SLOSTIN = CONFIGS / "slostin.toml"
BK27 = CONFIGS / "mauser_bk27.toml"
PRESETS = [M134, M61, GAU8, GSH, SLOSTIN, BK27]
BLOWDOWN = 0.025


def load(path, **changes):
    with open(path, "rb") as f:
        data = tomllib.load(f)
    for key, value in changes.items():
        section, name = key.split("__")
        data.setdefault(section, {})[name] = value
    return Gun.from_dict(data)


_shots = {}


def shot(path):
    """The preset's shot (the lumped model: the rotor's tests are about the action, not the bore)."""
    if path not in _shots:
        gun = load(path)
        _shots[path] = lumped.simulate(gun, blowdown_time=BLOWDOWN)
    return _shots[path]


def burst(path, shots=30, rounds=None, **changes):
    return action.simulate(load(path, **changes), shot(path), shots=shots, rounds=rounds)


# Published rates (rounds/min) and how close the presets come.
RATES = {M134: 3000, M61: 6000, GAU8: 3900, GSH: 9000, SLOSTIN: 1900, BK27: 1700}


@pytest.mark.parametrize("path", PRESETS, ids=lambda p: p.stem)
def test_presets_fire_their_burst_at_their_rate(path):
    a = burst(path, shots=40)
    r = a.rotary
    assert a.kind == "rotary" and a.status == "fired", a.warnings
    assert a.shots == 40 and r["shots"] == 40
    assert r["steady_rate"] == pytest.approx(RATES[path], rel=0.1)
    assert not a.warnings
    # The bolts stay locked until the bore has blown down.
    assert r["unlock_pressure"] < rotary.UNLOCK_PRESSURE_WARNING
    # Times are from the first ignition: the spin-up comes before it, and the rotor comes to rest.
    assert a.shot_times[0] == 0.0
    assert a.time[0] < 0 and r["first_shot"] > 0
    assert r["speed"][-1] < 0.05 * r["speed"].max()
    assert a.rounds_left == a.capacity - 40


def test_electric_spins_up_and_brakes():
    a = burst(M134, shots=20)
    names = [e["name"] for e in a.events]
    for name in ("trigger pulled", "first round fed", "fires", "case ejected", "trigger released", "drive brakes",
                 "rotor stops"):
        assert name in names
    assert names.count("fires") == 20 and names.count("case ejected") == 20
    # The rate climbs through the spin-up: the first gap between shots is the longest.
    gaps = np.diff(a.shot_times)
    assert gaps[0] > gaps[-1]
    assert a.motor_peak_power == pytest.approx(load(M134).action.motor_power, rel=0.05)
    # Up on the mount and back into battery once it is over.
    assert a.max_recoil > 0 and a.battery_time is not None and a.battery_speed is not None


def test_a_weak_motor_cannot_turn_the_gun():
    a = burst(M134, shots=20, action__motor_power=20.0)
    assert a.status != "fired"
    assert any("ran down" in w for w in a.warnings)


def test_hydraulic_valve_sets_the_spin_up():
    quick, slow = burst(GAU8, shots=10, action__valve_time=0.1), burst(GAU8, shots=10, action__valve_time=0.8)
    assert slow.rotary["first_shot"] > quick.rotary["first_shot"]


def test_gas_drive_needs_its_starter():
    a = burst(GSH, shots=20, action__starter_energy=0.5)
    assert a.shots < 20 and a.status != "fired"
    assert any("ran down" in w for w in a.warnings)


def test_gas_cylinders_drive_the_rotor():
    a = burst(GSH, shots=20)
    assert a.gas_peak_pressure > 1e6
    assert a.port_cd is not None


def test_more_drag_slows_a_self_driven_gun():
    free = burst(SLOSTIN, shots=40).rotary["steady_rate"]
    held = burst(SLOSTIN, shots=40, action__rotor_damping=0.09).rotary["steady_rate"]
    assert held < free


def test_recoil_drive_turns_the_rotor_from_the_barrels_recoil():
    changes = dict(action__rotary_drive="recoil", action__cam_lever=0.02, action__recoil_stroke=0.03,
                   action__spring_rate=5000.0, action__spring_preload=50.0, action__rotor_damping=0.0,
                   action__friction=5.0, action__feed_force=0.0, feed__belt_hang=0.0)
    a = burst(SLOSTIN, shots=30, **changes)
    assert a.status == "fired" and a.shots == 30
    # The barrels recoil in the receiver every shot, and are back in battery at the end.
    assert a.rotary["cluster"].max() > 1e-3
    assert a.rotary["cluster"][-1] < 1e-4


def test_revolver_layout():
    a = burst(BK27, shots=20)
    geo = a.strokes["rotary"]
    assert geo["layout"] == "revolver" and geo["stations"] == 5
    # Five chambers: the drum turns a fifth of a turn a shot.
    phi = np.interp(a.shot_times, a.rotary["time"], a.rotary["phi"])
    assert np.diff(phi).mean() == pytest.approx(2 * math.pi / 5, rel=0.02)


def test_burst_ends_when_the_belt_does():
    a = burst(M134, shots=30, rounds=12)
    assert a.shots == 12 and a.rounds_left == 0 and a.status == "empty"


def test_cam():
    ang = rotary.cam_angles(load(M134))
    stroke = 0.08
    assert rotary.cam(0.1, ang, stroke)[0] == 0.0
    assert rotary.cam(math.pi + 0.1, ang, stroke)[0] == pytest.approx(stroke)
    assert rotary.cam(2 * math.pi - 0.1, ang, stroke)[0] == 0.0
    # Continuous through the legs.
    th = np.linspace(0, 2 * math.pi, 2000)
    s = np.array([rotary.cam(x, ang, stroke)[0] for x in th])
    assert np.abs(np.diff(s)).max() < 0.01 * stroke * 10


@pytest.mark.parametrize("change, message", [
    ({"feed__type": "double_stack"}, "belt or a linkless chute"),
    ({"action__rotary_drive": "gas", "action__starter_energy": 0.0}, "starter"),
    ({"action__barrels": 1}, "barrels"),
    ({"trigger__mode": "semi"}, "bursts"),
])
def test_validation(change, message):
    with pytest.raises(ValueError, match=message):
        load(M134, **change)


def test_linkless_only_feeds_a_rotary_gun():
    with pytest.raises(ValueError, match="linkless"):
        load(CONFIGS / "example_belt_fed.toml", feed__type="linkless")


def test_drive_sound_spans_the_burst():
    a = burst(M61, shots=20)
    fs = 8000.0
    start, wave = mechanical.rotary(fs, a.rotary, a.events, load(M61))
    assert start < 0                                 # it starts with the spin-up, before the first shot
    assert len(wave) / fs > a.shot_times[-1] - start  # and runs past the last
    assert np.isfinite(wave).all() and np.abs(wave).max() > 0
    gas = burst(GSH, shots=10)
    _, wave = mechanical.rotary(fs, gas.rotary, gas.events, load(GSH))
    assert np.abs(wave[: int(0.01 * fs)]).max() > 0   # the starter cartridge


def test_api_json():
    gun = load(M134)
    a = burst(M134, shots=10)
    out = api.action_to_json(a)
    rot = out["rotary"]
    assert rot["stations"] == 6 and len(rot["phi"]) == len(rot["time"]) > 10
    assert out["strokes"]["rotary"]["layout"] == "gatling"
    assert api.max_burst(gun) == rotary.MAX_BURST
    with pytest.raises(ValueError, match="burst"):
        api._burst_rounds({"burst": rotary.MAX_BURST + 1}, gun)
