"""The expert editor's assistant: every error in a gun config, and a fix for each.

Gun.validate() stops at the first problem, so the checker works through them one at a
time: it finds the error, searches for a field change that clears it (or at least moves
on to a different error without just shifting the blame onto the changed field), applies
it, and validates again. The fixes it tries, in order, for each field it suspects:

1. a value the message suggests ("set shooter.stance = \"mount\"") or one worked out for
   the error (a form function scaled to reach 1, a charge that fits its chamber),
2. the value clamped into the range the message gives,
3. the value from the last config that passed (the reference), so a bad edit is undone,
4. the field's default, or blank where blank is allowed,
5. each other option, for a choice.

Suspects come from the message: the fields it names, then the whole of each section it
names, and only then every field, trying just the reference and the default.
"""

from __future__ import annotations

import copy
import json
import math
import re
import time
from dataclasses import MISSING, asdict, fields

from .config import (ACTION_TYPES, CASE_MATERIALS, CYLINDER_LOADING, DEVICE_TYPES, FEED_TYPES, FIRE_MODES, LOCKINGS,
                     PROJECTILE_TYPES, STANCES, STYLES, TRIGGER_TYPES, Action, Appearance, Barrel, Case, Feed, Gun,
                     Ignition, Mount, MuzzleDevice, Projectile, Propellant, Shooter, SolverSettings, Trigger)

SECTIONS = {
    "barrel": Barrel, "projectile": Projectile, "propellant": Propellant, "case": Case, "ignition": Ignition,
    "solver": SolverSettings, "action": Action, "shooter": Shooter, "muzzle_device": MuzzleDevice, "feed": Feed,
    "appearance": Appearance, "mount": Mount, "trigger": Trigger,
}

CHOICES = {
    ("projectile", "type"): PROJECTILE_TYPES, ("action", "type"): ACTION_TYPES, ("shooter", "stance"): STANCES,
    ("feed", "type"): FEED_TYPES, ("feed", "loading"): CYLINDER_LOADING, ("feed", "select"): ("left", "right"),
    ("trigger", "type"): TRIGGER_TYPES, ("trigger", "mode"): FIRE_MODES, ("muzzle_device", "type"): DEVICE_TYPES,
    ("action", "locking"): LOCKINGS, ("appearance", "style"): STYLES, ("case", "material"): CASE_MATERIALS,
    ("barrel", "chamber_shape"): ("cylinder", "case"), ("action", "hammer"): (True, False),
    ("case", "combustible"): (True, False),
}

# Words in a message that point at a section, beyond the section's own name.
SECTION_WORDS = {
    "chain gun": ["action", "feed"], "sliding wedge": ["action", "mount", "shooter"], "sliding-wedge": ["action", "shooter"],
    "revolver": ["action", "feed", "barrel", "trigger"], "striker": ["action", "trigger"], "hammer": ["action"],
    "gas action": ["action"], "gas-delayed": ["action"], "direct impingement": ["action"], "autoloader": ["feed", "action"],
    "bore evacuator": ["barrel"], "sabot": ["projectile"], "recuperator": ["mount"], "buffer": ["mount"],
    "flash suppressant": ["propellant"], "form function": ["propellant"], "charge": ["propellant", "barrel"],
    "the gun must be heavier": ["action"], "core_material": ["projectile"], "ogive_radius_ratio": ["projectile"],
}

# Fields a message points at without naming them.
HINTS = {
    "does not fit in the chamber": [("propellant", "charge_mass"), ("barrel", "chamber_volume")],
    "form function must reach": [("propellant", "form_chi"), ("propellant", "form_lambda"), ("propellant", "form_mu")],
    "a gas action needs": [("action", "gas_port_diameter"), ("action", "piston_diameter"), ("action", "gas_volume")],
    "the gun must be heavier": [("action", "gun_mass"), ("action", "bolt_mass"), ("action", "barrel_mass")],
    "a bore evacuator needs": [("barrel", "evacuator_volume"), ("barrel", "evacuator_nozzles"),
                               ("barrel", "evacuator_nozzle_diameter")],
    "leaves the charge no impetus": [("propellant", "suppressant_fraction"), ("propellant", "flash_suppressant")],
    "suppressant_fraction needs": [("propellant", "flash_suppressant"), ("propellant", "suppressant_fraction")],
    "freebore, groove depth": [("barrel", "freebore"), ("barrel", "groove_depth"), ("projectile", "engraving_pressure")],
    "the pulls and their travels": [("trigger", "pull"), ("trigger", "travel"), ("trigger", "da_pull"),
                                    ("trigger", "da_travel")],
}

UNITS = {"mm": 1e-3, "ms": 1e-3, "µs": 1e-6, "us": 1e-6, "kw": 1e3, "w": 1.0, "s": 1.0, "j": 1.0, "k": 1.0,
         "kn": 1e3, "mpa": 1e6, "cm": 1e-2, "m": 1.0, "g": 1e-3, "kg": 1.0}
