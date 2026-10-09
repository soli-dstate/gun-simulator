"""Handguns: the presets, triggers (single action, DA/SA, double action only, striker), semi-automatic
strings, the revolver's cylinder and its gap, the hands stance, and their sounds."""

import copy
import math
import tomllib
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pytest

from gun_sim import action, feed, fluid, lumped, revolver
from gun_sim.config import Gun
from gun_sim.sound import SoundSettings, mechanical, synthesize

CONFIGS = Path(__file__).resolve().parents[1] / "configs"
PRESETS = {name: CONFIGS / f"{name}.toml" for name in ("colt_1911", "beretta_m9", "glock_17", "colt_anaconda", "colt_saa")}
BLOWDOWN = 0.025


def load(name, **changes):
    with open(PRESETS[name], "rb") as f:
        data = tomllib.load(f)
    for key, value in changes.items():
        section, field = key.split("__")
        data.setdefault(section, {})[field] = value
    return Gun.from_dict(data)


@pytest.fixture(scope="module")
def shots():
    """Each preset and its fluid shot, solved once."""
    out = {}
    for name in PRESETS:
        gun = load(name)
        out[name] = (gun, fluid.simulate(gun, blowdown_time=BLOWDOWN))
    return out


def names(result):
    return [e["name"] for e in result.events]


def times(result, name):
    return [e["time"] for e in result.events if e["name"] == name]


# ---------- presets ----------

@pytest.mark.parametrize("name", PRESETS)
def test_presets_load_and_round_trip(name):
    gun = Gun.load(PRESETS[name])
    assert asdict(Gun.from_dict(asdict(gun))) == asdict(gun)


@pytest.mark.parametrize("name, velocity, pressure", [
    ("colt_1911", (243, 265), (80e6, 145e6)),       # M1911 ball, 830 ft/s; .45 ACP's 145 MPa maximum
    ("beretta_m9", (366, 396), (190e6, 252e6)),     # M882, 1,250 ft/s
    ("glock_17", (340, 370), (190e6, 252e6)),
    ("colt_anaconda", (375, 415), (200e6, 260e6)),  # .44 Magnum's 248 MPa
    ("colt_saa", (250, 275), (60e6, 97e6)),         # .45 Colt's 97 MPa
])
def test_presets_hit_their_published_velocities(shots, name, velocity, pressure):
    shot = shots[name][1]
    assert velocity[0] < shot.muzzle_velocity < velocity[1]
    assert pressure[0] < shot.peak_breech_pressure < pressure[1]


# ---------- semi-automatic pistols ----------

@pytest.mark.parametrize("name", ["colt_1911", "beretta_m9", "glock_17"])
def test_pistols_fire_a_string_a_pull_a_shot(shots, name):
    gun, shot = shots[name]
    r = action.simulate(gun, shot, shots=3)
    assert r.status == "cycled" and r.shots == 3 and r.semi, r.warnings
    cap = feed.capacity(gun)
    assert r.rounds == [cap, cap - 1, cap - 2] and r.chambered
    # Each shot is the shooter's: a pull trigger.split after the last, once the slide is home.
    assert names(r).count("trigger pulled") == 2
    gaps = np.diff(r.shot_times)
    assert np.all(gaps > gun.trigger.split) and np.all(gaps < gun.trigger.split + 0.01)
    assert r.cyclic_rate == pytest.approx(60 / gaps.mean())
    # The barrel unlocks after the bullet has gone, and the slide comes home well within the split.
    assert times(r, "barrel stops and unlocks")[0] > shot.muzzle_time
    assert r.cycle_time < 0.05 and not r.warnings
    # One shot of a semi-automatic has no cyclic rate.
    assert action.simulate(gun, shot).cyclic_rate is None


