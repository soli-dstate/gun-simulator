"""The chain gun, the sliding-wedge breech on its recoil system, the bore evacuator, APFSDS and the presets."""

import copy
import math
import tomllib
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pytest

from gun_sim import action, evacuator, exterior, feed, fluid
from gun_sim.config import Gun, Mount
from gun_sim.sound import mechanical

CONFIGS = Path(__file__).resolve().parents[1] / "configs"
MK44 = CONFIGS / "mk44_bushmaster_ii.toml"
RH120 = CONFIGS / "rh120_l55.toml"
BLOWDOWN = 0.025


def load(path, **changes):
    with open(path, "rb") as f:
        data = tomllib.load(f)
    for key, value in changes.items():
        section, name = key.split("__")
        data.setdefault(section, {})[name] = value
    return Gun.from_dict(data)


@pytest.fixture(scope="module")
def mk44():
    gun = load(MK44)
    return gun, fluid.simulate(gun, blowdown_time=BLOWDOWN)


@pytest.fixture(scope="module")
def rh120():
    gun = load(RH120)
    return gun, fluid.simulate(gun, blowdown_time=BLOWDOWN)


def names(result):
    return [e["name"] for e in result.events]


def first(result, name):
    return next(e["time"] for e in result.events if e["name"] == name)


# ---------- presets ----------

@pytest.mark.parametrize("path", [MK44, RH120])
def test_presets_load_and_round_trip(path):
    gun = Gun.load(path)
    again = Gun.from_dict(asdict(gun))
    assert asdict(again) == asdict(gun)


def test_presets_hit_their_published_velocities(mk44, rh120):
    assert 1040 < mk44[1].muzzle_velocity < 1120 and 350e6 < mk44[1].peak_breech_pressure < 450e6
    assert 1700 < rh120[1].muzzle_velocity < 1800 and 550e6 < rh120[1].peak_breech_pressure < 650e6


# ---------- the mount's recoil system ----------

def test_buffer_force_goes_as_the_square_of_speed_and_its_orifice_closes():
    m = Mount(stroke=0.3, buffer_area=6e-3, buffer_orifice=2e-4, buffer_orifice_end=2e-5)
    slow, fast = -action.mount_force(m, 0.0, 1.0), -action.mount_force(m, 0.0, 2.0)
    assert fast == pytest.approx(4 * slow)
    # Half way along, the throttling rod has closed the orifice: more force at the same speed.
    assert -action.mount_force(m, 0.15, 1.0) > 3 * slow
    # Running out it brakes the other way.
    assert action.mount_force(m, 0.1, -1.0) > 0


def test_recuperator_stiffens_as_it_is_compressed_and_counter_buffer_cushions():
    m = Mount(stroke=0.3, recuperator_pressure=5e6, recuperator_volume=8e-3, recuperator_area=4e-3)
    assert -action.mount_force(m, 0.0, 0.0) == pytest.approx(5e6 * 4e-3)
    assert -action.mount_force(m, 0.3, 0.0) > 1.2 * 5e6 * 4e-3
    c = Mount(stroke=0.3, buffer_area=6e-3, buffer_orifice=2e-4, counter_buffer=0.03)
    assert action.buffer_orifice(c, 0.003, -1.0) == pytest.approx(0.1 * 2e-4)
    assert action.buffer_orifice(c, 0.2, -1.0) == pytest.approx(2e-4)


# ---------- the chain gun ----------

def test_chain_track_is_continuous_and_dwells_in_battery_and_at_the_back():
    gun = load(MK44)
    stroke = action.strokes(gun)["stroke"]
    track = action.chain_track(gun, stroke)
    q = np.linspace(0, track["perimeter"], 4001)
    s = np.array([action.track_at(track, v)[0] for v in q])
    ds = np.array([action.track_at(track, v)[1] for v in q])
    assert s.min() == 0 and s.max() == pytest.approx(stroke)
    assert np.max(np.abs(np.diff(s))) < 2 * (q[1] - q[0])            # no jumps
    mid = 0.5 * (ds[1:] + ds[:-1])
    assert np.allclose(np.diff(s) / np.diff(q), mid, atol=0.02)      # dS/dq is the slope
    assert action.track_at(track, 0.0)[:2] == (0.0, 0.0)             # locked at the firing point
    rear = track["rear_start"] + 0.5 * track["rear_length"]
    assert action.track_at(track, rear)[0] == pytest.approx(stroke) and action.track_at(track, rear)[3] == "rear"


