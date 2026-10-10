"""Easy mode: build a whole gun from a cartridge, a load, a kind of gun and a barrel length.

The person picks what they would pick in a gun shop. The builder does the rest:

* the case, bullet and bore come from the cartridge library (cartridges.py);
* the chamber volume is the case's powder space under the seated bullet;
* the powder's burn rate is tuned (lumped model, bisection) so the load makes
  its published velocity from its published barrel, and the result is then
  fired from the barrel chosen, so a short barrel loses velocity as it should;
* the twist is the cartridge's standard one unless that leaves the bullet
  under-stabilised (Miller Sg < 1.3), when a faster one is worked out;
* the action, feed, trigger and stock come from a preset of that kind of gun,
  scaled to the cartridge's recoil momentum, and its one tuning knob (the gas
  port, a blowback's bolt mass, or the recoil spring) is tuned until the action
  cycles with the bolt reaching its stop at a healthy speed.

Everything it worked out is listed in plain words (`notes`), and the gun it
returns is an ordinary config the expert editor can take further.
"""

from __future__ import annotations

import copy
import math
import sys
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from . import action, lumped, projectiles, rifling
from .cartridges import CARTRIDGES, GRAIN, KINDS, MM, POWDERS, Cartridge, Load
from .config import Gun
from .exterior import LB_IN2

if getattr(sys, "frozen", False):
    CONFIG_DIR = Path(sys._MEIPASS) / "configs"
else:
    CONFIG_DIR = Path(__file__).resolve().parents[1] / "configs"

INCH = 0.0254
GAS_SPEED = 1250.0   # m/s, the powder gas's share of the recoil momentum, per kg of charge (SAAMI-style)
BLOWDOWN = 0.025     # s of blowdown the action sees, as the UI's shots


@dataclass(frozen=True)
class Platform:
    label: str
    blurb: str
    template: str                 # preset the action, feed, trigger and stock come from
    kinds: tuple[str, ...]        # cartridge kinds it takes
    style: str | None = None      # appearance, if not the template's
    mode: str | None = None       # trigger mode, if not the template's
    action: str | None = None     # action type, if not the template's
    feed: str | None = None       # feed type, if not the template's
    capacity: int | None = None   # rounds, for the template's cartridge (scaled to others)
    handgun: bool = False


PLATFORMS: dict[str, Platform] = {
    "pistol_striker": Platform("Striker-fired pistol", "Polymer frame, short recoil, striker (Glock-style).",
                               "glock_17", ("pistol",), handgun=True, capacity=17),
    "pistol_1911": Platform("Single-action pistol", "Steel frame, tilting barrel, hammer (1911-style).",
                            "colt_1911", ("pistol",), handgun=True, capacity=7),
    "pistol_dasa": Platform("DA/SA pistol", "Open-top slide, locking block, double-action first shot (Beretta-style).",
                            "beretta_m9", ("pistol",), handgun=True, capacity=15),
    "pcc": Platform("Pistol-calibre carbine", "Semi-automatic straight blowback in an AR-style rifle.",
                    "example_roller_delayed", ("pistol",), style="ar15", mode="semi", action="blowback",
                    feed="double_stack", capacity=30),
    "smg": Platform("Submachine gun", "Fully automatic straight blowback.",
                    "example_roller_delayed", ("pistol",), style="ar15", mode="auto", action="blowback",
                    feed="double_stack", capacity=30),
    "revolver_da": Platform("Double-action revolver", "Swing-out cylinder, every pull cocks and turns it.",
                            "colt_anaconda", ("revolver",), handgun=True, capacity=6),
    "revolver_sa": Platform("Single-action revolver", "Loading gate; cock the hammer with the thumb.",
                            "colt_saa", ("revolver",), handgun=True, capacity=6),
    "bolt": Platform("Bolt-action rifle", "Worked by hand: the simplest and most accurate.",
                     "example_rifle", ("intermediate", "rifle", "magnum", "heavy"), capacity=5),
    "ar_semi": Platform("AR-style semi-automatic", "Direct impingement, a shot per pull (AR-15 / AR-10).",
                        "m4a1", ("intermediate", "rifle"), mode="semi", capacity=30),
    "ar_auto": Platform("M4-style select fire", "Direct impingement, fully automatic (M4 / M16).",
                        "m4a1", ("intermediate", "rifle"), mode="auto", capacity=30),
    "ak": Platform("Kalashnikov-pattern rifle", "Long-stroke gas piston, fully automatic (AK).",
                   "akm", ("intermediate", "rifle"), capacity=30),
    "battle_rifle": Platform("Gas-piston rifle", "Short-stroke gas piston, semi-automatic (FAL / M14 / Barrett).",
                             "example_gas_rifle", ("intermediate", "rifle", "magnum", "heavy"), mode="semi",
                             feed="double_stack", capacity=20),
    "roller": Platform("Roller-delayed rifle", "Delayed blowback with rollers, fully automatic (G3 / MP5).",
                       "example_roller_delayed", ("pistol", "intermediate", "rifle"), capacity=20),
    "mg": Platform("Belt-fed machine gun", "Gas operated from a belt, fully automatic.",
                   "example_belt_fed", ("intermediate", "rifle"), capacity=100),
    "chain_gun": Platform("Chain gun", "Motor-driven bolt on a mount (Mk44 Bushmaster II).",
                          "mk44_bushmaster_ii", ("cannon",)),
    "tank_gun": Platform("Tank gun", "Sliding-wedge breech on a recoil mount (Rh-120).",
                         "rh120_l55", ("cannon",)),
}

