"""Projectile shape variants: config side only (the 3D profiles are drawn in the browser)."""

import dataclasses
from pathlib import Path

import pytest

from gun_sim import Gun
from gun_sim.config import CORE_MATERIALS, Projectile
from gun_sim.ui import api

CONFIGS = Path(__file__).resolve().parents[1] / "configs"
NEW_FIELDS = {
    "ogive_radius_ratio", "hollow_point_diameter", "hollow_point_depth", "cannelure_position",
    "cannelure_width", "cannelure_depth", "jacket_thickness", "core_material", "exposed_core_length",
}


def _base():
    d = dataclasses.asdict(Gun.load(CONFIGS / "example_rifle.toml"))
    d.pop("projectile")
    return d


def test_defaults_keep_the_plain_projectile():
    p = Projectile(mass=0.01)
    assert p.ogive_radius_ratio == 1.0   # tangent ogive
    assert p.core_material == 0
    for name in NEW_FIELDS - {"ogive_radius_ratio", "core_material"}:
        assert getattr(p, name) == 0.0, name


def test_existing_preset_is_plain():
    p = Gun.load(CONFIGS / "example_rifle.toml").projectile
    assert p.ogive_radius_ratio == 1.0
    assert p.jacket_thickness == 0.0
    assert p.hollow_point_depth == 0.0


def test_hollow_point_preset_loads_and_round_trips():
    gun = Gun.load(CONFIGS / "example_hollow_point.toml")
    p = gun.projectile
    assert p.ogive_radius_ratio > 1 and p.hollow_point_depth > 0 and p.cannelure_depth > 0
    assert p.jacket_thickness > 0 and p.core_material == CORE_MATERIALS.index("lead")
    assert Gun.from_dict(dataclasses.asdict(gun)).projectile == p


def test_core_material_by_name_or_code():
    for code, name in enumerate(CORE_MATERIALS):
        by_name = Gun.from_dict({**_base(), "projectile": {"mass": 0.01, "core_material": name.upper()}})
        by_code = Gun.from_dict({**_base(), "projectile": {"mass": 0.01, "core_material": code}})
        assert by_name.projectile.core_material == code == by_code.projectile.core_material


@pytest.mark.parametrize("bad", [
    {"ogive_radius_ratio": 0.8},
    {"ogive_radius_ratio": 11},
    {"core_material": "uranium"},
    {"core_material": 6},
    {"hollow_point_depth": -1e-3},
    {"jacket_thickness": -1e-4},
])
def test_invalid_shape_values_rejected(bad):
    with pytest.raises(ValueError):
        Gun.from_dict({**_base(), "projectile": {"mass": 0.01, **bad}})


def test_ui_form_lists_every_shape_field():
    keys = {row[0] for row in api.FIELDS["projectile"]}
    assert NEW_FIELDS <= keys
    assert keys <= {f.name for f in dataclasses.fields(Projectile)}