def test_chain_gun_cycles_at_its_rate_and_unlocks_after_the_bore_has_blown_down(mk44):
    gun, shot = mk44
    r = action.simulate(gun, shot)
    assert r.status == "cycled" and r.chambered
    assert 180 < r.cyclic_rate < 215
    order = names(r)
    assert order.index("bolt unlocks") < order.index("case ejected") < order.index("strips the next round") \
        < order.index("back in battery") < order.index("the drive stops")
    # The dwell holds the breech locked until the bore is nearly empty.
    assert r.unlock_pressure < 5e6 and first(r, "bolt unlocks") > shot.muzzle_time + 0.01
    assert r.motor_peak_power == pytest.approx(gun.action.motor_power, rel=0.05)
    # The motor, not the shot, drives the bolt: the chain ends a lap round at the firing point.
    assert r.drive[-1] == pytest.approx(action.strokes(gun)["chain"]["perimeter"], rel=0.01)


def test_chain_gun_burst_counts_down_the_belt(mk44):
    gun, shot = mk44
    r = action.simulate(gun, shot, shots=4, rounds=20)
    assert r.shots == 4 and r.rounds == [20, 19, 18, 17] and r.rounds_left == 16
    gaps = np.diff(r.shot_times)
    assert np.all(gaps > 0.25) and np.all(gaps < 0.35)


def test_weak_motor_stalls_the_chain(mk44):
    gun, shot = mk44
    weak = copy.deepcopy(gun)
    weak.action.motor_power = 20.0
    r = action.simulate(weak, shot)
    assert r.status == "the drive stalled" and any("stalled" in w for w in r.warnings)


def test_belt_running_out_stops_the_chain_gun(mk44):
    gun, shot = mk44
    r = action.simulate(gun, shot, shots=3, rounds=1)
    assert r.shots == 2 and r.status == "empty" and "belt runs out" in names(r)


def test_soft_mount_takes_the_recoil(mk44):
    gun, shot = mk44
    r = action.simulate(gun, shot)
    assert r.stance == "mount" and 0.01 < r.max_recoil < gun.mount.stroke
    assert r.stop_speed is None and r.battery_time is not None and r.battery_time < 0.1
    # The adapter spreads the impulse: well under the force of a rigid mount.
    assert 20e3 < r.peak_shoulder_force < 80e3


# ---------- the sliding wedge on its recoil system ----------

def test_wedge_opens_as_the_gun_runs_out_and_throws_the_stub(rh120):
    gun, shot = rh120
    r = action.simulate(gun, shot)
    assert r.status == "breech opened"
    assert 0.25 < r.max_recoil < gun.mount.stroke and r.stop_speed is None
    assert 250e3 < r.peak_shoulder_force < 550e3
    assert 0.3 < r.battery_time < 1.0 and r.open_time == pytest.approx(r.battery_time, abs=0.02)
    order = names(r)
    assert order.index("gun at full recoil") < order.index("the opening cam turns the crank") \
        < order.index("block strikes the extractors") < order.index("case ejected")
    assert r.case_speed > 1.0
    assert r.bolt_max_travel == pytest.approx(r.strokes["stroke"])
    assert not r.chambered       # the loader rams the next round


def test_wedge_stays_shut_if_the_run_out_is_too_weak(rh120):
    gun, shot = rh120
    stiff = copy.deepcopy(gun)
    stiff.action.spring_preload = 40e3      # a closing spring the cam cannot overcome
    r = action.simulate(stiff, shot)
    assert r.status in ("breech part open", "breech did not open") and r.warnings