# Barrel lengths offered (min, max, default) in mm, by cartridge kind.
BARRELS = {
    "pistol": (60, 450, 114),
    "revolver": (50, 260, 152),
    "intermediate": (180, 610, 368),
    "rifle": (300, 760, 559),
    "magnum": (500, 800, 660),
    "heavy": (500, 1300, 1143),
}
HANDGUN_BARRELS = {"pistol": (60, 200, 114)}
CARBINE_BARRELS = {"pistol": (100, 450, 229)}


def barrel_range(cartridge: Cartridge, platform_id: str) -> tuple[float, float, float]:
    """Barrel lengths (min, max, default) in mm this gun can be built with."""
    if cartridge.template:
        g = _template(cartridge.template)
        length = (g.barrel.travel + g.seat) / MM
        return round(0.6 * length), round(1.3 * length), round(length)
    plat = PLATFORMS[platform_id]
    if cartridge.kind == "pistol":
        return (HANDGUN_BARRELS if plat.handgun else CARBINE_BARRELS)["pistol"]
    return BARRELS[cartridge.kind]


def platforms_for(cartridge: Cartridge) -> list[str]:
    if cartridge.template:
        return [k for k, p in PLATFORMS.items() if p.template == cartridge.template]
    return [k for k, p in PLATFORMS.items() if cartridge.kind in p.kinds and p.template not in
            ("mk44_bushmaster_ii", "rh120_l55")]


@lru_cache(maxsize=None)
def _template(name: str) -> Gun:
    return Gun.load(CONFIG_DIR / f"{name}.toml")


@lru_cache(maxsize=None)
def _template_momentum(name: str) -> float:
    """Recoil momentum (N s, SAAMI-style) of a preset's own round, the yardstick its action is sized to."""
    g = copy.deepcopy(_template(name))
    r = lumped.simulate(g)
    return g.projectile.mass * r.muzzle_velocity + g.propellant.charge_mass * GAS_SPEED


