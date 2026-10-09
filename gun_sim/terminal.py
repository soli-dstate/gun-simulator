"""Terminal ballistics: what the projectile does to a steel plate it hits.

Three regimes, blended by how hard the penetrator is against the plate and how
fast it arrives:

* **Rigid penetration** (a hard core that stays whole: an AP round's hardened
  steel or tungsten carbide). The plate resists the nose with a pressure
  R + N rho_t V^2 (cavity expansion; N is the nose factor of the ogive), and
  the depth in a thick plate is Forrestal's

      P = m / (2 pi a^2 rho_t N) * ln(1 + N rho_t V^2 / R)

* **Eroding penetration** (a penetrator softer than the plate, or any rod at
  ordnance speed). The Alekseevskii-Tate model: the penetrator's nose erodes at
  the interface, where 0.5 rho_p (v - u)^2 + Y_p = 0.5 rho_t u^2 + R_t, while
  the rest of it is slowed by its own strength. A soft core (lead, copper) only
  gets in when 0.5 rho_p v^2 + Y_p beats R_t; below that it splashes on the face.

* **Cratering**: a bullet that splashes still leaves a crater. A share of its
  energy that grows as the fourth power of (0.5 rho_p v^2 + Y_p) / R_t digs a hemispherical crater
  against the plate's hardness.

A plate of thickness T is perforated once the depth in a thick plate, plus an
allowance for the plug or bulge pushed off its back face, reaches T along the
line of flight (T / cos of the obliquity). The residual velocity follows
Lambert and Jonas, v_r = m / (m + m_plug) sqrt(v^2 - v_bl^2).

RHAe (rolled homogeneous armour equivalent) is the same model run against RHA:
how much RHA the round would get through, and how much RHA the plate is worth
against this round (its thickness times the RHA depth over its own depth).

These are engineering estimates in the spirit of the textbook models, tuned to
a handful of published figures (.50 M2 AP: about 20 mm of RHA at 100 m; a
lead-core rifle bullet craters AR500 at close range without getting through);
treat them as such.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .config import CORE_MATERIALS, Gun

BHN_TO_PA = 9.80665e6     # Brinell hardness number (kgf/mm^2) to Pa
JACKET_DENSITY = 8900.0   # gilding metal


@dataclass(frozen=True)
class Armour:
    label: str
    hardness: float      # BHN
    density: float       # kg/m^3
    resistance: float    # Pa, the target's resistance R_t (Tate) and R (cavity expansion)


# Targets. AR500 is through-hardened abrasion-resistant plate (about 500 BHN) used for
# steel targets; RHA (MIL-DTL-12560, about 300 BHN) is the reference armour.
ARMOURS = {
    "ar500": Armour("AR500 steel", 500.0, 7850.0, 7.2e9),
    "rha": Armour("Rolled homogeneous armour (RHA)", 300.0, 7850.0, 5.0e9),
}
TARGETS = ("ar500",)   # the plates a target can be made of (RHA is the reference)


@dataclass(frozen=True)
class Penetrator:
    label: str
    density: float       # kg/m^3
    strength: float      # Pa, dynamic flow stress Y_p (Tate)
    hardness: float      # BHN


PENETRATORS = {
    "lead": Penetrator("lead (antimony-hardened)", 11340.0, 0.05e9, 8.0),
    "steel": Penetrator("mild steel", 7850.0, 0.9e9, 200.0),
    "copper": Penetrator("copper", 8960.0, 0.35e9, 90.0),
    "tungsten": Penetrator("tungsten heavy alloy", 17600.0, 1.6e9, 360.0),
    "hardened_steel": Penetrator("hardened steel", 7850.0, 2.0e9, 650.0),
    "tungsten_carbide": Penetrator("tungsten carbide", 14900.0, 4.0e9, 1300.0),
}
assert set(PENETRATORS) == set(CORE_MATERIALS)

RICOCHET_ANGLE = 70.0   # degrees from the plate's normal past which a hard core skips off steel
CRATER = 1.0e-3        # m: a dent this deep is a crater (the plate is damaged, and throws splash back)


def _smoothstep(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


@dataclass
class Core:
    """The part of the projectile that does the penetrating."""
    material: str
    mass: float          # kg
    diameter: float      # m
    nose_factor: float   # N: 1 for a flat face, 0.5 for a hemisphere, ~0.1 for a sharp ogive
    length: float        # m, of a cylinder of the same mass and diameter
    total_mass: float    # kg, the whole projectile that arrives (a jacket's energy cratering too)

    @property
    def props(self) -> Penetrator:
        return PENETRATORS[self.material]


def nose_factor(diameter: float, ogive_length: float, meplat: float) -> float:
    """Forrestal's N = (8 psi - 1) / (24 psi^2) for a tangent ogive of psi calibres radius, blunted by a meplat."""
    r = diameter / 2
    if ogive_length <= 1e-6:
        n = 1.0
    else:
        psi = max(0.5, (ogive_length**2 + r**2) / (2 * r) / diameter)
        n = (8 * psi - 1) / (24 * psi**2)
    flat = min(1.0, max(0.0, meplat / diameter)) ** 2
    return n + (1 - n) * flat


