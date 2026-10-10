"""Tank guns' autoloaders: the AZ and MZ carousels, the bustle conveyor and the oscillating turret's drums."""

import copy
import json
import tomllib
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pytest

from gun_sim import action, autoloader, fluid
from gun_sim.config import Gun
from gun_sim.sound import mechanical
from gun_sim.ui import api

CONFIGS = Path(__file__).resolve().parents[1] / "configs"
T90 = CONFIGS / "2a46m5_125_t90.toml"
T80 = CONFIGS / "2a46m1_125_t80.toml"
LECLERC = CONFIGS / "cn120_26_leclerc.toml"
TYPE90 = CONFIGS / "rh120_l44_type90.toml"
AMX13 = CONFIGS / "sa50_75_amx13.toml"
PRESETS = [T90, T80, LECLERC, TYPE90, AMX13]
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
    if path not in _shots:
        gun = load(path)
        _shots[path] = gun, fluid.simulate(gun, blowdown_time=BLOWDOWN)
    return _shots[path]


def cycle(path, rounds=None, **changes):
    """The action and autoloader cycle of a preset's shot, with its config changed (the shot is the preset's)."""
    gun, s = shot(path)
    if changes:
        gun = load(path, **changes)
    return gun, action.simulate(gun, s, rounds=rounds)


def stage(al, name):
    return next(st for st in al["stages"] if st["name"].startswith(name))


# ---------- the presets ----------

@pytest.mark.parametrize("path", PRESETS)
def test_presets_load_round_trip_and_load_the_next_round(path):
    gun = Gun.load(path)
    assert asdict(Gun.from_dict(asdict(gun))) == asdict(gun)
    _, r = cycle(path)
    al = r.autoloader
    assert r.status == "breech opened" and al["loaded"] and al["status"] == "loaded" and not al["warnings"]
    assert r.chambered and r.rounds_left == al["rounds_after"] == al["rounds_before"] - 1
    assert al["ready_time"] > r.open_time and al["seat_speed"] >= autoloader.SEAT_SPEED
    json.dumps(api.action_to_json(r))          # the UI gets all of it


def test_presets_hit_their_published_velocities():
    for path in (T90, T80):
        assert 1650 < shot(path)[1].muzzle_velocity < 1780
    assert 950 < shot(AMX13)[1].muzzle_velocity < 1050 and shot(AMX13)[1].peak_breech_pressure < 450e6


def test_cycle_times_are_the_mechanisms():
    times = {p.stem: cycle(p)[1].autoloader["ready_time"] for p in PRESETS}
    assert 6.5 < times["2a46m5_125_t90"] < 9.0          # the T-72's quoted 6.5 to 8 s
    assert 6.5 < times["2a46m1_125_t80"] < 8.0          # the T-80's quoted 7.1 s
    assert times["cn120_26_leclerc"] < times["rh120_l44_type90"] < times["2a46m5_125_t90"]
    assert times["sa50_75_amx13"] < times["cn120_26_leclerc"]


# ---------- the carousels ----------

def test_az_rams_the_projectile_then_raises_the_charge_tier_and_rams_it():
    _, r = cycle(T90)
    al = r.autoloader
    order = [st["name"] for st in al["stages"]]
    assert order.index("raise the cassette behind the breech") < order.index("ram the projectile") \
        < order.index("raise the charge's tier into line") < order.index("ram the charge") \
        < order.index("lower the empty cassette")
    # The gun comes to its loading angle and the carousel turns together, once the gun has run out.
    lay, turn = stage(al, "bring the gun"), stage(al, "turn the carousel")
    assert lay["start"] == turn["start"] == pytest.approx(r.battery_time, abs=1e-3)
    assert al["tracks"]["elevation"]["x"][-1] == pytest.approx(0.0) and max(al["tracks"]["elevation"]["x"]) == 3.0
    shut = next(e["time"] for e in al["events"] if e["name"] == "the block springs shut")
    assert shut > stage(al, "ram the charge")["start"] and al["tracks"]["block"]["x"][-1] == 0.0
    assert any("hatch" in e["name"] for e in al["events"])
    assert max(al["tracks"]["lift"]["x"]) == pytest.approx(al["geometry"]["lift"] + al["geometry"]["tier"])


def test_mz_is_hydraulic_swings_its_charge_tray_and_catches_the_stub():
    _, r = cycle(T80)
    al = r.autoloader
    assert al["drive"] == "hydraulic" and al["two_piece"]
    assert stage(al, "swing the charge tray into line")["end"] <= stage(al, "ram the projectile")["start"] + 1e-9
    names = [e["name"] for e in al["events"]]
    assert "the stub catcher takes the stub" in names and "the stub catcher drops the stub into the empty cassette" in names
    assert names.count("valve switches") >= 5


def test_carousel_turns_the_shorter_way_and_a_far_round_takes_longer():
    near = cycle(T90, feed__index_steps=1)[1].autoloader
    far = cycle(T90, feed__index_steps=11)[1].autoloader
    back = cycle(T90, feed__index_steps=20)[1].autoloader      # 2 the other way round
    assert far["ready_time"] > near["ready_time"] + 2
    assert stage(back, "turn the carousel")["name"].startswith("turn the carousel 2 positions")


def test_laying_the_gun_further_from_the_loading_angle_takes_longer():
    level = cycle(T90)[1].autoloader
    high = cycle(T90, feed__gun_elevation=15.0)[1].autoloader
    assert high["ready_time"] > level["ready_time"] + 4


# ---------- the bustle ----------

