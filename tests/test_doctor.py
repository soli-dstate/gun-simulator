"""The expert editor's assistant must be able to fix any field, including ones added later.

The fields come from the config dataclasses, so a new field is covered here as soon as it exists.
"""

from dataclasses import asdict

import pytest

from gun_sim import doctor
from gun_sim.config import Gun
from gun_sim.designer import CONFIG_DIR

# A rifle, a revolver, a pistol, a chain gun and a tank gun: between them they reach every validation branch.
PRESETS = ["m4a1", "colt_anaconda", "glock_17", "mk44_bushmaster_ii", "2a46m5_125_t90"]


def preset(name):
    return asdict(Gun.load(CONFIG_DIR / f"{name}.toml"))


def bad_values(value):
    """Values that may break a field holding `value`."""
    if isinstance(value, bool):
        return [not value]
    if isinstance(value, (int, float)):
        return [-1e9, 1e9, 0, -abs(value) - 1, None]
    if isinstance(value, str):
        return ["bogus", None]
    if value is None:
        return [-1e9, 1e9, 0, "bogus"]
    return []


def breakages(name):
    gun = preset(name)
    for section, keys in doctor.DEFAULTS.items():
        for key in keys:
            for bad in bad_values(gun[section][key]):
                yield section, key, bad


@pytest.mark.parametrize("name", PRESETS)
def test_every_broken_field_is_fixed(name):
    good = preset(name)
    assert doctor.error_of(good) is None
    failures = []
    for section, key, bad in breakages(name):
        broken = preset(name)
        broken[section][key] = bad
        if doctor.error_of(broken) is None:
            continue   # not an error for this gun
        out = doctor.check(broken, reference=good)
        if not out["complete"] or doctor.error_of(out["fixed"]) is not None or not out["errors"]:
            failures.append(f"{section}.{key} = {bad!r}: {out['errors'][-1]['message']}")
    assert not failures, f"{len(failures)} unfixed:\n" + "\n".join(failures)


def test_fixes_without_a_reference():
    """With nothing to go back to, the message and the defaults are enough for the usual mistakes."""
    gun = preset("m4a1")
    gun["barrel"]["leade_angle"] = 60.0
    gun["feed"]["ramp_angle"] = 2.0
    gun["propellant"]["form_lambda"] = 0.3
    gun["trigger"]["type"] = "double_action"
    gun["action"]["hammer"] = False
    out = doctor.check(gun)
    assert out["complete"] and doctor.error_of(out["fixed"]) is None
    assert len(out["errors"]) >= 4
    assert out["fixed"]["barrel"]["leade_angle"] <= 45


def test_valid_config_has_no_errors():
    out = doctor.check(preset("m4a1"))
    assert out == {"errors": [], "fixed": preset("m4a1"), "complete": True}


def test_errors_are_counted_one_by_one():
    gun = preset("m4a1")
    gun["barrel"]["leade_angle"] = 90.0
    gun["muzzle_device"]["type"] = "nonsense"
    gun["feed"]["friction"] = 3.0
    good = preset("m4a1")
    out = doctor.check(gun, reference=good)
    assert out["complete"] and len(out["errors"]) == 3
    changed = {(c["section"], c["key"]) for e in out["errors"] for c in e["fix"]}
    assert changed == {("barrel", "leade_angle"), ("muzzle_device", "type"), ("feed", "friction")}