def core_of(gun: Gun) -> Core:
    """The penetrating core of the gun's projectile (an APFSDS's rod, or a bullet's core inside its jacket)."""
    p, d = gun.projectile, gun.barrel.bore_diameter
    material = CORE_MATERIALS[int(p.core_material)]
    rho = PENETRATORS[material].density
    if p.type == "apfsds":
        mass, dc, total = p.penetrator_mass, p.penetrator_diameter, p.penetrator_mass
        n = 0.1   # a rod's long, sharp nose
    else:
        total = p.mass
        t = min(p.jacket_thickness, 0.45 * d)
        dc = d - 2 * t
        # Mass shared between the core and the jacket round it, as for a cylinder.
        core_share = rho * dc**2 / (rho * dc**2 + JACKET_DENSITY * (d**2 - dc**2))
        mass = p.mass * core_share
        n = nose_factor(d, p.ogive_length or 0.0, p.meplat_diameter or 0.0)
        if p.hollow_point_diameter > 0 or p.exposed_core_length > 0:
            n = max(n, 0.6)   # an expanding nose opens up on the face
    length = mass / (rho * math.pi * dc**2 / 4)
    return Core(material, mass, dc, n, length, total)


def rigid_depth(core: Core, armour: Armour, v: float) -> float:
    """Depth (m) of a rigid penetrator in a thick plate (Forrestal)."""
    if v <= 0:
        return 0.0
    a = core.diameter / 2
    n, rho_t = core.nose_factor, armour.density
    return core.mass / (2 * math.pi * a * a * rho_t * n) * math.log1p(n * rho_t * v * v / armour.resistance)


def tate_depth(core: Core, armour: Armour, v: float) -> tuple[float, float]:
    """Depth (m) of an eroding penetrator in a thick plate (Alekseevskii-Tate), and the length of it left."""
    pen = core.props
    rho_p, rho_t, yp, rt = pen.density, armour.density, pen.strength, armour.resistance
    if 0.5 * rho_p * v * v + yp <= rt:
        return 0.0, core.length
    mu = rho_t / rho_p
    length, depth = core.length, 0.0
    dt = core.length / max(v, 1.0) / 4000
    while length > 1e-3 * core.length and v > 0:
        if 0.5 * rho_p * v * v + yp <= rt:
            break
        if abs(1 - mu) < 1e-9:
            u = v / 2 - (rt - yp) / (rho_p * v)
        else:
            u = (v - math.sqrt(max(mu * v * v + 2 * (rt - yp) * (1 - mu) / rho_p, 0.0))) / (1 - mu)
        if u <= 0:
            break
        depth += u * dt
        length -= (v - u) * dt
        v -= yp / (rho_p * max(length, 1e-9)) * dt
    return depth, max(length, 0.0)


def crater_depth(core: Core, armour: Armour, v: float) -> float:
    """Depth (m) of the crater a projectile that splashes on the face leaves."""
    pen = core.props
    s = min(1.0, (0.5 * pen.density * v * v + pen.strength) / armour.resistance)
    energy = 0.1 * s**4 * 0.5 * core.total_mass * v * v
    volume = energy / (armour.hardness * BHN_TO_PA)
    return (3 * volume / (2 * math.pi)) ** (1 / 3)


def rigid_share(core: Core, armour: Armour, v: float) -> float:
    """How far the penetrator behaves as a rigid body (1) rather than eroding (0).

    A core much harder than the plate stays whole; one about as hard shatters or
    erodes. Above about 1.3 km/s everything erodes, as long rods do.
    """
    h = core.props.hardness / armour.hardness
    return _smoothstep((h - 0.9) / 0.6) * _smoothstep((1500.0 - v) / 500.0)