def test_weak_recuperator_leaves_the_gun_out_of_battery(rh120):
    gun, shot = rh120
    weak = copy.deepcopy(gun)
    weak.mount.recuperator_pressure = 0.5e6
    r = action.simulate(weak, shot)
    assert r.battery_time is None and any("did not run out" in w for w in r.warnings)


def test_without_its_buffer_the_gun_hits_the_recoil_stop(rh120):
    gun, shot = rh120
    bare = copy.deepcopy(gun)
    bare.mount.buffer_area = 0.0
    r = action.simulate(bare, shot)
    assert r.stop_speed is not None and any("recoil stop" in w for w in r.warnings)


def test_cannon_sounds_have_no_hammer_and_ring_low(rh120):
    gun, shot = rh120
    impacts = mechanical.impacts(action.simulate(gun, shot), gun)
    which = {i["name"]: i for i in impacts}
    assert "hammer falls" not in which and "block strikes the extractors" in which
    assert which["gun runs out into battery"]["modes"][0][0] < 300   # a 3.5 t gun rings low


# ---------- the bore evacuator ----------

def test_evacuator_charges_then_sweeps_the_bore_before_the_breech_opens(rh120):
    gun, shot = rh120
    r = action.simulate(gun, shot)
    ev = evacuator.simulate(gun, shot, r.open_time)
    assert 1e6 < ev["peak_pressure"] < shot.peak_breech_pressure
    assert ev["charge"] > 0.01 and ev["blow_end"] > r.open_time
    assert ev["clear"] and ev["open_flow"] > 5 and ev["sweep_time"] < 0.5
    late = evacuator.simulate(gun, shot, ev["blow_end"] + 1.0)
    assert late["clear"] is False


def test_no_evacuator_no_result(mk44):
    gun, shot = mk44
    assert evacuator.simulate(gun, shot) is None


# ---------- APFSDS, combustible case ----------

def test_apfsds_flies_its_rod_and_holds_its_speed(rh120):
    gun, shot = rh120
    assert gun.flight_mass == pytest.approx(4.9) and gun.flight_diameter == pytest.approx(0.022)
    p, c = gun.projectile, gun.case
    assert gun.seat == pytest.approx(c.overall_length - p.length + p.sabot_offset)
    assert exterior.ballistic_coefficient(gun) == pytest.approx(4.9 / 0.022**2)
    traj = exterior.trajectory(gun, shot.muzzle_velocity, zero_range=1000, sight_height=0.4, max_range=2000)
    loss = (shot.muzzle_velocity - traj.at(1000)["velocity"])
    assert 40 < loss < 90                    # m/s per km
    assert traj.at(1000)["energy"] == pytest.approx(0.5 * 4.9 * traj.at(1000)["velocity"] ** 2)
    assert traj.stability == 0.0             # fin-stabilised, smoothbore: no spin drift


def test_combustible_case_leaves_only_its_stub(rh120):
    gun = rh120[0]
    stub = feed.case_mass(gun)
    whole = copy.deepcopy(gun)
    whole.case.combustible = False
    assert 0.5 < stub < 5 and feed.case_mass(whole) > 3 * stub
    assert feed.round_mass(gun) == pytest.approx(gun.projectile.mass + gun.propellant.charge_mass + stub)


@pytest.mark.parametrize("changes, message", [
    ({"shooter__stance": "shoulder"}, "mount"),
    ({"projectile__penetrator_mass": 9.0}, "penetrator_mass"),
    ({"mount__recuperator_volume": 1e-3}, "recuperator"),
    ({"barrel__evacuator_position": 7.0}, "evacuator_position"),
])
def test_cannon_validation(changes, message):
    with pytest.raises(ValueError, match=message):
        load(RH120, **changes)


def test_chain_gun_needs_a_belt():
    with pytest.raises(ValueError, match="belt"):
        load(MK44, feed__type="double_stack")
