import copy

import pytest

from gun_sim import terminal
from gun_sim.config import Gun

INCH = 0.0254


@pytest.fixture(scope="module")
def rifle():
    return Gun.load("configs/example_rifle.toml")


def test_lead_core_craters_ar500_but_does_not_get_through(rifle):
    hit = terminal.impact(rifle, 838.0, 0.375 * INCH)
    assert hit["verdict"] == "cratered"
    assert hit["regime"] == "splash"
    assert 1e-3 < hit["depth"] < 4e-3
    # RHA is softer than AR500: deeper, and the plate is worth more than its thickness in RHAe.
    assert hit["rha_depth"] > hit["depth"]
    assert hit["plate_rhae"] > hit["line_of_sight"]


def test_pistol_bullet_is_stopped(rifle):
    g = Gun.load("configs/glock_17.toml")
    hit = terminal.impact(g, 360.0, 0.25 * INCH)
    assert hit["verdict"] == "stopped" and hit["depth"] < 1e-3


def test_hard_core_penetrates_rigidly(rifle):
    ap = copy.deepcopy(rifle)
    ap.projectile.core_material = 4   # hardened steel
    ap.projectile.jacket_thickness = 0.6e-3
    hit = terminal.impact(ap, 850.0, 0.25 * INCH)
    assert hit["regime"] == "rigid" and hit["verdict"] == "perforated"
    assert 0 < hit["residual_velocity"] < 850.0
    assert hit["ballistic_limit"] < 850.0
    # About a centimetre of RHA, as .30 AP manages.
    assert 8e-3 < hit["rha_depth"] < 18e-3
    thick = terminal.impact(ap, 850.0, 0.75 * INCH)
    assert not thick["perforated"]


def test_penetration_grows_with_velocity_and_obliquity_thickens_the_plate(rifle):
    ap = copy.deepcopy(rifle)
    ap.projectile.core_material = 5   # tungsten carbide
    slow, fast = terminal.impact(ap, 600.0, 0.01), terminal.impact(ap, 900.0, 0.01)
    assert fast["depth"] > slow["depth"]
    angled = terminal.impact(ap, 900.0, 0.01, angle=45.0)
    assert angled["line_of_sight"] == pytest.approx(0.01 * 2 ** 0.5)
    assert terminal.impact(ap, 900.0, 0.01, angle=75.0)["verdict"] == "ricochet"


def test_long_rod_erodes():
    g = Gun.load("configs/rh120_l55.toml")
    hit = terminal.impact(g, 1700.0, 0.05)
    assert hit["regime"] == "eroding" and hit["perforated"]
    assert 0.4 < hit["rha_depth"] < 0.9


def test_bad_inputs(rifle):
    with pytest.raises(ValueError):
        terminal.impact(rifle, 800.0, 0.0)
    with pytest.raises(ValueError):
        terminal.impact(rifle, 800.0, 0.01, target="cardboard")