@dataclass
class Hit:
    depth: float          # m into a thick plate
    regime: str           # "rigid", "eroding" or "splash"
    rigid: float          # rigid share
    limit_thickness: float  # m of plate (along the line of flight) it just gets through


def penetrate(core: Core, armour: Armour, v: float) -> Hit:
    """The projectile's hit on a thick plate of `armour` at `v` (m/s), square on."""
    w = rigid_share(core, armour, v)
    p_rigid = rigid_depth(core, armour, v)
    p_tate, _ = tate_depth(core, armour, v)
    p_crater = crater_depth(core, armour, v)
    soft = max(p_tate, p_crater)
    depth = w * p_rigid + (1 - w) * soft
    if w >= 0.5:
        regime = "rigid"
    else:
        regime = "eroding" if p_tate > p_crater else "splash"
    # The plug (rigid) or bulge (eroding) that comes off the back face.
    allowance = w * 0.5 * core.diameter + (1 - w) * (0.25 * core.diameter if p_tate > p_crater else 0.0)
    return Hit(depth, regime, w, depth + allowance)


def ballistic_limit(core: Core, armour: Armour, thickness: float, v_max: float) -> float | None:
    """Lowest impact speed (m/s) up to v_max that perforates `thickness` (m, along the line of flight)."""
    if penetrate(core, armour, v_max).limit_thickness < thickness:
        return None
    lo, hi = 0.0, v_max
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        if penetrate(core, armour, mid).limit_thickness >= thickness:
            hi = mid
        else:
            lo = mid
    return hi


def impact(gun: Gun, velocity: float, thickness: float, angle: float = 0.0, target: str = "ar500") -> dict:
    """What a hit at `velocity` (m/s) does to a plate of `target` steel `thickness` (m) thick,
    struck `angle` degrees off its normal, with its RHA equivalents."""
    if target not in ARMOURS:
        raise ValueError(f"unknown target material {target!r}; choose from {', '.join(ARMOURS)}")
    if thickness <= 0:
        raise ValueError("the plate's thickness must be positive")
    if not 0 <= angle < 85:
        raise ValueError("the angle off the plate's normal must be between 0 and 85 degrees")
    armour, rha = ARMOURS[target], ARMOURS["rha"]
    core = core_of(gun)
    los = thickness / math.cos(math.radians(angle))
    hit = penetrate(core, armour, velocity)
    hit_rha = penetrate(core, rha, velocity)
    perforated = hit.limit_thickness >= los
    ricochet = angle >= RICOCHET_ANGLE
    if ricochet:
        perforated = False
    residual = 0.0
    v_bl = ballistic_limit(core, armour, los, velocity) if perforated else None
    if perforated and v_bl is not None:
        plug = armour.density * math.pi * (core.diameter / 2) ** 2 * los
        residual = core.mass / (core.mass + plug) * math.sqrt(max(velocity**2 - v_bl**2, 0.0))
    # How much RHA this plate is worth against this round.
    if hit.depth > 0.5e-3 and hit_rha.depth > 0:
        efficiency = min(3.0, max(1.0, hit_rha.depth / hit.depth))
    else:
        efficiency = armour.resistance / rha.resistance
    energy = 0.5 * core.total_mass * velocity**2
    if ricochet:
        verdict = "ricochet"
    elif perforated:
        verdict = "perforated"
    elif hit.depth >= CRATER:
        verdict = "cratered"
    else:
        verdict = "stopped"
    return {
        "target": target,
        "target_label": armour.label,
        "velocity": velocity,
        "energy": energy,
        "thickness": thickness,
        "angle": angle,
        "line_of_sight": los,
        "core": {"material": core.material, "label": core.props.label, "mass": core.mass,
                 "diameter": core.diameter, "length": core.length, "nose_factor": core.nose_factor},
        "depth": hit.depth,
        "regime": hit.regime,
        "rigid_share": hit.rigid,
        "limit_thickness": hit.limit_thickness,
        "perforated": perforated,
        "ricochet": ricochet,
        "verdict": verdict,
        "ballistic_limit": v_bl,
        "residual_velocity": residual,
        "rha_depth": hit_rha.depth,
        "rha_limit_thickness": hit_rha.limit_thickness,
        "plate_rhae": los * efficiency,
        "efficiency": efficiency,
    }