def schema() -> dict:
    """What the easy-mode form offers: the cartridges, their loads, and the guns each fits."""
    out = []
    for c in CARTRIDGES.values():
        loads = []
        for ld in c.loads:
            if c.template and ld.design:
                g = _template_load(c.template, ld.design)
                loads.append({"id": ld.id, "name": ld.name, "kind": ld.kind, "mass": g.projectile.mass,
                              "velocity": None, "barrel": None, "core": g.projectile.insert_material or
                              _core_name(g.projectile.core_material)})
            elif c.template:
                p = _template(c.template).projectile
                loads.append({"id": ld.id, "name": _template(c.template).name, "kind": ld.kind, "mass": p.mass,
                              "velocity": None, "barrel": None, "core": _core_name(p.core_material)})
            else:
                loads.append({"id": ld.id, "name": ld.name, "kind": ld.kind, "mass": ld.mass,
                              "velocity": ld.velocity, "barrel": ld.barrel_mm * MM,
                              "core": ld.fills.get("insert_material") or ld.core})
        out.append({
            "id": c.id, "metric": c.metric, "imperial": c.imperial, "label": c.label, "aliases": list(c.aliases),
            "kind": c.kind, "kind_label": KINDS[c.kind], "bore": c.bore * MM, "max_pressure": c.max_pressure or None,
            "standard": c.standard, "twist": c.twist * INCH, "loads": loads,
            "platforms": [{"id": k, "barrel": [v * MM for v in barrel_range(c, k)]} for k in platforms_for(c)],
        })
    return {
        "cartridges": out,
        "kinds": KINDS,
        "platforms": {k: {"label": p.label, "blurb": p.blurb, "handgun": p.handgun} for k, p in PLATFORMS.items()},
        "devices": {"none": "None", "flash_hider": "Flash hider", "brake": "Muzzle brake", "suppressor": "Suppressor"},
    }


def _core_name(index) -> str:
    from .config import CORE_MATERIALS
    return CORE_MATERIALS[int(index)]


@lru_cache(maxsize=None)
def _template_load(name: str, design_key: str) -> Gun:
    """A preset gun firing one of the projectile designs instead of its own round, seated where its own was."""
    g = copy.deepcopy(_template(name))
    data = asdict(g)
    p = data["projectile"] = projectiles.fit_design(design_key, g)
    if p["type"] in ("apfsds", "apds"):
        offset = p["sabot_offset"] or 0.0
    else:
        offset = p["boom_length"] if p["type"] == "finned" else 0.0
    data["case"]["overall_length"] = g.seat + p["length"] - offset
    return Gun.from_dict(data)


# ---------------------------------------------------------------------------
# building
# ---------------------------------------------------------------------------

def _si_case(c: Cartridge, ld: Load) -> dict:
    case = {k: (v if k == "shoulder_angle" else v * MM) for k, v in c.case.items()}
    if ld.oal:
        case["overall_length"] = ld.oal * MM
    case.update(material="brass", combustible=False, stub_length=None)
    return case


def _projectile(c: Cartridge, ld: Load, template: Gun) -> dict:
    t = template.projectile
    bc = ld.bc * LB_IN2 if ld.bc else None
    p = {
        "mass": ld.mass, "shot_start_pressure": t.shot_start_pressure, "bore_resistance": t.bore_resistance,
        "engraving_pressure": t.engraving_pressure if c.kind == "revolver" else 0.0,
        "length": ld.length * MM, "ogive_length": ld.ogive * MM, "meplat_diameter": ld.meplat * MM,
        "boat_tail_length": ld.boat_tail * MM, "boat_tail_angle": 9.0 if ld.boat_tail else 0.0,
        "jacket_thickness": ld.jacket * MM, "core_material": ld.core,
        "exposed_core_length": ld.exposed_core * MM,
        "hollow_point_diameter": ld.hollow_point[0] * MM, "hollow_point_depth": ld.hollow_point[1] * MM,
        "drag_model": ld.drag, "ballistic_coefficient": bc,
    }
    # What is inside it: lengths are given in mm.
    for k, v in ld.fills.items():
        p[k] = v * MM if k in projectiles._LENGTHS and isinstance(v, (int, float)) else v
    # A crimp groove at the case mouth on rifle and revolver bullets.
    # It has to sit on the bearing surface, between the boat tail and the ogive.
    mouth = ld.length - ((ld.oal or c.case["overall_length"]) - c.case["length"])
    lo, hi = ld.boat_tail + 0.8, ld.length - ld.ogive - 0.8
    groove = min(max(mouth - 0.6, lo), hi)
    if c.kind not in ("pistol",) and ld.kind in ("fmj", "ap", "sp", "lead", "tracer", "api", "apit", "mp") and lo < hi:
        p.update(cannelure_position=groove * MM, cannelure_width=1.0 * MM,
                 cannelure_depth=(0.25 if ld.jacket == 0 else 0.1) * MM)
    return p


