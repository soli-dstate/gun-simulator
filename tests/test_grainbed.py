"""Two-phase grain bed: grains that move, drag, flame spread from the primer."""

from pathlib import Path

import numpy as np
import pytest

from gun_sim import Gun, fluid

RIFLE = Path(__file__).parent.parent / "configs" / "example_rifle.toml"


def two_phase(shape="cylinder", **ignition):
    gun = Gun.load(RIFLE)
    gun.solver.two_phase = True
    gun.barrel.chamber_shape = shape
    for key, value in ignition.items():
        setattr(gun.ignition, key, value)
    return gun


@pytest.fixture(scope="module")
def shots():
    return {shape: fluid.simulate(two_phase(shape)) for shape in ("cylinder", "case")}


@pytest.mark.parametrize("shape", ["cylinder", "case"])
def test_unlit_bed_in_still_gas_stays_put(shape):
    """No primer: cold gas and grains at rest stay at rest, even past the case's shoulder."""
    gun = two_phase(shape, pressure=0.0)
    gun.solver.max_time = 1e-4
    r = fluid.simulate(gun)
    assert not r.left_muzzle
    assert r.breech_pressure == pytest.approx(fluid.ATMOSPHERE, rel=1e-9)
    assert r.grain_bed["lit"].max() == 0.0
    for _, _, alpha, u_g in r.grain_bed["profiles"]:
        assert np.abs(u_g).max() < 1e-9   # m/s: round-off only


@pytest.mark.parametrize("shape", ["cylinder", "case"])
def test_flame_spreads_from_the_primer(shots, shape):
    bed = shots[shape].grain_bed
    lit = bed["lit_time"]
    assert np.nanargmin(lit) == 0                     # the flash hole lights first
    assert np.all(np.diff(lit[::10]) > 0)             # and the flame runs forwards through the bed
    assert 2e-5 < bed["flame_spread_time"] < 1e-3     # tens to hundreds of microseconds
    speed = bed["cell_x"][-1] / bed["flame_spread_time"]
    assert 50 < speed < 3000                          # m/s


def test_two_phase_shot_is_close_to_the_simple_one(shots):
    for shape, r in shots.items():
        gun = Gun.load(RIFLE)
        gun.barrel.chamber_shape = shape
        simple = fluid.simulate(gun)
        assert r.left_muzzle and r.burnt_at_muzzle > 0.95
        assert r.muzzle_velocity == pytest.approx(simple.muzzle_velocity, rel=0.03)
        assert r.peak_breech_pressure == pytest.approx(simple.peak_breech_pressure, rel=0.1)
        assert r.muzzle_time > simple.muzzle_time     # the flame takes time to spread


def test_grains_are_carried_forwards(shots):
    _, _, alpha, u_g = shots["cylinder"].grain_bed["profiles"][2]
    carried = alpha > 0.01
    assert np.average(u_g[carried], weights=alpha[carried]) > 50   # m/s, behind the projectile
    assert alpha[-1] < 0.01   # but they lag it: the gas right behind the base is clear of grains


def test_momentum_is_kept(shots):
    """The gun's impulse is the projectile's momentum and the gas's (and grains'), about half the charge's."""
    gun = Gun.load(RIFLE)
    r = shots["cylinder"]
    m, omega, v = gun.projectile.mass, gun.propellant.charge_mass, r.muzzle_velocity
    assert 0.4 < (r.recoil_impulse - m * v) / (omega * v) < 0.7


def test_weaker_primer_and_harder_powder_light_later():
    def spread(**ignition):
        return fluid.simulate(two_phase(**ignition)).grain_bed["flame_spread_time"]
    base = spread()
    assert spread(pressure=2e6) > 1.2 * base
    assert spread(grain_ignition_temperature=600.0) > 1.1 * base


def test_two_phase_grid_convergence():
    gun = two_phase()
    gun.solver.cells = 50
    coarse = fluid.simulate(gun)
    gun.solver.cells = 200
    fine = fluid.simulate(gun)
    assert coarse.muzzle_velocity == pytest.approx(fine.muzzle_velocity, rel=0.005)
    assert coarse.peak_breech_pressure == pytest.approx(fine.peak_breech_pressure, rel=0.02)


def test_blowdown_blows_out_a_little_unburnt_powder():
    r = fluid.simulate(two_phase(), blowdown_time=0.006)
    assert 0 < r.grain_bed["ejected"] < 0.01 * Gun.load(RIFLE).propellant.charge_mass
    assert np.isfinite(r.recoil_impulse) and r.muzzle_flow.ejected_mass > 0


def test_bad_ignition_rejected():
    gun = two_phase()
    gun.ignition.duration = 0.0
    with pytest.raises(ValueError, match="duration"):
        gun.validate()
    gun = two_phase()
    gun.ignition.grain_ignition_temperature = 200.0
    with pytest.raises(ValueError, match="grain_ignition_temperature"):
        gun.validate()
