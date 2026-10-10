"""Projectile construction (projectiles.py): designs, fills, and what they do in flight and in a target."""

import copy
import dataclasses

import pytest

from gun_sim import exterior, projectiles, terminal
from gun_sim.config import Gun
from gun_sim.ui import api

INCH = 0.0254


def _load(name: str) -> Gun:
    return Gun.load(f"configs/{name}.toml")


def _with(gun: Gun, design: str) -> Gun:
    return Gun.from_dict(api.projectile_design({"gun": dataclasses.asdict(gun), "design": design})["gun"])


@pytest.fixture(scope="module")
def rifle():
    return _load("example_rifle")


@pytest.fixture(scope="module")
def tank():
    return _load("rh120_l55")


@pytest.fixture(scope="module")
def cannon():
    return _load("mk44_bushmaster_ii")


@pytest.mark.parametrize("name", ["example_rifle", "mk44_bushmaster_ii", "rh120_l55"])
def test_every_design_builds_and_keeps_the_seat(name):
    gun = _load(name)
    for key in projectiles.DESIGNS:
        g = _with(gun, key)
        assert g.projectile.mass > 0 and g.flight_mass > 0, key
        assert g.seat == pytest.approx(gun.seat), key   # the base stays where it was seated
        parts = projectiles.parts(g)
        assert parts.scale == pytest.approx(1.0, rel=0.02), key   # the mass is what the parts weigh


def test_a_bullet_design_keeps_the_bullets_length(rifle):
    g = _with(rifle, "jhp")
    assert g.projectile.length == pytest.approx(rifle.projectile.length)
    assert g.projectile.hollow_point_depth > 0


def test_fills_are_laid_out_where_asked(rifle):
    g = _with(rifle, "raufoss")
    parts = projectiles.parts(g)
    roles = {pc.material: pc.role for pc in parts.pieces if pc.mass > 0}
    assert roles["tungsten_carbide"] == "insert" and roles["petn"] == "fill" and roles["zirconium"] == "tip"
    # Front to back: incendiary, explosive, then the penetrator.
    first = {m: min(pc.x0 for pc in parts.pieces if pc.material == m) for m in ("zirconium", "petn", "tungsten_carbide")}
    assert first["zirconium"] > first["petn"] > first["tungsten_carbide"]


def test_shaped_charge_jet_ignores_speed_and_hates_spin(tank, cannon):
    heat = _with(tank, "heat_fs")
    slow = terminal.impact(heat, 600.0, 0.3, target="rha", distance=500, time=0.5, muzzle_velocity=1100)
    fast = terminal.impact(heat, 1100.0, 0.3, target="rha", distance=500, time=0.5, muzzle_velocity=1100)
    assert slow["regime"] == fast["regime"] == "jet"
    assert slow["payload"]["jet"]["rha_depth"] == pytest.approx(fast["payload"]["jet"]["rha_depth"])
    assert 0.4 < fast["rha_depth"] < 0.9 and fast["perforated"]
    # A spun HEAT shell's jet spreads.
    spun = terminal.impact(_with(cannon, "heat"), 1000.0, 0.05, target="rha", distance=100, time=0.1,
                           muzzle_velocity=1000)
    assert spun["payload"]["jet"]["spin_factor"] < 0.8


def test_fuze_needs_arming(tank):
    heat = _with(tank, "heat_fs")
    near = terminal.impact(heat, 1100.0, 0.3, target="rha", distance=5, time=0.005, muzzle_velocity=1100)
    assert not near["payload"]["fuze"]["armed"] and near["regime"] != "jet"


def test_hesh_scabs_plate_up_to_its_limit(tank):
    hesh = _with(tank, "hesh")
    thin = terminal.impact(hesh, 700.0, 0.12, target="rha", distance=500, time=0.7)
    thick = terminal.impact(hesh, 700.0, 0.30, target="rha", distance=500, time=0.7)
    assert thin["verdict"] == "scabbed"
    assert thick["verdict"] != "scabbed" and not thick["perforated"]


def test_he_breaches_thin_plate_and_throws_fragments(cannon):
    he = _with(cannon, "he")
    hit = terminal.impact(he, 1000.0, 0.004, target="aluminium", distance=500, time=0.5)
    assert hit["verdict"] == "breached"
    frag = hit["payload"]["fragments"]
    assert frag["count"] > 100 and 500 < frag["velocity"] < 2500 and frag["lethal_radius"] > 0
    assert hit["payload"]["blast"]["eardrums"] > hit["payload"]["blast"]["lungs"]