def _scaled_action(t: Gun, k: float, bore_ratio: float, plat: Platform, travel: float, oal: float) -> dict:
    a = asdict(t.action)
    # The stroke grows or shrinks with the round it has to clear; a blowback runs a long one (a slower rate).
    if plat.action == "blowback":
        a["bolt_travel"] = 3.0 * oal
    elif t.action.bolt_travel is not None:
        a["bolt_travel"] = max(t.action.bolt_travel + oal - t.case.overall_length, oal + 8e-3)
    root = math.sqrt(k)
    a["gun_mass"] = max(0.4, t.action.gun_mass * k ** (0.5 if plat.handgun else 0.6))
    if plat.action == "blowback":
        # A straight blowback's bolt holds the breech shut by its mass alone: about 0.45 kg for a 9 mm.
        p9 = 8.04e-3 * 360 + 0.29e-3 * GAS_SPEED
        ratio = k * _template_momentum(plat.template) / p9
        a.update(type="blowback", bolt_mass=0.45 * ratio, spring_preload=45.0 * math.sqrt(ratio),
                 spring_rate=350.0 * math.sqrt(ratio), bolt_head_mass=None, delay_ratio=None, unlock_travel=None,
                 hammer=False, friction=4.0)
        a["gun_mass"] = max(2.4, 3.0 * math.sqrt(ratio))
    else:
        a["bolt_mass"] = t.action.bolt_mass * root
        if t.action.bolt_head_mass is not None:
            a["bolt_head_mass"] = t.action.bolt_head_mass * root
        a["spring_preload"] = t.action.spring_preload * root
        a["spring_rate"] = t.action.spring_rate * root
    a["bolt_mass"] = min(a["bolt_mass"], 0.45 * a["gun_mass"])
    a["feed_force"] = t.action.feed_force * k**0.3
    a["barrel_mass"] = None   # from the barrel's steel
    a["cylinder_radius"] = None
    a["cylinder_mass"] = t.action.cylinder_mass * bore_ratio**2
    a["piston_diameter"] = t.action.piston_diameter * bore_ratio
    a["gas_volume"] = t.action.gas_volume * root
    if t.action.gas_port_position is not None:
        frac = t.action.gas_port_position / t.barrel.travel
        a["gas_port_position"] = frac * travel
        if t.action.gas_tube_length is not None:
            a["gas_tube_length"] = max(0.05, t.action.gas_tube_length + a["gas_port_position"] - t.action.gas_port_position)
    a["gas_port_diameter"] = t.action.gas_port_diameter * bore_ratio
    return a



def _capacity(plat: Platform, t: Gun, c: Cartridge) -> int | None:
    if plat.capacity is None:
        return None
    if plat.feed in ("belt", "dual_belt") or t.feed.type in ("belt", "dual_belt", "cylinder"):
        return plat.capacity
    ratio = (t.case.base_diameter / (c.case["base_diameter"] * MM)) ** 1.5
    n = plat.capacity * ratio
    if c.kind == "heavy":
        n = min(n, 10)
    if not plat.handgun:
        n = min(n, plat.capacity)   # a longer magazine than the usual would not fit the gun
    return max(3, int(round(n / 5) * 5) if n >= 15 else int(round(n)))


def _lumped_dt(travel: float, velocity: float, steps: int = 4000) -> float:
    t_bore = 2 * travel / max(velocity, 100.0)
    return float(min(2.5e-7, max(2e-8, t_bore / steps)))


def _chamber_pressure(r) -> np.ndarray:
    """The lumped model's chamber pressure as the fluid model (and a chamber gauge) would see it.

    The lumped model's Lagrange gradient puts too much pressure at the breech; a quarter of its
    breech pressure and three quarters of its base pressure match the fluid model's breech
    pressure to a few percent across the presets.
    """
    return 0.25 * np.asarray(r.breech_pressure) + 0.75 * np.asarray(r.base_pressure)


