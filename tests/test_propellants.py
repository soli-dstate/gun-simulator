from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import pytest

from gun_sim import Gun, lumped
from gun_sim.config import Propellant
from gun_sim.propellants import (COMPOSITIONS, GRAINS, combustibles, form_coefficients, grain_geometry, inhibition,
                                 sliver_phase, smokiness)

ROOT = Path(__file__).parent.parent
RIFLE = ROOT / "configs" / "example_rifle.toml"
SEVEN_PERF = ROOT / "configs" / "example_7perf.toml"

GRAIN_CASES = {
    "tube": dict(grain="tube", web=0.4e-3, grain_length=2e-3),
    "sphere": dict(grain="sphere", web=0.8e-3),
    "flake": dict(grain="flake", web=0.3e-3, grain_length=2e-3),
    "7-perf": dict(grain="7-perf", web=0.4e-3, grain_length=2e-3, perforation_diameter=0.2e-3),
    "19-perf": dict(grain="19-perf", web=0.3e-3, grain_length=2e-3, perforation_diameter=0.15e-3),
}


def make(**kwargs) -> Propellant:
    base = dict(charge_mass=2.9e-3, composition="single_base")
    base.update(kwargs)
    return Propellant(**base)


def test_old_rifle_config_is_neutral():
    prop = Gun.load(RIFLE).propellant
    assert (prop.form_chi, prop.form_lambda, prop.form_mu) == (1.0, 0.0, 0.0)
    assert prop.z_burnout == 1.0
    z = np.linspace(0, 1, 11)
    np.testing.assert_allclose(prop.burnt_fraction(z), z)


@pytest.mark.parametrize("name", list(GRAIN_CASES))
def test_form_function_shape(name):
    prop = make(**GRAIN_CASES[name])
    z = np.linspace(0.0, prop.z_burnout, 400)
    psi = prop.burnt_fraction(z)
    assert prop.burnt_fraction(0.0) == 0.0
    assert prop.burnt_fraction(prop.z_burnout) == pytest.approx(1.0)
    assert prop.burnt_fraction(prop.z_burnout * 3) == pytest.approx(1.0)
    assert np.all(np.diff(psi) >= -1e-12), "psi must not decrease"
    assert np.all((psi >= 0) & (psi <= 1))


def test_burnt_fraction_accepts_float_and_array():
    prop = make(**GRAIN_CASES["7-perf"])
    assert isinstance(prop.burnt_fraction(0.5), float)
    out = prop.burnt_fraction(np.array([0.0, 0.5, 1.0, 2.0]))
    assert out.shape == (4,)
    assert out[-1] == pytest.approx(1.0)


def test_sphere_matches_closed_form():
    prop = make(**GRAIN_CASES["sphere"])
    z = np.linspace(0, 1, 50)
    np.testing.assert_allclose(prop.burnt_fraction(z), 1 - (1 - z) ** 3, atol=1e-12)


def test_seven_perf_sliver_phase():
    prop = make(**GRAIN_CASES["7-perf"])
    psi1 = prop.burnt_fraction(1.0)
    assert 0.8 < psi1 < 0.9
    assert prop.z_burnout > 1.0
    assert prop.form_z_k == prop.z_burnout
    # Phase 2 is continuous at z = 1.
    assert prop.burnt_fraction(1.0 + 1e-9) == pytest.approx(psi1, abs=1e-6)


def test_tube_limit_is_neutral():
    chi, lam, mu = form_coefficients("tube", 0.4e-3, 1e4)
    assert chi == pytest.approx(1.0, abs=1e-6)
    assert lam == pytest.approx(0.0, abs=1e-6)
    assert mu == 0.0


def test_sliver_phase_solves_its_conditions():
    chi_s, lam_s, z_k = sliver_phase(0.4e-3, 0.2e-3, 0.85)
    assert chi_s * (1 + lam_s) == pytest.approx(0.85)
    assert chi_s * z_k * (1 + lam_s * z_k) == pytest.approx(1.0)


def test_grain_geometry_derives_missing_dimensions():
    web, diameter = grain_geometry("7-perf", None, None, 2.2e-3, 0.2e-3)
    assert web == pytest.approx(0.4e-3)
    web, diameter = grain_geometry("7-perf", 0.4e-3, None, None, 0.2e-3)
    assert diameter == pytest.approx(2.2e-3)
    with pytest.raises(ValueError, match="needs"):
        grain_geometry("tube", 0.4e-3, None)


def test_unknown_grain_rejected():
    with pytest.raises(ValueError, match="unknown grain"):
        make(grain="rod", web=1e-3)