NUM = r"(-?\d+(?:\.\d+)?(?:e-?\d+)?)"
RANGES = [re.compile(NUM + r"\s*([a-zµ]+)?\s+and\s+" + NUM + r"\s*([a-zµ/]+)?", re.I),
          re.compile(NUM + r"\s*([a-zµ]+)?\s+to\s+" + NUM + r"\s*([a-zµ/]+)?", re.I)]
SUGGEST = re.compile(r"\b([a-z_]+)\.([a-z_]+)\s*(?:=\s*)?(\"[^\"]*\"|true\b|false\b)")
STEP_BUDGET = 40
TIME_BUDGET = 4.0   # s, so a hopeless config can't hang the editor


def defaults() -> dict:
    """{section: {field: default}}, MISSING for a field with none."""
    out = {}
    for name, cls in SECTIONS.items():
        out[name] = {}
        for f in fields(cls):
            if f.default is not MISSING:
                out[name][f.name] = f.default
            elif f.default_factory is not MISSING:
                out[name][f.name] = f.default_factory()
            else:
                out[name][f.name] = MISSING
    return out


DEFAULTS = defaults()


def error_of(data: dict) -> str | None:
    """The first error in a config, or None if it is valid."""
    try:
        Gun.from_dict(data)
    except Exception as e:  # noqa: BLE001 - any failure to build the gun is an error to report
        return str(e) or type(e).__name__
    return None


def _norm(msg: str) -> str:
    return msg.lower()


def _mentions(msg: str, section: str, key: str) -> bool:
    m = _norm(msg)
    if f"{section}.{key}" in m:
        return True
    # A bare field name counts if it is specific (has an underscore), or the message names its section.
    bare = re.search(rf"(?<![a-z_.]){key}(?![a-z_])", m) is not None
    return bare and ("_" in key or f"{section}." in m)


def suspects(msg: str, data: dict) -> tuple[list, list]:
    """(fields the message points at, sections it points at), most specific first."""
    m = _norm(msg)
    named = []
    for phrase, keys in HINTS.items():
        if phrase in m:
            named += keys
    for section, key in re.findall(r"\b([a-z_]+)\.([a-z_]+)", m):
        if section in SECTIONS and key in DEFAULTS[section]:
            named.append((section, key))
    for section in SECTIONS:
        for key in DEFAULTS[section]:
            if (section, key) not in named and _mentions(msg, section, key):
                named.append((section, key))
    # Missing propellant fields: "[propellant] is missing force, covolume; ..."
    missing = re.search(r"\[propellant\] is missing ([a-z_, ]+);", m)
    if missing:
        named += [("propellant", k.strip()) for k in missing.group(1).split(",")]
    sections = [s for s in SECTIONS if re.search(rf"\b{s}\b", m) or f"[{s}]" in m]
    for phrase, secs in SECTION_WORDS.items():
        if phrase in m:
            sections += secs
    named = [k for k in dict.fromkeys(named) if k[0] in SECTIONS and k[1] in DEFAULTS[k[0]]]
    sections += [s for s, _ in named]
    return named, list(dict.fromkeys(sections))


def _scale(unit: str) -> float | None:
    return UNITS.get((unit or "").lower().split("/")[0])


def _ranges(msg: str) -> list[tuple[float, float]]:
    """The (low, high) ranges a message gives, in SI ("between 1 µs and 5 ms", "2 to 100 mm")."""
    out = []
    for pattern in RANGES:
        for lo, u1, hi, u2 in pattern.findall(msg):
            s2 = _scale(u2) or 1.0
            out.append((float(lo) * (_scale(u1) or s2), float(hi) * s2))
    return out


def _computed(msg: str, data: dict) -> list[tuple[str, str, object]]:
    """Fixes worked out for particular errors."""
    m, out = _norm(msg), []
    pr = data.get("propellant", {})
    if "form function must reach" in m:
        lam, mu = pr.get("form_lambda") or 0.0, pr.get("form_mu") or 0.0
        if 1 + lam + mu > 0:
            out.append(("propellant", "form_chi", 1.0 / (1 + lam + mu)))
        chi = pr.get("form_chi") or 1.0
        out.append(("propellant", "form_lambda", 1.0 / chi - 1 - mu))
    fit = re.search(r"charge \(([\d.]+) cm\^3 of solid\) does not fit in the chamber \(([\d.]+) cm\^3\)", m)
    if fit and pr.get("charge_mass"):
        solid, chamber = float(fit.group(1)), float(fit.group(2))
        out.append(("propellant", "charge_mass", pr["charge_mass"] * 0.9 * chamber / solid))
        if data.get("barrel", {}).get("chamber_shape") != "case":
            out.append(("barrel", "chamber_volume", solid * 1.25e-6))
    unknown = re.search(r"unknown keys in \[([a-z_]+)\]: ([a-z_, ]+)", m)
    if unknown:
        for key in unknown.group(2).split(","):
            out.append((unknown.group(1), key.strip(), DELETE))
    for section, key, raw in SUGGEST.findall(msg):
        if section in SECTIONS and key in DEFAULTS[section]:
            value = raw.strip('"') if raw.startswith('"') else raw == "true"
            out.append((section, key, value))
    return out