def test_bustle_opens_its_door_and_rams_a_unitary_round():
    _, r = cycle(LECLERC)
    al = r.autoloader
    assert not al["two_piece"] and al["drive"] == "electric"
    assert stage(al, "open the blast door")["start"] == stage(al, "run the conveyor")["start"]
    assert [st["piece"] for st in al["stages"] if st["name"].startswith("ram")] == ["round"]
    assert any(e["name"] == "the blast door shuts" for e in al["events"])
    assert "lift" not in [st["part"] for st in al["stages"]]


def test_electromechanical_bustle_is_slower_than_electric():
    elec = cycle(TYPE90, feed__drive="electric")[1].autoloader
    mech = cycle(TYPE90)[1].autoloader
    assert mech["drive"] == "electromechanical" and mech["ready_time"] > elec["ready_time"] + 0.5
    assert any(e["name"] == "clutch engages" for e in mech["events"])
    assert not any(e["name"] == "clutch engages" for e in elec["events"])
    # Laid at 2°, it comes down to its 0° loading angle and goes back up.
    x = mech["tracks"]["elevation"]["x"]
    assert x[0] == 2.0 and min(x) == pytest.approx(0.0) and max(x) == 2.0 and x[-1] == pytest.approx(2.0)


# ---------- the oscillating turret ----------

def test_oscillating_turret_loads_at_any_elevation_with_its_recoil_cocked_rammer():
    _, r = cycle(AMX13)
    al = r.autoloader
    assert al["load_angle"] is None and al["geometry"]["drums"] == 2 and al["geometry"]["per_drum"] == 6
    assert "elevation" not in [st["part"] for st in al["stages"]]
    names = [e["name"] for e in al["events"]]
    assert names.index("the round drops onto the loading tray") < names.index("the rammer's spring is let go")
    # Firing elevated changes nothing: the drums elevate with the gun.
    high = cycle(AMX13, feed__gun_elevation=12.0)[1].autoloader
    assert high["ready_time"] == pytest.approx(al["ready_time"], abs=0.01)


def test_short_recoil_leaves_the_oscillating_rammer_uncocked():
    gun, s = shot(AMX13)
    long = copy.deepcopy(gun)
    long.mount.stroke = 1.5          # the spring needs 60 % of a stroke the gun never comes near
    r = action.simulate(long, s)
    assert not r.autoloader["loaded"] and r.autoloader["status"] == "rammer not cocked"
    assert any("cocks the rammer" in w for w in r.warnings) and not r.chambered


# ---------- what goes wrong ----------

def test_a_weak_drive_stalls_the_lift():
    _, r = cycle(T90, feed__drive_power=10.0)
    al = r.autoloader
    assert not al["loaded"] and al["status"] == "stalled" and any("stalled" in w for w in al["warnings"])


def test_a_slow_rammer_does_not_seat_the_projectile():
    _, r = cycle(T90, feed__ram_speed=0.6)
    al = r.autoloader
    assert al["loaded"] and al["seat_speed"] < autoloader.SEAT_SPEED
    assert any("slide back out" in w for w in r.warnings)


def test_an_empty_autoloader_leaves_the_breech_open():
    _, r = cycle(T90, rounds=0)
    assert not r.autoloader["loaded"] and r.autoloader["status"] == "empty" and not r.chambered


def test_move_profile_respects_its_limits():
    m = autoloader._move(1.0, 50.0, 2000.0, 1.0, 4.0, resist=50.0 * 9.81)
    assert m["x"][-1] == pytest.approx(1.0) and m["v"].max() <= 1.0 + 1e-9 and m["v"][-1] == 0
    assert np.all(np.diff(m["v"]) / autoloader.DT <= 4.0 + 1e-6)
    assert autoloader._move(1.0, 50.0, 10.0, 1.0, 4.0, resist=50.0 * 9.81) is None   # too weak to lift it


@pytest.mark.parametrize("changes, message", [
    ({"action__type": "bolt", "shooter__stance": "shoulder"}, "sliding_wedge"),
    ({"feed__drive": "steam"}, "feed.drive"),
    ({"feed__ammunition": "three_piece"}, "feed.ammunition"),
    ({"feed__load_angle": 45.0}, "load_angle"),
    ({"feed__ram_speed": 50.0}, "ram_speed"),
])
def test_autoloader_validation(changes, message):
    with pytest.raises(ValueError, match=message):
        load(T90, **changes)


# ---------- the sound ----------

@pytest.mark.parametrize("path, drive", [(T90, "electromechanical"), (T80, "hydraulic"), (LECLERC, "electric"),
                                         (AMX13, "spring")])
def test_autoloader_is_heard_over_its_whole_cycle(path, drive):
    _, r = cycle(path)
    al = r.autoloader
    assert al["drive"] == drive
    fs = 48000
    t0, wave = mechanical.autoloader(fs, al)
    assert np.all(np.isfinite(wave)) and np.abs(wave).max() > 0
    assert t0 < al["stages"][0]["start"] and t0 + len(wave) / fs > al["ready_time"]
    # The block springing shut is one of the loudest things in it.
    shut = next(e["time"] for e in al["events"] if e["name"] == "the block springs shut")
    i = int((shut - t0) * fs)
    assert np.abs(wave[i:i + int(0.05 * fs)]).max() > 0.1 * np.abs(wave).max()
    if drive == "hydraulic":
        # The pump hums between the moves too.
        gap = (stage(al, "raise the cassette")["start"] + stage(al, "turn the carousel")["end"]) / 2
        j = int((gap - t0) * fs)
        assert np.abs(wave[j:j + 2000]).max() > 0