def _velocity(gun: Gun) -> tuple[float, float, float]:
    """(muzzle velocity, peak chamber pressure, burnt share) of the lumped model; NaN if it went unstable."""
    try:
        r = lumped.simulate(gun)
    except (ValueError, FloatingPointError, ZeroDivisionError):
        return math.nan, math.nan, math.nan
    if not r.left_muzzle:
        return 0.0, float(np.max(r.breech_pressure)), r.burnt_at_muzzle
    chamber = _chamber_pressure(r)
    return r.muzzle_velocity, float(np.max(chamber)), r.burnt_at_muzzle


def _tune_burn_rate(gun: Gun, target: float) -> float:
    """Burn-rate coefficient a (Vieille) that makes the target muzzle velocity, by bisection on log a.

    A slow powder that would leave the bullet in the bore is cut off after ten times the
    time the bullet should take, and coarse steps do for the search.
    """
    t_bore = 2 * gun.barrel.travel / target
    gun.solver.max_time, gun.solver.lumped_dt = 10 * t_bore, _lumped_dt(gun.barrel.travel, target, 1200)
    lo, hi = math.log(1e-10), math.log(3e-6)
    for _ in range(13):
        mid = 0.5 * (lo + hi)
        gun.propellant.burn_rate_coeff = math.exp(mid)
        v, _, _ = _velocity(gun)
        if not math.isfinite(v) or v > target:
            hi = mid
        else:
            lo = mid
    gun.propellant.burn_rate_coeff = math.exp(0.5 * (lo + hi))
    return gun.propellant.burn_rate_coeff


KNOBS = {
    # action type: (field, + if raising it speeds the action up)
    "gas": ("gas_port_diameter", +1),
    "direct_impingement": ("gas_port_diameter", +1),
    "gas_delayed": ("gas_port_diameter", +1),
    "blowback": ("bolt_mass", -1),
    "short_recoil": ("spring", -1),
    "roller_delayed": ("spring", -1),
    "lever_delayed": ("spring", -1),
}
KNOB_LABELS = {"gas_port_diameter": "gas port", "bolt_mass": "bolt mass", "spring": "recoil spring"}


def _cycle(gun: Gun, shot) -> tuple[str, float, object]:
    try:
        a = action.simulate(gun, shot)
    except (ValueError, FloatingPointError, ZeroDivisionError):
        return "error", 0.0, None
    return a.status, (a.rear_speed or 0.0), a


def _tune_action(gun: Gun, shot, target_speed: float) -> tuple[float, object, str]:
    """Tune the action's knob until it cycles with the bolt reaching its stop near `target_speed` m/s.

    Returns (multiplier applied, the action result, what was tuned); multiplier 1 if nothing needed doing.
    """
    kind = gun.action.type
    if kind not in KNOBS:
        status, _, res = _cycle(gun, shot)
        return 1.0, res, ""
    field_name, sign = KNOBS[kind]
    a = gun.action
    base = {"spring": (a.spring_preload, a.spring_rate)}.get(field_name, getattr(a, field_name, None))

    def apply(x: float):
        if field_name == "spring":
            a.spring_preload, a.spring_rate = base[0] * x, base[1] * x
        elif field_name == "bolt_mass":
            a.bolt_mass = min(base * x, 0.45 * a.gun_mass)
        else:
            setattr(a, field_name, base * x)

    best = None   # (|speed - target|, x, result)

    def evaluate(x: float) -> float:
        nonlocal best
        apply(x)
        status, speed, res = _cycle(gun, shot)
        ok = status == "cycled"
        if ok and (best is None or abs(speed - target_speed) < best[0]):
            best = (abs(speed - target_speed), x, res)
        return speed

    speed = evaluate(1.0)
    if best is not None and 0.6 * target_speed <= speed <= 1.6 * target_speed:
        apply(1.0)
        return 1.0, best[2], field_name
    lo, hi = math.log(0.2), math.log(5.0)
    for _ in range(9):
        mid = 0.5 * (lo + hi)
        s = evaluate(math.exp(mid))
        faster = s > target_speed
        # Too fast: move the knob the way that slows it.
        if (faster and sign > 0) or (not faster and sign < 0):
            hi = mid
        else:
            lo = mid
    if best is None:
        apply(1.0)
        status, _, res = _cycle(gun, shot)
        return 1.0, res, field_name
    apply(best[1])
    return best[1], best[2], field_name


