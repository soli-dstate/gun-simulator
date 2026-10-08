import math
from pathlib import Path

import numpy as np
import pytest

from gun_sim import Gun, exterior, fluid, lumped, rifling

RIFLE = Path(__file__).parent.parent / "configs" / "example_rifle.toml"


@pytest.fixture
def gun():
    return Gun.load(RIFLE)


def test_moment_of_inertia_of_a_cylinder(gun):
    """A flat-based, flat-nosed projectile is a solid cylinder: I = m r^2 / 2."""
    p = gun.projectile
    p.ogive_length = p.boat_tail_length = 0.0
    r = gun.barrel.bore_diameter / 2
    assert rifling.moment_of_inertia(gun) == pytest.approx(p.mass * r * r / 2, rel=1e-3)


def test_moment_of_inertia_of_a_spitzer(gun):
    """A pointed bullet keeps its mass nearer the axis than a cylinder does."""
    k = rifling.moment_of_inertia(gun) / (gun.projectile.mass * (gun.barrel.bore_diameter / 2) ** 2)
    assert 0.35 < k < 0.5


def test_tangent_ogive_profile(gun):
    """The nose meets the shank at the bore radius and ends at the meplat."""
    p = gun.projectile
    x, r = rifling.profile(gun, points=2001)
    R = gun.barrel.bore_diameter / 2
    start = np.searchsorted(x, p.length - p.ogive_length)
    assert r[start] == pytest.approx(R, rel=1e-3)
    assert r[-1] == pytest.approx(p.meplat_diameter / 2, rel=1e-3)
    assert np.all(np.diff(r[start:]) <= 1e-12)


def test_smooth_bore_has_no_spin(gun):
    gun.barrel.twist = 0.0
    assert rifling.effective_mass(gun) == gun.projectile.mass
    assert rifling.stability(gun, 800.0) == 0.0
    r = lumped.simulate(gun)
    assert rifling.spin_report(gun, r)["spin_rpm"] == 0.0
    assert exterior.trajectory(gun, 800.0, max_range=500).spin_drift is None


def test_spin_rate_follows_twist(gun):
    r = lumped.simulate(gun)
    s = rifling.spin_report(gun, r)
    assert s["spin_rate"] == pytest.approx(2 * math.pi * r.muzzle_velocity / gun.barrel.twist)
    assert s["angular_impulse"] == pytest.approx(-s["moment_of_inertia"] * s["spin_rate"])
    assert s["spin_energy"] < 0.01 * 0.5 * gun.projectile.mass * r.muzzle_velocity**2
    assert s["peak_torque"] > 0


def test_faster_twist_costs_velocity(gun):
    slow = lumped.simulate(gun).muzzle_velocity
    gun.barrel.twist = 0.08
    assert rifling.effective_mass(gun) > 1.03 * gun.projectile.mass
    assert lumped.simulate(gun).muzzle_velocity < slow


def test_miller_stability_reference(gun):
    """A 168 gr .308 bullet, 1.215 in long, from a 1:12 barrel at 2600 ft/s in standard air.

    By hand: 30 * 168 / (38.96^2 * 0.308^3 * 3.945 * (1 + 3.945^2)) = 1.739, times
    (2600 / 2800)^(1/3) = 0.976 for the velocity, gives 1.70.
    """
    gun.barrel.bore_diameter = 0.308 * rifling.INCH
    gun.barrel.twist = 12 * rifling.INCH
    gun.projectile.mass = 168 * rifling.GRAIN
    gun.projectile.length = 1.215 * rifling.INCH
    sg = rifling.stability(gun, 2600 * 0.3048)
    assert sg == pytest.approx(1.70, rel=0.01)
    # Thinner (warmer, higher) air steadies it.
    assert rifling.stability(gun, 2600 * 0.3048, temperature=30, pressure=80e3) > sg


def test_left_hand_twist_drifts_left(gun):
    right = exterior.trajectory(gun, 830.0, max_range=800)
    gun.barrel.twist = -gun.barrel.twist
    left = exterior.trajectory(gun, 830.0, max_range=800)
    assert right.at(800)["spin_drift"] > 0.05
    assert left.at(800)["spin_drift"] == pytest.approx(-right.at(800)["spin_drift"])
    assert right.at(800)["windage"] == pytest.approx(right.at(800)["spin_drift"], abs=1e-6)


def test_engraving_profile(gun):
    gun.barrel.freebore = 1e-3
    gun.projectile.engraving_pressure = 50e6
    start, full, decay = rifling.engraving_window(gun)
    base = gun.projectile.bore_resistance
    assert start == 1e-3
    assert full - start == pytest.approx(gun.barrel.groove_depth / math.tan(math.radians(gun.barrel.leade_angle)))
    assert rifling.resistance(gun, 0.5e-3) == base
    assert rifling.resistance(gun, full) == pytest.approx(base + 50e6)
    assert rifling.resistance(gun, full + decay) == pytest.approx(base + 50e6 / math.e)
    assert rifling.resistance(gun, 0.3) == pytest.approx(base, abs=1e3)


def test_no_engraving_keeps_bore_resistance(gun):
    gun.barrel.freebore = 2e-3
    assert rifling.resistance(gun, 0.0) == rifling.resistance(gun, 0.1) == gun.projectile.bore_resistance


def test_freebore_lowers_peak_pressure(gun):
    """Engraving after a jump happens in a bigger volume, so the pressure peaks lower."""
    gun.projectile.shot_start_pressure = 15e6
    gun.projectile.engraving_pressure = 60e6
    for model in (lumped, fluid):
        seated = model.simulate(gun).peak_breech_pressure
        gun.barrel.freebore = 2e-3
        jumped = model.simulate(gun).peak_breech_pressure
        gun.barrel.freebore = 0.0
        assert jumped < 0.97 * seated, model.__name__


def test_engraving_resistance_slows_the_projectile_early(gun):
    """Over the first millimetres the engraved projectile lags the free one."""
    free = lumped.simulate(gun)
    gun.projectile.engraving_pressure = 80e6
    held = lumped.simulate(gun)
    t = 0.4e-3  # after shot start (about 0.2 ms), while engraving
    assert np.interp(t, held.time, held.travel) < np.interp(t, free.time, free.travel)


def test_bad_rifling_rejected(gun):
    gun.barrel.leade_angle = 0.0
    with pytest.raises(ValueError, match="leade_angle"):
        gun.validate()
    gun.barrel.leade_angle = 1.5
    gun.barrel.freebore = -1e-3
    with pytest.raises(ValueError, match="negative"):
        gun.validate()