DELETE = object()   # a candidate that removes the key


def _candidates(section: str, key: str, msg: str, data: dict, reference: dict | None, thorough: bool):
    current = data.get(section, {}).get(key, MISSING)
    seen = []

    def offer(v):
        if v is MISSING or any(v is s or (type(v) is type(s) and v == s) for s in seen) or v == current:
            return
        seen.append(v)
        yield v

    if thorough and isinstance(current, (int, float)) and not isinstance(current, bool) and math.isfinite(current):
        for lo, hi in _ranges(msg):
            if current < lo:
                yield from offer(lo)
                yield from offer(lo + 0.01 * (hi - lo))
            elif current > hi:
                yield from offer(hi)
                yield from offer(hi - 0.01 * (hi - lo))
        if current < 0 and ("negative" in msg or "positive" in msg):
            yield from offer(-current)
    if reference:
        yield from offer(reference.get(section, {}).get(key, MISSING))
    default = DEFAULTS[section].get(key, MISSING)
    yield from offer(default)
    if thorough:
        if default is None:
            yield from offer(None)
        for option in CHOICES.get((section, key), ()):
            yield from offer(option)


def _apply(data: dict, section: str, key: str, value) -> dict:
    out = copy.deepcopy(data)
    sec = out.setdefault(section, {})
    if value is DELETE:
        sec.pop(key, None)
    else:
        sec[key] = value
    return out


def _progress(msg: str, new: str | None, changed: list, seen_msgs: set) -> bool:
    """A change helps if it clears the config, or moves to an error that isn't about what it changed."""
    if new is None:
        return True
    if new == msg or new in seen_msgs:
        return False
    return not any(_mentions(new, s, k) for s, k in changed)


def find_fix(data: dict, msg: str, reference: dict | None, seen_msgs: set, deadline: float):
    """[(section, key, value)] that clears or gets past this error, or None."""
    named, sections = suspects(msg, data)

    # Tier 1: worked-out fixes, then each named field with every candidate,
    # then the named fields together back to the reference (or the default).
    first = [[(s, k, v)] for s, k, v in _computed(msg, data)]
    for s, k in named:
        first += [[(s, k, v)] for v in _candidates(s, k, msg, data, reference, thorough=True)]
    if len(named) > 1:
        for source in (reference, None):
            together = []
            for s, k in named:
                v = source.get(s, {}).get(k, MISSING) if source else DEFAULTS[s].get(k, MISSING)
                if v is not MISSING and v != data.get(s, {}).get(k, MISSING):
                    together.append((s, k, v))
            if together:
                first.append(together)
    # Tier 2: every other field of the sections it names.
    second = [[(s, k, v)] for s in sections for k in DEFAULTS[s] if (s, k) not in named
              for v in _candidates(s, k, msg, data, reference, thorough=True)]
    # Tier 3: anything else, back to the reference or default.
    third = [[(s, k, v)] for s in SECTIONS if s not in sections for k in DEFAULTS[s]
             for v in _candidates(s, k, msg, data, reference, thorough=False)]

    # A change that clears the config wins; otherwise the first in the tier that gets past the error.
    for tier in (first, second, third):
        best = None
        for changes in tier:
            if time.monotonic() > deadline:
                return best
            trial = data
            for s, k, v in changes:
                trial = _apply(trial, s, k, v)
            new = error_of(trial)
            if new is None:
                return changes
            if best is None and _progress(msg, new, [(s, k) for s, k, _ in changes], seen_msgs):
                best = changes
        if best:
            return best
    return None


def check(data: dict, reference: dict | None = None) -> dict:
    """Every error in a config with its fix, and the config with all the fixes made.

    Returns {"errors": [{"message", "fix": [{"section", "key", "old", "new"}] or None}],
    "fixed": config, "complete": False if it gave up before the config was valid}.
    """
    data = copy.deepcopy(data)
    deadline = time.monotonic() + TIME_BUDGET
    errors, seen_msgs, seen_states = [], set(), set()
    for _ in range(STEP_BUDGET):
        msg = error_of(data)
        if msg is None:
            # As the gun works it out, so fields derived from others (a grain's form functions) come back filled in.
            return {"errors": errors, "fixed": {**data, **asdict(Gun.from_dict(data))}, "complete": True}
        state = json.dumps(data, sort_keys=True, default=str)
        fix = None if state in seen_states else find_fix(data, msg, reference, seen_msgs, deadline)
        seen_states.add(state)
        seen_msgs.add(msg)
        if fix is None:
            errors.append({"message": msg, "fix": None})
            return {"errors": errors, "fixed": data, "complete": False}
        record = []
        for s, k, v in fix:
            old = data.get(s, {}).get(k)
            data = _apply(data, s, k, v)
            record.append({"section": s, "key": k, "old": old, "new": None if v is DELETE else v,
                           "removed": v is DELETE})
        errors.append({"message": msg, "fix": record})
        if time.monotonic() > deadline:
            break
    complete = error_of(data) is None
    return {"errors": errors, "fixed": {**data, **asdict(Gun.from_dict(data))} if complete else data, "complete": complete}