def design(payload: dict) -> dict:
    """Build a gun. payload: cartridge, load, platform, barrel_length (m), device, twist ("auto" or m per turn),
    capacity (rounds, optional), name (optional)."""
    cid = payload.get("cartridge")
    if cid not in CARTRIDGES:
        raise ValueError(f"unknown cartridge {cid!r}")
    c = CARTRIDGES[cid]
    ld = c.load(payload.get("load"))
    pid = payload.get("platform") or platforms_for(c)[0]
    if pid not in platforms_for(c):
        raise ValueError(f"a {PLATFORMS[pid].label.lower() if pid in PLATFORMS else pid} can't take {c.metric}")
    plat = PLATFORMS[pid]
    lo, hi, default = barrel_range(c, pid)
    barrel = float(payload.get("barrel_length") or default * MM)
    if not lo * MM * 0.999 <= barrel <= hi * MM * 1.001:
        raise ValueError(f"barrel length must be between {lo} and {hi} mm for this gun")
    device = payload.get("device") or "none"
    notes: list[dict] = []

    if c.template:
        gun = _from_template(c, ld, plat, barrel, device, notes)
    else:
        gun = _build(c, ld, plat, barrel, device, payload, notes)
    if payload.get("name"):
        gun.name = str(payload["name"])
    gun.validate()
    return {"gun": asdict(gun), "notes": notes, "prediction": _predict(gun, c, notes)}


def _note(notes: list, title: str, text: str, kind: str = "info"):
    notes.append({"title": title, "text": text, "kind": kind})


def _from_template(c: Cartridge, ld: Load, plat: Platform, barrel: float, device: str, notes: list) -> Gun:
    gun = copy.deepcopy(_template_load(plat.template, ld.design) if ld.design else _template(plat.template))
    if ld.design:
        _note(notes, "Projectile", f"{ld.name}: {projectiles.DESIGNS[ld.design].blurb} Its mass is what its parts "
              f"weigh ({gun.projectile.mass:.3g} kg), seated where the preset's own round is; the charge is the preset's.")
    old = gun.barrel.travel
    gun.barrel.travel = barrel - gun.seat
    if gun.barrel.evacuator_position:
        gun.barrel.evacuator_position *= gun.barrel.travel / old
    gun.muzzle_device.type = device
    gun.name = f"{plat.label} ({c.metric})"
    _note(notes, "Built from the preset", f"{c.metric} is a complete gun system: its round, breech and mount come "
          f"from the {_template(plat.template).name} preset, with the barrel cut to {barrel / MM:.0f} mm.")
    return gun


