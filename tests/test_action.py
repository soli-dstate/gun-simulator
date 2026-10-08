import math
from pathlib import Path

import pytest

from gun_sim import Gun, action, fluid, lumped

CONFIGS = Path(__file__).parent.parent / "configs"
RIFLE = CONFIGS / "example_rifle.toml"
GAS_RIFLE = CONFIGS / "example_gas_rifle.toml"
BLOWDOWN = 0.006


@pytest.fixture(scope="module")
def rifle_shot():
    gun = Gun.load(RIFLE)
    return fluid.simulate(gun, blowdown_time=BLOWDOWN)


@pytest.fixture(scope="module")
def gas_shot():
    gun = Gun.load(GAS_RIFLE)
    return fluid.simulate(gun, blowdown_time=BLOWDOWN)


def gun_momentum_at_end(gun, a):
    """Momentum of the gun and bolt at the end (no shooter): the bolt is home, so it moves with the gun."""
    return gun.action.gun_mass * a.recoil_velocity[-1]


def test_loads_integrate_to_the_recoil_impulse(rifle_shot):
    assert rifle_shot.loads.impulse == pytest.approx(rifle_shot.recoil_impulse, rel=1e-3)


def test_in_bore_impulse_is_projectile_plus_half_the_gas():
    """Momentum conservation: before exit the gun has given the projectile m v and the gas about omega v / 2."""
    gun = Gun.load(RIFLE)
    r = fluid.simulate(gun)
    m, omega, v = gun.projectile.mass, gun.propellant.charge_mass, r.muzzle_velocity
    gas_share = (r.recoil_impulse - m * v) / (omega * v)
    assert 0.4 < gas_share < 0.7


def test_lumped_and_fluid_recoil_agree(rifle_shot):
    gun = Gun.load(RIFLE)
    l = lumped.simulate(gun, blowdown_time=BLOWDOWN)
    assert l.loads.impulse == pytest.approx(l.recoil_impulse, rel=1e-3)
    assert l.recoil_impulse == pytest.approx(rifle_shot.recoil_impulse, rel=0.08)


def test_free_recoil_conserves_momentum(rifle_shot):
    gun = Gun.load(RIFLE)
    gun.shooter.stance = "free"
    a = action.simulate(gun, rifle_shot)
    assert a.free_recoil_velocity == pytest.approx(a.impulse / gun.action.gun_mass)
    assert gun_momentum_at_end(gun, a) == pytest.approx(a.impulse, rel=0.01)
    # Typical of a 4 kg rifle in this class: about 3 m/s and 15-20 J.
    assert 2 < a.free_recoil_velocity < 4
    assert 10 < a.free_recoil_energy < 25


def test_gas_action_conserves_momentum(gas_shot):
    """The piston, spring and impacts are internal: free, the whole gun ends with the shot's impulse."""
    gun = Gun.load(GAS_RIFLE)
    gun.shooter.stance = "free"
    a = action.simulate(gun, gas_shot)
    assert a.status == "cycled"
    assert gun_momentum_at_end(gun, a) == pytest.approx(a.impulse, rel=0.01)


def test_shoulder_stops_the_gun_and_brings_it_back(rifle_shot):
    gun = Gun.load(RIFLE)
    a = action.simulate(gun, rifle_shot)
    assert 5e-3 < a.max_recoil < 50e-3
    assert abs(a.recoil[-1]) < 0.2 * a.max_recoil
    assert a.peak_recoil_velocity < a.free_recoil_velocity  # the shooter's body adds mass
    assert a.peak_shoulder_force > 100


def test_muzzle_rise_comes_from_the_bore_height(rifle_shot):
    gun = Gun.load(RIFLE)
    gun.action.bore_height = 0.0
    assert abs(action.simulate(gun, rifle_shot).max_pitch) < 1e-9
    gun.action.bore_height = 0.03
    low = action.simulate(gun, rifle_shot).max_pitch
    gun.action.bore_height = 0.06
    high = action.simulate(gun, rifle_shot).max_pitch
    assert 0 < low < high
    assert math.degrees(low) < 5


def test_gas_action_cycles_in_order(gas_shot):
    gun = Gun.load(GAS_RIFLE)
    a = action.simulate(gun, gas_shot)
    assert a.status == "cycled", a.warnings
    assert not a.warnings
    t = {e["name"]: e["time"] for e in a.events}
    order = ["bolt unlocks", "case ejected", "bolt hits the rear stop", "strips the next round", "back in battery"]
    assert [t[name] for name in order] == sorted(t[name] for name in order)
    assert t["bolt unlocks"] > gas_shot.muzzle_time  # the port is uncovered first, then the carrier gets going
    assert 300 < a.cyclic_rate < 3000
    assert a.unlock_pressure < 20e6
    assert 3 < a.rear_speed < 10


