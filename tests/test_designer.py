import pytest

from gun_sim import designer
from gun_sim.cartridges import CARTRIDGES
from gun_sim.config import Gun


def test_every_cartridge_has_both_names_and_a_gun():
    for c in CARTRIDGES.values():
        assert c.metric
        assert c.imperial or c.template   # cannon go by their metric name only
        assert designer.platforms_for(c), c.id
        lo, hi, default = designer.barrel_range(c, designer.platforms_for(c)[0])
        assert lo < default < hi


def test_schema_lists_names_and_loads():
    s = designer.schema()
    by_id = {c["id"]: c for c in s["cartridges"]}
    assert by_id["762x51"]["metric"] == "7.62×51mm NATO" and by_id["762x51"]["imperial"] == ".308 Winchester"
    assert ".308" in by_id["762x51"]["aliases"]
    assert any(ld["core"] == "hardened_steel" for ld in by_id["762x51"]["loads"])


@pytest.mark.parametrize("cartridge, platform, status", [
    ("9x19", "pistol_striker", "cycled"),
    ("556", "ar_auto", "cycled"),
    ("762x51", "bolt", "manual"),
    ("357mag", "revolver_da", "fired"),
])
def test_design_builds_a_working_gun(cartridge, platform, status):
    out = designer.design({"cartridge": cartridge, "platform": platform})
    gun = Gun.from_dict(out["gun"])   # a valid config the expert editor can take
    p = out["prediction"]
    load = CARTRIDGES[cartridge].loads[0]
    assert p["left_muzzle"] and p["status"] == status
    # The default barrel is near the load's reference one, so near its published velocity.
    assert p["muzzle_velocity"] == pytest.approx(load.velocity, rel=0.12)
    assert p["peak_pressure"] < 1.15 * CARTRIDGES[cartridge].max_pressure
    assert gun.barrel.chamber_volume == pytest.approx(gun.powder_space)
    assert {n["title"] for n in out["notes"]} >= {"Chamber", "Powder burn rate"}


def test_shorter_barrel_is_slower():
    long = designer.design({"cartridge": "762x51", "platform": "bolt", "barrel_length": 0.66})
    short = designer.design({"cartridge": "762x51", "platform": "bolt", "barrel_length": 0.33})
    assert short["prediction"]["muzzle_velocity"] < long["prediction"]["muzzle_velocity"] - 50


def test_heavy_bullet_gets_a_faster_twist():
    # 77 gr in a 1:9 would be marginal; the standard 5.56 twist is 1:7, so ask for the slow one.
    out = designer.design({"cartridge": "556", "load": "mk262", "platform": "bolt", "twist": 0.2286})
    assert out["gun"]["barrel"]["twist"] == pytest.approx(0.2286)


def test_rejects_a_gun_that_cannot_take_the_cartridge():
    with pytest.raises(ValueError):
        designer.design({"cartridge": "50bmg", "platform": "pistol_striker"})
    with pytest.raises(ValueError):
        designer.design({"cartridge": "556", "platform": "ar_auto", "barrel_length": 5.0})