def test_composition_fills_missing_fields():
    prop = Propellant(charge_mass=1e-3, composition="double_base", web=0.4e-3)
    for key, value in COMPOSITIONS["double_base"].items():
        assert getattr(prop, key) == value


def test_explicit_values_override_composition():
    prop = Propellant(charge_mass=1e-3, composition="double_base", web=0.4e-3, force=9e5, gamma=1.3)
    assert prop.force == 9e5
    assert prop.gamma == 1.3
    assert prop.covolume == COMPOSITIONS["double_base"]["covolume"]


def test_unknown_composition_rejected():
    with pytest.raises(ValueError, match="unknown composition"):
        Propellant(charge_mass=1e-3, composition="cordite", web=0.4e-3)


def test_missing_fields_are_named():
    with pytest.raises(ValueError, match="force, covolume, gamma, density, web, burn_rate_coeff, burn_rate_exp"):
        Propellant(charge_mass=1e-3)


def test_grain_library_lists_every_shape():
    assert set(GRAINS) == {"tube", "sphere", "ball", "flake", "7-perf", "19-perf"}
    for name in GRAINS:
        make(**{**GRAIN_CASES.get(name, GRAIN_CASES["sphere"]), "grain": name})


def test_propellant_round_trip_is_exact():
    prop = make(**GRAIN_CASES["7-perf"])
    assert asdict(Propellant(**asdict(prop))) == asdict(prop)


def test_gun_round_trip_is_exact():
    gun = Gun.load(SEVEN_PERF)
    assert Gun.from_dict(asdict(gun)) == gun


def test_invalid_form_rejected():
    gun = Gun.load(RIFLE)
    gun.propellant = replace(gun.propellant, form_chi=1.2)
    with pytest.raises(ValueError, match="z_burnout"):
        gun.validate()


def test_seven_perf_config_burns_whole_charge_in_long_barrel():
    gun = Gun.load(SEVEN_PERF)
    gun.barrel.travel = 3.0
    gun.solver.lumped_dt = 1e-6
    gun.solver.max_time = 0.05
    result = lumped.simulate(gun)
    assert result.burnt_at_muzzle == pytest.approx(1.0)
    assert result.peak_breech_pressure < 450e6


def test_seven_perf_config_runs_lumped():
    gun = Gun.load(SEVEN_PERF)
    result = lumped.simulate(gun)
    assert result.muzzle_velocity > 100
    assert result.peak_breech_pressure < 450e6


def test_flash_suppressant_costs_impetus_and_cools_the_flame():
    plain = make(web=0.4e-3)
    salt = make(web=0.4e-3, flash_suppressant="potassium_sulfate", suppressant_fraction=0.01)
    assert plain.impetus == plain.force
    assert 0.97 * plain.force < salt.impetus < 0.99 * plain.force
    assert salt.gas_constant == pytest.approx(0.99 * plain.gas_constant)
    assert salt.impetus / salt.gas_constant < plain.impetus / plain.gas_constant   # cooler flame
    # The oxidizer gives heat instead, and burns some of the fuel in the bore.
    nitrate = make(web=0.4e-3, flash_suppressant="potassium_nitrate", suppressant_fraction=0.01)
    assert nitrate.impetus / nitrate.gas_constant > plain.impetus / plain.gas_constant
    assert combustibles("single_base", "potassium_nitrate", 0.01)[0] < combustibles("single_base", "potassium_sulfate", 0.01)[0]
    assert inhibition(None, 0.0) == 0.0 and inhibition("potassium_sulfate", 0.01) > 0
    assert smokiness(None, 0.0) == 1.0 and smokiness("potassium_sulfate", 0.01) > 2


def test_flash_suppressant_is_not_applied_twice_on_a_round_trip():
    gun = Gun.load(RIFLE)
    gun.propellant = replace(gun.propellant, flash_suppressant="potassium_cryolite", suppressant_fraction=0.015)
    again = Gun.from_dict(asdict(gun))
    assert again.propellant.impetus == pytest.approx(gun.propellant.impetus)
    assert lumped.simulate(again).muzzle_velocity < lumped.simulate(Gun.load(RIFLE)).muzzle_velocity


def test_flash_suppressant_is_checked():
    with pytest.raises(ValueError, match="unknown flash_suppressant"):
        make(web=0.4e-3, flash_suppressant="sodium_chloride", suppressant_fraction=0.01)
    with pytest.raises(ValueError, match="needs a flash_suppressant"):
        make(web=0.4e-3, suppressant_fraction=0.01)
    with pytest.raises(ValueError, match="between 0 and 0.1"):
        make(web=0.4e-3, flash_suppressant="potassium_sulfate", suppressant_fraction=0.5)