def _build(c: Cartridge, ld: Load, plat: Platform, barrel: float, device: str, payload: dict, notes: list) -> Gun:
    t = _template(plat.template)
    bore = c.bore * MM
    bore_ratio = bore / t.barrel.bore_diameter
    case = _si_case(c, ld)
    proj = _projectile(c, ld, t)
    seat = case["overall_length"] - proj["length"]
    if seat < case["head_thickness"] + 1 * MM:
        case["overall_length"] = proj["length"] + case["head_thickness"] + 1 * MM
        seat = case["overall_length"] - proj["length"]
    travel = barrel - seat
    if travel < 3 * bore:
        raise ValueError("the barrel is too short for this round")

    data = asdict(t)
    data["name"] = f"{plat.label} ({c.metric})"
    data["case"] = case
    data["projectile"] = proj
    data["barrel"] = {
        **asdict(t.barrel),
        "bore_diameter": bore, "travel": travel, "chamber_volume": 1e-3, "chamber_shape": "cylinder",
        "twist": c.twist * INCH, "groove_depth": (t.barrel.groove_depth or 0.1e-3) * bore_ratio,
        "breech_diameter": (t.barrel.breech_diameter or 30e-3) * bore_ratio,
        "muzzle_diameter": (t.barrel.muzzle_diameter or 16e-3) * bore_ratio,
        "cylinder_length": None,
    }
    powder = dict(POWDERS[c.kind])
    data["propellant"] = {**powder, "charge_mass": ld.charge, "burn_rate_coeff": 1e-8}
    data["ignition"] = {**asdict(t.ignition), "strike_energy": c.primer_energy}
    data["muzzle_device"] = {"type": device}
    data["solver"] = {**asdict(t.solver), "gas_port_2d": False}
    k = (ld.mass * ld.velocity + ld.charge * GAS_SPEED) / _template_momentum(plat.template)
    data["action"] = _scaled_action(t, k, bore_ratio, plat, travel, case["overall_length"])
    if plat.mode:
        data["trigger"] = {**asdict(t.trigger), "mode": plat.mode}
    if plat.style:
        data["appearance"] = {"style": plat.style}
    feed = {**asdict(t.feed), "capacity": payload.get("capacity") or _capacity(plat, t, c),
            "spring_empty": None, "spring_full": None, "follower_mass": None, "feed_angle": None}
    if plat.feed:
        feed["type"] = plat.feed
    data["feed"] = feed

    # The chamber is the case's powder space under the seated bullet.
    gun = Gun.from_dict(data)
    space = gun.powder_space
    gun.barrel.chamber_volume = space
    solid = ld.charge / gun.propellant.density
    if solid > 0.92 * space:
        gun.propellant.charge_mass = 0.92 * space * gun.propellant.density
        _note(notes, "Charge trimmed", f"The listed {ld.charge_gr:.1f} gr would overfill this case; "
              f"it is cut to {gun.propellant.charge_mass / GRAIN:.1f} gr.", "warn")
    fill = gun.propellant.charge_mass / gun.propellant.density / space
    _note(notes, "Chamber", f"The case holds {space * 1e6:.2f} cm³ under the seated bullet "
          f"({space * 1e6 / 0.0648:.0f} gr of water), so the solver's chamber is that big. "
          f"The {gun.propellant.charge_mass / GRAIN:.1f} gr charge fills {fill * 100:.0f} % of it.")

    # Powder: tuned at the load's reference barrel to its published velocity.
    ref = copy.deepcopy(gun)
    ref.barrel.travel = max(ld.barrel_mm * MM - seat, 3 * bore)
    coeff = _tune_burn_rate(ref, ld.velocity)
    v_ref, p_ref, _ = _velocity(ref)
    for _ in range(3):
        if v_ref >= 0.5 * ld.velocity:
            break
        # Packed too tight for the gas to fit (its covolume): a lighter charge.
        ref.propellant.charge_mass *= 0.92
        gun.propellant.charge_mass = ref.propellant.charge_mass
        coeff = _tune_burn_rate(ref, ld.velocity)
        v_ref, p_ref, _ = _velocity(ref)
        _note(notes, "Charge lightened", f"The full charge leaves no room for its gas; it is cut to "
              f"{gun.propellant.charge_mass / GRAIN:.1f} gr.", "warn")
    if v_ref < 0.97 * ld.velocity:
        _note(notes, "Short of the published velocity", f"Even burnt at once, this charge only makes {v_ref:.0f} m/s "
              f"from {ld.barrel_mm:.0f} mm (published: {ld.velocity:.0f} m/s).", "warn")
    gun.propellant.burn_rate_coeff = coeff
    _note(notes, "Powder burn rate", f"Tuned so the load makes its published {ld.velocity:.0f} m/s from a "
          f"{ld.barrel_mm:.0f} mm barrel (burn-rate coefficient {coeff:.3g} (m/s)/Paⁿ, n = "
          f"{gun.propellant.burn_rate_exp:.2f}). Your barrel then gives what it gives.")

    # Twist: the standard one, unless the bullet needs faster to be stable.
    sg = rifling.stability(gun, ld.velocity)
    twist_in = payload.get("twist")
    if twist_in not in (None, "", "auto"):
        gun.barrel.twist = float(twist_in)
        _note(notes, "Twist", f"1 in {abs(gun.barrel.twist) / INCH:.1f}\" as set: Sg {rifling.stability(gun, ld.velocity):.2f}.")
    elif c.twist and sg < 1.3:
        twist = abs(gun.barrel.twist) * math.sqrt(sg / 1.6)
        twist = math.floor(twist / INCH * 2) / 2 * INCH
        gun.barrel.twist = math.copysign(twist, c.twist)
        _note(notes, "Twist", f"The standard 1 in {abs(c.twist):g}\" leaves this {ld.mass_gr:.0f} gr bullet "
              f"under-stabilised (Sg {sg:.2f}), so the barrel gets 1 in {twist / INCH:g}\" "
              f"(Sg {rifling.stability(gun, ld.velocity):.2f}).")
    elif c.twist:
        _note(notes, "Twist", f"Standard 1 in {abs(c.twist):g}\"{' left-hand' if c.twist < 0 else ''}: "
              f"Sg {sg:.2f} at the muzzle ({'stable' if sg >= 1.4 else 'marginal'}).")

    gun.solver.lumped_dt = _lumped_dt(travel, ld.velocity)
    capacity = gun.feed.capacity
    if capacity:
        _note(notes, "Feed", f"{gun.feed.type.replace('_', ' ')}, {capacity} rounds.")
    return gun