def test_hands_take_the_recoil_and_a_higher_bore_flips_more(shots):
    gun, shot = shots["colt_1911"]
    r = action.simulate(gun, shot)
    assert r.stance == "hands" and 5e-3 < r.max_recoil < 40e-3
    assert 3 < math.degrees(r.max_pitch) < 25 and 100 < r.peak_shoulder_force < 600
    high = copy.deepcopy(gun)
    high.action.bore_height = 0.05
    assert action.simulate(high, shot).max_pitch > 1.3 * r.max_pitch


def test_single_action_hammer_is_cocked_by_the_slide(shots):
    gun, shot = shots["colt_1911"]
    r = action.simulate(gun, shot, shots=2)
    order = names(r)
    assert order.index("hammer cocked") < order.index("back in battery") < order.index("trigger pulled") \
        < order.index("hammer strikes the firing pin")
    assert r.trigger == "single_action" and r.trigger_work == pytest.approx(gun.trigger.pull * gun.trigger.travel)


def test_double_action_first_pull_then_single_action(shots):
    gun, shot = shots["beretta_m9"]
    r = action.simulate(gun, shot, shots=2)
    t = gun.trigger
    assert r.trigger_work == pytest.approx(t.da_pull * t.da_travel)
    assert r.follow_up_work == pytest.approx(t.pull * t.travel)
    # The slide left the hammer cocked: the second pull only lets it go.
    assert "hammer cocked" in names(r) and "hammer released" not in names(r)


def test_double_action_only_cocks_the_hammer_every_pull(shots):
    gun, shot = shots["beretta_m9"]
    dao = copy.deepcopy(gun)
    dao.trigger.type = "double_action_only"
    r = action.simulate(dao, shot, shots=3)
    assert r.status == "cycled" and r.shots == 3, r.warnings
    # Nothing leaves the hammer on the sear: each pull draws it back over pull_time and lets it go.
    assert "hammer cocked" not in names(r)
    pulls, releases = times(r, "trigger pulled"), times(r, "hammer released")
    assert len(pulls) == len(releases) == 2
    assert np.allclose(np.subtract(releases, pulls), dao.trigger.pull_time, atol=2 * action.QUIET_DT)
    assert r.follow_up_work == pytest.approx(dao.trigger.da_pull * dao.trigger.da_travel)
    # The pull ends (and lets the hammer go) split after the last shot; the shot follows a lock time later.
    assert np.diff(r.shot_times) == pytest.approx([dao.trigger.split + r.lock_time] * 2, abs=5e-4)


def test_striker_strike_and_lock_time(shots):
    gun, shot = shots["glock_17"]
    a = gun.action
    t, energy = action.striker_fall(gun)
    stored = a.striker_spring_preload * a.striker_travel + 0.5 * a.striker_spring_rate * a.striker_travel**2
    assert energy == pytest.approx(stored, rel=1e-3) and energy > gun.ignition.strike_energy
    assert 0.5e-3 < t < 4e-3
    r = action.simulate(gun, shot, shots=2)
    assert r.hammer is None and r.striker_energy == pytest.approx(energy)
    assert r.lock_time == pytest.approx(t + action.PRIMER_DELAY)
    release = times(r, "striker released")[0]
    assert r.shot_times[1] == pytest.approx(release + r.lock_time, abs=3 * action.SLOW_DT)


def test_slide_cocks_the_striker_as_it_closes(shots):
    gun, shot = shots["glock_17"]
    none = copy.deepcopy(gun)
    none.action.striker_precock = 0.0
    with_it, without = action.simulate(gun, shot), action.simulate(none, shot)
    # Compressing the striker spring over the last few mm slows the slide into battery.
    battery = lambda r: times(r, "back in battery")[0]
    assert battery(with_it) > battery(without)
    assert next(e["speed"] for e in with_it.events if e["name"] == "back in battery") < \
        next(e["speed"] for e in without.events if e["name"] == "back in battery")


