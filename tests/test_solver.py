"""Fluid solver: case-shaped chamber, HLLC/MUSCL scheme, wall losses and barrel heating."""

from pathlib import Path

import numpy as np
import pytest

from gun_sim import Gun, fluid, lumped
from gun_sim.chamber import ChamberProfile, case_cavity, chamber_profile

RIFLE = Path(__file__).parent.parent / "configs" / "example_rifle.toml"


@pytest.fixture
def gun():
    return Gun.load(RIFLE)


def test_cylinder_profile_matches_chamber_volume(gun):
    profile = chamber_profile(gun)
    assert profile.volume == pytest.approx(gun.barrel.chamber_volume)
    assert profile.length == pytest.approx(gun.chamber_length)
    assert profile.area_at(np.array([0.0, 1.0])) == pytest.approx([gun.barrel.bore_area] * 2)


def test_case_cavity_is_a_bottleneck(gun):
    x, r = case_cavity(gun)
    assert np.all(np.diff(x) >= 0)
    assert x[0] == pytest.approx(gun.case.head_thickness)
    assert x[-1] == pytest.approx(gun.case.length)
    body, neck = r.max(), r[-1]
    assert body > 1.3 * neck                                   # shoulder down to the neck
    assert neck == pytest.approx(gun.barrel.bore_diameter / 2, abs=0.02e-3)


def test_case_profile_volume_is_consistent(gun):
    profile = ChamberProfile.from_case(gun)
    # The example's powder space is a little under its 3.6 cm^3 chamber_volume.
    assert 2.8e-6 < profile.volume < 3.6e-6
    # volume_at integrates area_at, and continues at the bore's area past the base.
    x = np.linspace(0, profile.length, 2001)
    integral = np.sum(profile.area_at(0.5 * (x[:-1] + x[1:])) * np.diff(x))
    assert integral == pytest.approx(profile.volume, rel=1e-3)
    assert profile.volume_at(profile.length + 0.1) == pytest.approx(profile.volume + 0.1 * gun.barrel.bore_area)


def test_effective_chamber_volume(gun):
    assert gun.effective_chamber_volume == gun.barrel.chamber_volume
    gun.barrel.chamber_shape = "case"
    assert gun.effective_chamber_volume == pytest.approx(gun.powder_space)


def test_bad_chamber_shape_rejected(gun):
    gun.barrel.chamber_shape = "sphere"
    with pytest.raises(ValueError, match="chamber_shape"):
        gun.validate()


def test_closed_case_chamber_stays_at_rest(gun):
    """Uniform gas in a stepped duct must not move: the wall force balances the flux."""
    gun.barrel.chamber_shape = "case"
    gun.propellant.burn_rate_coeff = 0.0
    gun.projectile.shot_start_pressure = 1e12
    gun.solver.max_time = 1e-4
    result = fluid.simulate(gun)
    assert not result.left_muzzle
    assert result.breech_pressure == pytest.approx(gun.ignition.pressure, rel=1e-9)


def test_case_chamber_shot(gun):
    gun.barrel.chamber_shape = "case"
    f = fluid.simulate(gun)
    l = lumped.simulate(gun)
    assert f.left_muzzle and f.burnt_at_muzzle == pytest.approx(1.0, abs=0.01)
    assert f.muzzle_velocity == pytest.approx(l.muzzle_velocity, rel=0.05)
    # Smaller than the 3.6 cm^3 cylinder, so faster and at a higher pressure.
    cylinder = fluid.simulate(Gun.load(RIFLE))
    assert f.muzzle_velocity > cylinder.muzzle_velocity
    assert f.peak_breech_pressure > cylinder.peak_breech_pressure


def test_case_chamber_grid_convergence(gun):
    gun.barrel.chamber_shape = "case"
    gun.solver.cells = 50
    coarse = fluid.simulate(gun)
    gun.solver.cells = 200
    fine = fluid.simulate(gun)
    assert coarse.muzzle_velocity == pytest.approx(fine.muzzle_velocity, rel=0.01)


def test_second_order_scheme_converges_tightly(gun):
    """MUSCL + HLLC: 50 and 200 cells agree far better than first order did (1%)."""
    gun.solver.cells = 50
    coarse = fluid.simulate(gun)
    gun.solver.cells = 200
    fine = fluid.simulate(gun)
    assert coarse.muzzle_velocity == pytest.approx(fine.muzzle_velocity, rel=0.002)
    assert coarse.peak_breech_pressure == pytest.approx(fine.peak_breech_pressure, rel=0.01)


def test_wall_losses_slow_the_shot_and_heat_the_barrel(gun):
    plain = fluid.simulate(gun)
    assert not plain.heat_to_barrel
    gun.solver.wall_losses = True
    lossy = fluid.simulate(gun)
    assert 0.9 * plain.muzzle_velocity < lossy.muzzle_velocity < plain.muzzle_velocity
    chemical = gun.propellant.charge_mass * gun.propellant.force / (gun.propellant.gamma - 1)
    assert 0 < lossy.heat_to_barrel < 0.2 * chemical
    assert 0 < lossy.barrel_temperature_rise < 10       # K per shot, bulk
    assert 100 < lossy.bore_temperature_rise < 1500      # K at the throat surface
    # Blowdown keeps heating the bore after the projectile has gone.
    blown = fluid.simulate(gun, blowdown_time=5e-3)
    assert blown.heat_to_barrel > lossy.heat_to_barrel


def test_surface_temperature_of_constant_flux():
    """Constant flux q on a semi-infinite wall: dT = 2 q sqrt(t / (pi k rho c))."""
    t = np.linspace(1e-6, 1e-3, 1000)
    q = 1e8
    rise = fluid._surface_temperature_rise(t, np.full_like(t, q), [t[-1]])[0]
    k_rho_c = fluid.STEEL_CONDUCTIVITY * fluid.STEEL_DENSITY * fluid.STEEL_HEAT_CAPACITY
    assert rise == pytest.approx(2 * q * np.sqrt((t[-1] - 0.0) / (np.pi * k_rho_c)), rel=0.01)
