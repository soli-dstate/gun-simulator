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


def test_lead_bullet_pancakes_and_splashes_without_spalling_ar500(rifle):
    hit = terminal.impact(rifle, 838.0, 0.375 * INCH)
    rem = hit["remnant"]
    assert rem["state"] == "splash" and 2.5 < rem["expansion"] <= 4.5
    assert rem["length_share"] == pytest.approx(1 / rem["expansion"] ** 2)
    # Fast enough that most of it sprays off the rim, back across the face.
    assert rem["keep"] < 0.5
    assert hit["splash"]["velocity"] > 200 and hit["splash"]["count"] >= 6
    assert hit["spall"] is None   # the shock reaching the back face is well short of AR500's spall strength


def test_perforation_throws_debris_and_strips_the_jacket(rifle):
    ap = copy.deepcopy(rifle)
    ap.projectile.core_material = 4
    ap.projectile.jacket_thickness = 0.6e-3
    hit = terminal.impact(ap, 850.0, 0.25 * INCH, target="rha")
    assert hit["remnant"]["state"] == "intact" and hit["remnant"]["stripped"]
    assert hit["spall"]["cause"] == "debris" and 0 < hit["spall"]["velocity"] <= hit["residual_velocity"] + 1e-9


def test_rod_erodes_and_a_near_miss_spalls_the_back():
    g = Gun.load("configs/rh120_l55.toml")
    through = terminal.impact(g, 1700.0, 0.1, target="rha")
    assert through["remnant"]["state"] == "eroded" and 0.5 < through["remnant"]["length_share"] < 1
    # A plate it only just fails to get through: the back face bulges and a dish cracks off.
    limit = terminal.impact(g, 1700.0, 0.1, target="rha")["limit_thickness"]
    near = terminal.impact(g, 1700.0, limit / 0.95, target="rha")
    assert not near["perforated"]
    assert near["verdict"] == "spalled" and near["spall"]["cause"] == "bulge"
    assert near["spall"]["mass"] < 5.0   # a dish of the ligament, not the plate


def test_shock_spall_needs_the_back_face_close():
    g = Gun.load("configs/2a46m1_125_t80.toml")
    core = terminal.core_of(g)
    armour = terminal.ARMOURS["rha"]
    hit = terminal.penetrate(core, armour, 1700.0)
    thin = terminal.back_spall(core, armour, 1700.0, 0.01, hit, hit.regime, False, 0.0, None)
    thick = terminal.back_spall(core, armour, 1700.0, 0.3, hit, hit.regime, False, 0.0, None)
    assert thin["back_stress"] > thick["back_stress"]
    assert thin["cause"] == "shock" and thin["velocity"] > 0


def test_gel_series_and_recovered_bullet():
    hp = terminal.gel(Gun.load("configs/example_hollow_point.toml"), 360.0)
    s = hp["series"]
    assert len(s["time"]) == len(s["depth"]) == len(s["yaw"]) == len(s["expansion"])
    assert all(b > a for a, b in zip(s["time"], s["time"][1:]))
    assert hp["recovered"]["petals"] == 6 and hp["recovered"]["expansion"] == pytest.approx(hp["expansion"])
    # A slender rifle bullet yaws and ends up base first; a fragmenting one says how many pieces it threw.
    m4 = terminal.gel(Gun.load("configs/m4a1.toml"), 900.0)
    assert max(m4["series"]["yaw"]) == pytest.approx(180.0, abs=1.0)
    assert m4["recovered"]["fragmented"] and m4["recovered"]["fragments"] >= 4
    akm = terminal.gel(Gun.load("configs/akm.toml"), 715.0)
    assert 0.45 < akm["depth"] < 0.75   # 7.62x39 ball: about 60 cm


def test_bad_inputs(rifle):
    with pytest.raises(ValueError):
        terminal.impact(rifle, 800.0, 0.0)
    with pytest.raises(ValueError):
        terminal.impact(rifle, 800.0, 0.01, target="cardboard")