def test_small_gas_port_short_strokes(gas_shot):
    gun = Gun.load(GAS_RIFLE)
    gun.solver.gas_port_2d = False  # the action model's own orifice, to test it alone
    gun.action.gas_port_diameter = 0.3e-3
    a = action.simulate(gun, gas_shot)
    assert a.status.startswith("failed")
    assert any("short stroke" in w for w in a.warnings)


def test_big_gas_port_batters(gas_shot):
    gun = Gun.load(GAS_RIFLE)
    gun.solver.gas_port_2d = False
    gun.action.gas_port_diameter = 3e-3
    a = action.simulate(gun, gas_shot)
    assert a.rear_speed > action.REAR_SPEED_WARNING
    assert any("battering" in w for w in a.warnings)


def test_light_blowback_bolt_lets_the_case_out_under_pressure(rifle_shot):
    gun = Gun.load(RIFLE)
    gun.action.type = "blowback"
    light = action.simulate(gun, rifle_shot)
    assert any("rupture" in w for w in light.warnings)
    ejected = lambda r: next(e["time"] for e in r.events if e["name"] == "case ejected")
    gun.action.gun_mass, gun.action.bolt_mass = 20.0, 8.0
    heavy = action.simulate(gun, rifle_shot)
    assert ejected(heavy) > ejected(light)  # a heavier bolt is slower to open


def test_short_recoil_unlocks_then_cycles(rifle_shot):
    gun = Gun.load(RIFLE)
    gun.action.type = "short_recoil"
    gun.shooter.stance = "free"
    a = action.simulate(gun, rifle_shot)
    names = [e["name"] for e in a.events]
    assert names[:2] == ["fires", "barrel stops and unlocks"]
    assert "back in battery" in names
    assert gun_momentum_at_end(gun, a) == pytest.approx(a.impulse, rel=0.01)


def test_manual_bolt_does_not_cycle(rifle_shot):
    a = action.simulate(Gun.load(RIFLE), rifle_shot)
    assert a.status == "manual"
    assert [e["name"] for e in a.events] == ["fires"]
    assert a.bolt.max() == 0


def test_bad_action_rejected():
    gun = Gun.load(RIFLE)
    gun.action.type = "lever"
    with pytest.raises(ValueError, match="action.type"):
        gun.validate()
    gun = Gun.load(RIFLE)
    gun.action.bolt_mass = 5.0
    with pytest.raises(ValueError, match="heavier"):
        gun.validate()
    gun = Gun.load(RIFLE)
    gun.action.gas_port_position = 1.0
    with pytest.raises(ValueError, match="inside the barrel"):
        gun.validate()


def test_burst_builds_up_recoil_and_climb(gas_shot):
    gun = Gun.load(GAS_RIFLE)
    one = action.simulate(gun, gas_shot)
    burst = action.simulate(gun, gas_shot, shots=4)
    assert burst.shots == 4 and burst.status == "cycled"
    gaps = [b - a for a, b in zip(burst.shot_times, burst.shot_times[1:])]
    assert all(g > one.cycle_time for g in gaps)  # each fires after the bolt is home again
    assert burst.max_pitch > 2 * one.max_pitch      # muzzle climb
    assert 300 < burst.cyclic_rate < 3000
    assert [e["shot"] for e in burst.events if e["name"] == "fires"] == [1, 2, 3, 4]


def test_burst_conserves_momentum(gas_shot):
    gun = Gun.load(GAS_RIFLE)
    gun.shooter.stance = "free"
    a = action.simulate(gun, gas_shot, shots=3)
    assert a.gun_mass * a.recoil_velocity[-1] == pytest.approx(3 * a.impulse, rel=0.02)


def test_manual_bolt_fires_one_shot(rifle_shot):
    assert action.simulate(Gun.load(RIFLE), rifle_shot, shots=5).shots == 1


def test_gas_port_discharge_coefficient_from_2d(gas_shot):
    gun = Gun.load(GAS_RIFLE)
    a = action.simulate(gun, gas_shot)
    assert a.port_cd_2d and 0.1 < a.port_cd < 1.2