def test_weak_striker_spring_is_a_light_strike(shots):
    gun, shot = shots["glock_17"]
    weak = copy.deepcopy(gun)
    weak.action.striker_spring_preload, weak.action.striker_spring_rate = 1.0, 200.0
    r = action.simulate(weak, shot, shots=3)
    assert r.status == "light strike" and r.shots == 1
    assert any("striker" in w and "light strike" in w for w in r.warnings)


def test_magazine_rakes_into_the_grip_not_the_physics(shots):
    # The magazine's rake is the 3D view's; the feed geometry is the same as a rifle's.
    gun = shots["colt_1911"][0]
    geo = feed.geometry(gun)
    assert geo["drop"] < 0 and not feed.check(geo)["jam"]


# ---------- revolvers ----------

def test_revolver_cylinder_geometry():
    gun = load("colt_anaconda")
    n, r = feed.chambers(gun), revolver.cylinder_radius(gun)
    assert n == 6 and feed.capacity(gun) == 5
    # Neighbouring rims clear each other with a web of steel between.
    assert 2 * r * math.sin(math.pi / n) == pytest.approx(gun.case.rim_diameter + revolver.WEB)
    assert revolver.gap_travel(gun) == pytest.approx(gun.barrel.cylinder_length - gun.seat)
    assert revolver.gap_area(gun) == pytest.approx(math.pi * gun.barrel.bore_diameter * 0.15e-3)
    full, empty = revolver.cylinder_inertia(gun, 6), revolver.cylinder_inertia(gun, 0)
    assert full - empty == pytest.approx(6 * feed.round_mass(gun) * r * r)


@pytest.mark.parametrize("name", ["colt_anaconda", "colt_saa"])
def test_revolver_fires_turning_the_cylinder_between_shots(shots, name):
    gun, shot = shots[name]
    r = action.simulate(gun, shot, shots=3)
    assert r.kind == "revolver" and r.status == "fired" and r.shots == 3, r.warnings
    assert r.rounds == [5, 4, 3] and r.rounds_left == 3 and r.chambered
    assert r.bolt_max_travel == 0 and r.cylinder is not None
    assert r.cylinder[-1] == pytest.approx(2) and np.all(np.diff(r.cylinder) >= -1e-12)
    order = names(r)
    first = "trigger pulled" if gun.trigger.type == "double_action" else "hammer cocked by the thumb"
    assert order.count(first) == order.count("cylinder locks") == order.count("hammer released") == 2
    assert order.index(first) < order.index("cylinder locks") < order.index("hammer released") \
        < order.index("hammer strikes the firing pin")
    # The cylinder spins onto its stop at the hand's speed.
    span = revolver.INDEX_END - revolver.INDEX_START
    assert r.cylinder_lock_speed == pytest.approx(2 * math.pi / 6 / (span * gun.trigger.pull_time))
    assert 0 < r.cylinder_lock_energy < 0.1
    assert np.diff(r.shot_times) == pytest.approx([gun.trigger.split + r.lock_time] * 2, abs=5e-4)
    # Nothing is ejected: the cases stay in their chambers.
    assert "case ejected" not in order


def test_revolver_runs_dry_on_a_fired_case(shots):
    gun, shot = shots["colt_anaconda"]
    r = action.simulate(gun, shot, shots=4, rounds=1)
    assert r.shots == 2 and r.status == "empty" and not r.chambered
    assert "the hammer falls on a fired case" in names(r)
    assert any("ran dry" in w for w in r.warnings)


def test_quicker_double_action_spins_the_cylinder_harder(shots):
    gun, shot = shots["colt_anaconda"]
    quick = copy.deepcopy(gun)
    quick.trigger.pull_time = gun.trigger.pull_time / 2
    slow, fast = action.simulate(gun, shot, shots=2), action.simulate(quick, shot, shots=2)
    assert fast.cylinder_lock_energy == pytest.approx(4 * slow.cylinder_lock_energy, rel=1e-6)