def _predict(gun: Gun, c: Cartridge, notes: list) -> dict:
    """Quick estimate of the finished gun (lumped model) and its action tuned to cycle."""
    r = lumped.simulate(gun, blowdown_time=BLOWDOWN)
    if not r.left_muzzle:
        _note(notes, "Stuck", "The bullet does not leave this barrel: the barrel is too long for the charge.", "bad")
        return {"left_muzzle": False}
    chamber = _chamber_pressure(r)
    pressure = float(np.max(chamber))
    target = 6.0 if gun.appearance.style in ("1911", "beretta", "polymer") else 3.5 if gun.action.type == "blowback" else 5.0
    knob, res, field_name = _tune_action(gun, r, target)
    if field_name and res is not None and res.status == "cycled":
        a = gun.action
        if knob != 1.0:
            what = {"gas_port_diameter": f"a {a.gas_port_diameter / MM:.2f} mm gas port",
                    "bolt_mass": f"a {a.bolt_mass * 1e3:.0f} g bolt",
                    "spring": f"a {a.spring_preload:.0f} N recoil spring ({a.spring_rate / 1e3:.2f} N/mm)"}[field_name]
            _note(notes, "Action tuned", f"The {KNOB_LABELS[field_name]} was resized until the action cycles "
                  f"cleanly: {what}, the bolt reaching its stop at {res.rear_speed or 0:.1f} m/s.")
        else:
            _note(notes, "Action", f"Cycles cleanly as scaled, the bolt reaching its stop at {res.rear_speed or 0:.1f} m/s.")
    elif field_name:
        status = res.status if res is not None else "error"
        _note(notes, "Action may not cycle", f"No setting of the {KNOB_LABELS[field_name]} made it cycle cleanly "
              f"({status}). Fine-tune it in Expert mode.", "warn")
    energy = 0.5 * gun.flight_mass * r.muzzle_velocity**2
    if c.max_pressure:
        ratio = pressure / c.max_pressure
        if ratio > 1.10:
            _note(notes, "Over pressure", f"Peak chamber pressure, estimated at {pressure / 1e6:.0f} MPa, is "
                  f"{(ratio - 1) * 100:.0f} % over the {c.standard} maximum.", "warn")
    sg = rifling.stability(gun, r.muzzle_velocity) if gun.barrel.twist else 0.0
    out = {
        "left_muzzle": True,
        "muzzle_velocity": r.muzzle_velocity,
        "muzzle_energy": energy,
        "peak_pressure": pressure,
        "max_pressure": c.max_pressure or None,
        "standard": c.standard,
        "burnt": r.burnt_at_muzzle,
        "muzzle_time": r.muzzle_time,
        "stability": sg,
        "twist": gun.barrel.twist,
        "gun_mass": gun.action.gun_mass,
        "recoil_impulse": None, "free_recoil_energy": None, "status": None, "cyclic_rate": None,
    }
    if res is not None:
        out.update(recoil_impulse=res.impulse, free_recoil_energy=res.free_recoil_energy,
                   free_recoil_velocity=res.free_recoil_velocity, status=res.status, cyclic_rate=res.cyclic_rate)
    return out
