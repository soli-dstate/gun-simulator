from pathlib import Path

import numpy as np
import pytest

from gun_sim import Gun
from gun_sim import fluid, lumped

RIFLE = Path(__file__).parent.parent / "configs" / "example_rifle.toml"


@pytest.fixture
def gun():
    return Gun.load(RIFLE)


def test_config_loads(gun):
    assert gun.barrel.bore_area == pytest.approx(np.pi * 7.82e-3**2 / 4)
    assert gun.solver.cells == 100


def test_unknown_key_rejected():
    with pytest.raises(ValueError, match="unknown keys"):
        Gun.from_dict({"barrel": {"bore_diameter": 0.01, "travel": 0.5, "chamber_volume": 1e-6, "colour": "red"}})


def test_overfilled_chamber_rejected(gun):
    gun.propellant.charge_mass = 1.0
    with pytest.raises(ValueError, match="does not fit"):
        gun.validate()


def test_closed_chamber_conserves_mass_and_energy(gun):
    """No burning and a projectile that never moves: the gas must just sit there."""
    gun.propellant.burn_rate_coeff = 0.0
    gun.projectile.shot_start_pressure = 1e12
    gun.solver.max_time = 1e-4
    result = fluid.simulate(gun)
    assert not result.left_muzzle
    p = result.breech_pressure
    assert p.max() == pytest.approx(gun.ignition.pressure, rel=1e-9)
    assert p.min() == pytest.approx(gun.ignition.pressure, rel=1e-9)


def test_fluid_and_lumped_agree(gun):
    f = fluid.simulate(gun)
    l = lumped.simulate(gun)
    assert f.left_muzzle and l.left_muzzle
    assert f.muzzle_velocity == pytest.approx(l.muzzle_velocity, rel=0.05)
    assert f.peak_breech_pressure == pytest.approx(l.peak_breech_pressure, rel=0.2)


def test_energy_budget(gun):
    """Projectile kinetic energy cannot exceed the chemical energy of the charge."""
    r = fluid.simulate(gun)
    ke = 0.5 * gun.projectile.mass * r.muzzle_velocity**2
    chemical = gun.propellant.charge_mass * gun.propellant.force / (gun.propellant.gamma - 1)
    assert 0 < ke < chemical


def test_fluid_grid_convergence(gun):
    gun.solver.cells = 50
    coarse = fluid.simulate(gun)
    gun.solver.cells = 200
    fine = fluid.simulate(gun)
    assert coarse.muzzle_velocity == pytest.approx(fine.muzzle_velocity, rel=0.01)


def test_missing_geometry_scaled_from_bore():
    gun = Gun.from_dict({
        "barrel": {"bore_diameter": 2 * 7.82e-3, "travel": 1.0, "chamber_volume": 30e-6},
        "projectile": {"mass": 0.05},
        "propellant": {"charge_mass": 0.01, "force": 1e6, "covolume": 1e-3, "gamma": 1.24, "density": 1600,
                       "web": 4e-4, "burn_rate_coeff": 7e-9, "burn_rate_exp": 0.9},
        "case": {"length": 0.1},
    })
    assert gun.case.length == 0.1                               # given values are kept
    assert gun.case.rim_diameter == pytest.approx(2 * 11.94e-3)  # missing ones scale with the bore
    assert gun.projectile.length == pytest.approx(2 * 28.6e-3)
    assert gun.barrel.breech_diameter == pytest.approx(2 * 30e-3)
    assert gun.barrel.muzzle_diameter == pytest.approx(2 * 16e-3)
