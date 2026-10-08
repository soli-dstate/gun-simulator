"""Muzzle flash and smoke: stretched 2D grids, afterburning, and the plume of a shot."""

from pathlib import Path

import numpy as np
import pytest

from gun_sim import Gun, fluid, plume
from gun_sim.axisym import Afterburn, Axisymmetric
from gun_sim.propellants import combustibles

CONFIGS = Path(__file__).parent.parent / "configs"
RIFLE = CONFIGS / "example_rifle.toml"
SUPPRESSED = CONFIGS / "example_suppressed.toml"
BLOWDOWN = 0.006


def test_stretched_edges_are_fine_in_the_middle_and_grow_outwards():
    h = 1e-3
    e = plume.edges(-0.05, -0.01, 0.02, 0.3, h)
    d = np.diff(e)
    fine = (e[:-1] >= -0.01 - 1e-9) & (e[1:] <= 0.02 + 1e-9)
    assert np.allclose(d[fine], h)
    assert e[0] <= -0.05 and e[-1] >= 0.3
    assert d.max() == pytest.approx(plume.COARSEST * h)
    assert np.all(d[1:] / d[:-1] <= plume.GROWTH + 1e-9)


def test_gas_at_rest_stays_at_rest_on_a_stretched_grid():
    xe = plume.edges(-0.03, -0.01, 0.01, 0.06, 1e-3)
    re = plume.edges(0.0, 0.0, 0.008, 0.04, 1e-3)
    solid = np.zeros((len(xe) - 1, len(re) - 1), bool)
    ox, orr = np.ones((solid.shape[0] + 1, solid.shape[1])), np.ones((solid.shape[0], solid.shape[1] + 1))
    s = Axisymmetric(1e-3, 0.0, solid, ox, orr, 330.0, 1.24, 101325.0, 288.15, x_edges=xe, r_edges=re,
                     afterburn=Afterburn(*combustibles(None)))
    for _ in range(40):
        s.step(1.0)
    assert np.abs(s.pressure() - 101325.0).max() < 1e-3 * 101325.0
    assert s.burnt == 0.0


def test_afterburning_releases_the_fuels_heat_and_stops_at_the_ceiling():
    fuel, heat, oxygen = combustibles("single_base")
    assert 0.3 < fuel < 0.5 and 1e7 < heat < 2e7
    solid = np.zeros((4, 4), bool)
    ox, orr = np.ones((5, 4)), np.ones((4, 5))
    ox[0] = ox[-1] = 0.0
    orr[:, -1] = 0.0
    a = Afterburn(fuel, heat, oxygen)
    s = Axisymmetric(1e-3, 0.0, solid, ox, orr, 330.0, 1.24, 101325.0, 288.15, wall_heat=False, afterburn=a)
    # Propellant gas mixed with air (a little oxygen to spare), hot enough to light: it
    # holds more heat than it takes to reach the ceiling.
    Y = 0.35
    s.U[4] = s.U[0] * Y
    s.U[5] = s.U[0] * Y * fuel
    cv = 287.05 / 0.4 * (1 - Y) + 330.0 / 0.24 * Y
    s.U[3] = s.U[0] * cv * 1100.0
    E0 = float(np.sum(s.U[3] * s.volume))
    for _ in range(200):
        s.step(2e-6)
    burnt_fuel, o2 = s.fuel_oxygen()
    T = s.temperature()
    released = float(np.sum(s.U[3] * s.volume)) - E0
    assert released == pytest.approx(s.burnt, rel=1e-3)
    # It burns until it reaches the ceiling, not beyond.
    assert T.max() == pytest.approx(a.ceiling, abs=30)
    assert np.all(burnt_fuel < Y * fuel)
    # Cold gas doesn't light.
    s2 = Axisymmetric(1e-3, 0.0, solid, ox, orr, 330.0, 1.24, 101325.0, 288.15, wall_heat=False, afterburn=a)
    s2.U[4] = s2.U[0] * Y
    s2.U[5] = s2.U[0] * Y * fuel
    for _ in range(200):
        s2.step(2e-6)
    assert s2.burnt < 1e-6 * s.burnt