def test_self_destruct_and_airburst(cannon):
    hei = _with(cannon, "hei")
    late = terminal.impact(hei, 400.0, 0.01, target="rha", distance=3000, time=hei.projectile.fuze_time + 1)
    assert late["verdict"] == "self-destructed"
    ab = _with(cannon, "he_ab")
    assert terminal.impact(ab, 600.0, 0.01, distance=2000, time=3.0)["verdict"] == "airburst"


def test_delay_fuze_bursts_behind_a_perforated_plate(rifle):
    mp = _with(rifle, "raufoss")
    hit = terminal.impact(mp, 840.0, 0.004, target="rha", distance=100, time=0.12)
    assert hit["perforated"]
    fz = hit["payload"]["fuze"]
    assert fz["where"] == "behind" and fz["behind"] > 0
    assert hit["payload"]["incendiary"]["lights"]


def test_shatter_and_the_penetrating_cap(rifle):
    wc = _with(rifle, "ap_wc")
    core = terminal.core_of(wc)
    ar500, rha = terminal.ARMOURS["ar500"], terminal.ARMOURS["rha"]
    assert terminal.shatter_speed(core, ar500) < terminal.shatter_speed(core, rha)
    capped = dataclasses.replace(core, capped=True)
    assert terminal.shatter_speed(capped, ar500) > terminal.shatter_speed(core, ar500)
    assert terminal.penetrate(core, ar500, 1400.0).shattered


def test_depleted_uranium_goes_deeper_and_burns(tank):
    w = terminal.impact(_with(tank, "apfsds"), 1650.0, 0.5, target="rha")
    du = terminal.impact(_with(tank, "apfsds_du"), 1650.0, 0.5, target="rha")
    assert du["rha_depth"] > w["rha_depth"]
    assert du["payload"].get("pyrophoric")


def test_frangible_turns_to_dust_on_steel(rifle):
    hit = terminal.impact(_with(rifle, "frangible"), 840.0, 0.375 * INCH)
    assert hit["verdict"] == "dusted"


def test_gelatin(rifle):
    pistol = _load("glock_17")
    fmj = terminal.gel(_with(pistol, "fmj_rn"), 360.0)
    jhp = terminal.gel(_with(pistol, "jhp"), 370.0)
    assert 0.5 < fmj["depth"] < 0.8 and fmj["expansion"] == pytest.approx(1.0)
    assert 0.2 < jhp["depth"] < fmj["depth"] and jhp["expansion"] > 1.5
    # A slender ball bullet yaws, and fragments only when fast.
    fast, slow = terminal.gel(_with(rifle, "fmj"), 900.0), terminal.gel(_with(rifle, "fmj"), 600.0)
    assert fast["yaw_depth"] and fast["fragmented"] and not slow["fragmented"]
    assert fast["temporary_cavity"] > fmj["temporary_cavity"]


def test_tracer_burns_out_and_lightens(rifle):
    plain, traced = _with(rifle, "fmj"), _with(rifle, "tracer")
    t = exterior.trajectory(traced, 840.0, max_range=1500)
    assert t.tracer_burnout and 1.0 < t.tracer_burnout < 6.0
    burn, mass = exterior.tracer_burn(traced)
    assert 0 < mass < 0.05 * traced.projectile.mass
    assert t.range_at_time(t.tracer_burnout) > 300


def test_target_api_gelatin_and_payload(rifle):
    g = dataclasses.asdict(_with(rifle, "polymer_tip"))
    r = api.target({"gun": g, "muzzle_velocity": 850.0, "distance": 50.0, "target": "gelatin"})
    assert r["kind"] == "gel" and r["series"]["depth"] and r["parts"]
    p = api.target({"gun": dataclasses.asdict(_with(rifle, "api")), "muzzle_velocity": 850.0, "distance": 50.0,
                    "thickness": 0.006, "target": "ar500"})
    assert p["kind"] == "plate" and "incendiary" in p["payload"] and p["series"]["depth"]


def test_ui_lists_every_new_field():
    keys = {row[0] for row in api.FIELDS["projectile"]}
    for name in ("insert_material", "filler", "tip_filler", "tracer", "liner_material", "cap", "fuze", "fuze_delay",
                 "fuze_time", "arming_distance", "jacket_material", "construction", "boom_length", "sabot_material"):
        assert name in keys
    schema = api.schema()
    assert "raufoss" in schema["projectiles"]["designs"] and "gelatin" in schema["targets"]["materials"]


def test_easy_mode_cannon_loads_use_designs():
    from gun_sim import designer
    out = designer.design({"cartridge": "120x570", "load": "heat_fs"})
    assert out["gun"]["projectile"]["type"] == "finned" and out["gun"]["projectile"]["liner_material"] == "copper"


def test_copy_of_gun_unaffected_by_design(rifle):
    before = copy.deepcopy(rifle.projectile)
    _with(rifle, "apcbc")
    assert rifle.projectile == before