def test_gap_leaks_gas_once_the_bullet_is_out_of_the_cylinder(shots):
    gun, shot = shots["colt_anaconda"]
    gap = shot.gap_flow
    assert gap is not None and 0.02 < gap["mass"] / gun.propellant.charge_mass < 0.2
    opened = np.interp(gap["t"][0], shot.time, shot.travel)
    assert opened >= revolver.gap_travel(gun) - 2e-3
    sealed = copy.deepcopy(gun)
    sealed.barrel.cylinder_gap = 0.0
    tight = fluid.simulate(sealed)
    assert tight.gap_flow is None and tight.muzzle_velocity > shot.muzzle_velocity + 3
    # The lumped model loses about as much.
    lp = lumped.simulate(gun)
    assert lp.gap_flow is not None and 0.4 < lp.gap_flow["mass"] / gap["mass"] < 1.6
    assert lumped.simulate(sealed).muzzle_velocity > lp.muzzle_velocity


def test_wider_gap_loses_more(shots):
    gun = load("colt_saa")
    wide = copy.deepcopy(gun)
    wide.barrel.cylinder_gap = 0.4e-3
    a, b = lumped.simulate(gun), lumped.simulate(wide)
    assert b.gap_flow["mass"] > 1.5 * a.gap_flow["mass"] and b.muzzle_velocity < a.muzzle_velocity


# ---------- sounds ----------

def test_handgun_mechanical_sounds(shots):
    gun, shot = shots["glock_17"]
    which = {i["name"] for i in mechanical.impacts(action.simulate(gun, shot), gun)}
    assert "striker falls" in which and "hammer falls" not in which and "case lands" in which
    gun, shot = shots["colt_saa"]
    impacts = mechanical.impacts(action.simulate(gun, shot), gun)
    which = {i["name"]: i for i in impacts}
    assert "hammer falls" in which and "cylinder locks" in which and "case lands" not in which
    assert which["cylinder locks"]["time"] < which["hammer falls"]["time"] < 0


def test_revolver_sound_has_a_gap_blast():
    gun = load("colt_anaconda")
    snd = synthesize(gun, SoundSettings.from_dict({"preset": "shooter", "blast_cells": 300}))
    kinds = {m["name"]: m["kind"] for m in snd.stems}
    assert kinds["cylinder gap blast"] == "gap" and kinds["action: cylinder locks"] == "action"
    gap = max(e["peak_db"] for e in snd.events if e["name"].startswith("cylinder gap"))
    blast = max(e["peak_db"] for e in snd.events if e["name"].startswith("muzzle blast"))
    # Beside the shooter's hands it is loud, though the muzzle's is louder.
    assert 120 < gap < blast
    assert snd.stats["gap_gas"] > 0


# ---------- validation ----------

@pytest.mark.parametrize("name, changes, message", [
    ("colt_anaconda", {"feed__type": "double_stack"}, "cylinder"),
    ("colt_1911", {"feed__type": "cylinder"}, "cylinder"),
    ("colt_1911", {"barrel__cylinder_gap": 0.15e-3}, "cylinder_gap"),
    ("colt_anaconda", {"trigger__type": "striker"}, "hammer"),
    ("colt_anaconda", {"trigger__split": 0.1}, "split"),
    ("colt_anaconda", {"barrel__cylinder_length": 0.03}, "cylinder_length"),
    ("glock_17", {"action__hammer": True}, "striker"),
    ("colt_1911", {"trigger__type": "double_action_only", "trigger__split": 0.05}, "split"),
    ("colt_1911", {"trigger__mode": "burst"}, "trigger.mode"),
    ("colt_1911", {"action__locking": "toggle"}, "locking"),
    ("colt_1911", {"ignition__strike_energy": 5.0}, "strike_energy"),
])
def test_handgun_validation(name, changes, message):
    with pytest.raises(ValueError, match=message):
        load(name, **changes)