def test_fluid_records_the_bore_gas_cooling_after_exit():
    gun = Gun.load(RIFLE)
    shot = fluid.simulate_cached(gun, blowdown_time=BLOWDOWN)
    t = np.array([t for t, _ in shot.bore_gas])
    T = np.array([temps for _, temps in shot.bore_gas])
    assert T.shape[1] == fluid.BORE_GAS_POINTS and np.all(np.diff(t) > 0)
    at_exit = T[np.searchsorted(t, shot.muzzle_time)].max()
    assert 1500 < at_exit < gun.propellant.force / gun.propellant.gas_constant
    assert T[-1].max() < 0.7 * at_exit   # it expands and cools as the bore empties


@pytest.fixture(scope="module")
def plumes():
    out = {}
    for name, path, device in (("bare", RIFLE, None), ("brake", RIFLE, "brake"), ("suppressed", SUPPRESSED, None)):
        gun = Gun.load(path)
        if device:
            gun.muzzle_device.type = device
        gun.solver.plume_time = 0.0012
        shot = fluid.simulate_cached(gun, blowdown_time=BLOWDOWN)
        out[name] = plume.simulate(gun, shot)
    return out


def test_bare_muzzle_has_a_secondary_flash(plumes):
    r = plumes["bare"]
    assert r.afterburn > 1e3                   # the fuel-rich gas burns in the air
    assert 2000 < r.peak_temperature < 3200
    assert r.cloud["x"] > 0.05 and r.cloud["velocity"] > 0   # the cloud is thrown forwards
    assert r.escaped < 0.02                    # and stays on the grid


def test_suppressor_holds_back_and_dims_the_flash(plumes):
    bare, can = plumes["bare"], plumes["suppressed"]
    assert can.glow.max() < 0.05 * bare.glow.max()
    assert can.afterburn < 0.1 * bare.afterburn   # starved of oxygen in the can
    assert can.trickle["mass"] > 2 * bare.trickle["mass"]
    assert can.trickle["tau"] > bare.trickle["tau"]


def test_brake_throws_the_gas_sideways(plumes):
    bare, brake = plumes["bare"], plumes["brake"]
    side = lambda r: r.extent[-1][2] / max(r.extent[-1][1], 1e-9)
    assert side(brake) > 1.5 * side(bare)
    assert brake.cloud["x"] < 0.5 * bare.cloud["x"]


def test_flash_hider_removes_the_shock_reheat_and_trims_the_fireball():
    """Bare, the jet's Mach disk shocks the gas hotter than burning can make it (the intermediate
    flash). In a flash hider the jet expands first, so nothing gets hotter than burning makes it,
    and less of the gas reignites. (4 cells across the bore: at 2 the Mach disk is barely resolved.)"""
    out = {}
    for kind in ("none", "flash_hider"):
        gun = Gun.load(RIFLE)
        gun.muzzle_device.type = kind
        gun.solver.plume_resolution = 4
        gun.solver.plume_time = 0.0012
        out[kind] = plume.simulate(gun, fluid.simulate_cached(gun, blowdown_time=BLOWDOWN))
    ceiling = Afterburn(*combustibles(None)).ceiling
    bare, hider = out["none"], out["flash_hider"]
    assert bare.peak_temperature > ceiling + 50
    assert hider.peak_temperature < ceiling + 20
    assert hider.afterburn < 0.97 * bare.afterburn
    assert hider.glow.max() < bare.glow.max()


def test_plume_json(plumes):
    r = plumes["bare"]
    gun = Gun.load(RIFLE)
    shot = fluid.simulate_cached(gun, blowdown_time=BLOWDOWN)
    d = plume.to_json(r, shot)
    import base64
    cells = base64.b64decode(d["frames"])
    assert len(cells) == d["nx"] * d["nr"] * d["layers"] * 2
    assert d["layers"] == len(d["times"]) + 1
    assert len(d["x_edges"]) == d["nx"] + 1 and len(d["r_edges"]) == d["nr"] + 1
    assert len(d["bore"]["t"]) == len(d["bore"]["T"]) > 50
