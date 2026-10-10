"""Terminal ballistics: what the projectile does to what it hits.

**Plates** (AR500, RHA, mild steel, aluminium armour). The kinetic part is
three regimes, blended by how hard the penetrator is against the plate and how
fast it arrives:

* **Rigid penetration** (a hard core that stays whole: an AP round's hardened
  steel or tungsten carbide). The plate resists the nose with a pressure
  R + N rho_t V^2 (cavity expansion; N is the nose factor of the ogive), and
  the depth in a thick plate is Forrestal's

      P = m / (2 pi a^2 rho_t N) * ln(1 + N rho_t V^2 / R)

  A brittle core breaks up (shatters) above a speed that falls with the plate's
  hardness; a soft penetrating cap spreads the blow and raises it (APC, APCBC).

* **Eroding penetration** (a penetrator softer than the plate, or any rod at
  ordnance speed). The Alekseevskii-Tate model: the penetrator's nose erodes at
  the interface, where 0.5 rho_p (v - u)^2 + Y_p = 0.5 rho_t u^2 + R_t, while
  the rest of it is slowed by its own strength. A soft core (lead, copper) only
  gets in when 0.5 rho_p v^2 + Y_p beats R_t; below that it splashes on the face.
  Depleted uranium shears off at its nose and stays sharp (a little deeper).

* **Cratering**: a bullet that splashes still leaves a crater. A share of its
  energy that grows as the fourth power of (0.5 rho_p v^2 + Y_p) / R_t digs a
  hemispherical crater against the plate's hardness. A frangible bullet turns
  to powder instead.

A plate of thickness T is perforated once the depth in a thick plate, plus an
allowance for the plug or bulge pushed off its back face, reaches T along the
line of flight (T / cos of the obliquity). The residual velocity follows
Lambert and Jonas, v_r = m / (m + m_plug) sqrt(v^2 - v_bl^2).

The penetrator is the round's insert (an AP core) if it has one, else its core,
else (a shell whose explosive fills it) its steel body.

**Payloads** (fills, projectiles.py), once the fuze has armed and fires:

* a **shaped charge** (HEAT): the liner's jet reaches about 5.6 cone diameters
  into RHA at its best standoff for a copper cone and Comp B, scaled by
  sqrt(liner density), the explosive's detonation pressure, the standoff, the cone
  angle, and spin (a spun jet spreads: 1 / sqrt(1 + (n CD / 30 m/s)^2));
  independent of the impact speed;
* **HESH**: the squashed explosive's shock knocks a scab off the back face of
  plate up to about 0.09 m kg^-1/3 times the cube root of its TNT equivalent;
* **HE**: a contact burst breaches plate up to 0.02 m kg^-1/3 W^1/3; the blast's
  peak overpressure follows Kinney and Graham's fit in the scaled distance
  R / W^(1/3); the body breaks into fragments by Mott's law (mean mass
  2 B^2 t^5/3 d^2/3 (1 + t/d)^2) thrown at the Gurney velocity, slowed by
  the air, lethal while they carry 80 J;
* **incendiaries** flash on a hard impact, their heat of burning released;
  **depleted uranium** burns behind the armour; a **tracer** still alight can
  start a fire.

**Ballistic gelatin** (10 %, calibrated): the projectile is slowed by
A (0.5 rho C_D v^2 + R); an expanding bullet opens over its first few
centimetres to a diameter set by its impact speed and sheds mass, a slender
non-expanding one yaws after about 20 calibres and tumbles base-first, and above
its construction's speed it fragments. The temporary cavity grows with the
energy it deposits per unit depth.

RHAe (rolled homogeneous armour equivalent) is the same model run against RHA.
These are engineering estimates in the spirit of the textbook models, tuned to a
handful of published figures (.50 M2 AP: about 20 mm of RHA at 100 m; a lead-core
rifle bullet craters AR500 at close range without getting through; 9 mm ball
about 65 cm of gelatin, JHP about 30 cm; a 120 mm HEAT-FS about 600 mm of RHA);
treat them as such.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from . import projectiles
from .config import SUB_CALIBRE, Gun
from .projectiles import CONSTRUCTIONS, FILLS, LINERS, METALS, TRACERS, construction_of

BHN_TO_PA = 9.80665e6     # Brinell hardness number (kgf/mm^2) to Pa
JACKET_DENSITY = 8900.0   # gilding metal
AIR_DENSITY = 1.225
P_ATM = 101325.0


@dataclass(frozen=True)
class Armour:
    label: str
    hardness: float      # BHN
    density: float       # kg/m^3
    resistance: float    # Pa, the target's resistance R_t (Tate) and R (cavity expansion)


# AR500 is through-hardened abrasion-resistant plate (about 500 BHN) used for steel targets; RHA
# (MIL-DTL-12560, about 300 BHN) is the reference armour.
ARMOURS = {
    "ar500": Armour("AR500 steel", 500.0, 7850.0, 7.2e9),
    "rha": Armour("Rolled homogeneous armour (RHA)", 300.0, 7850.0, 5.0e9),
    "mild_steel": Armour("Mild steel (A36)", 150.0, 7850.0, 2.8e9),
    "aluminium": Armour("Aluminium armour (5083)", 95.0, 2660.0, 1.4e9),
}
GELATIN = "gelatin"
TARGETS = ("ar500", "rha", "mild_steel", "aluminium", GELATIN)   # what a target can be made of

PENETRATORS = METALS     # density, strength (Y_p), hardness of every core material
Penetrator = projectiles.Metal

RICOCHET_ANGLE = 70.0   # degrees from the plate's normal past which a hard core skips off steel
CRATER = 1.0e-3        # m: a dent this deep is a crater (the plate is damaged, and throws splash back)
CAP_SHATTER = 1.35     # a penetrating cap raises the shatter speed this much
CAP_NORMALISE = 7.0    # degrees a penetrating cap adds to the ricochet angle (it bites and turns the shot in)


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
    capped: bool = False
    frangible: bool = False
    what: str = "core"   # "core", "insert", "rod" or "body"

    @property
    def props(self) -> projectiles.Metal:
        return METALS[self.material]


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


_JACKET_METAL = {"gilding_metal": "copper", "copper": "copper", "clad_steel": "steel", "steel": "steel",
                 "brass": "brass", "aluminium": "aluminium", "polymer": "lead"}


def core_of(gun: Gun) -> Core:
    """What does the penetrating: a sabot round's rod, the AP insert, the core inside the jacket, or (a shell
    whose fill takes up the core) its body."""
    p, d = gun.projectile, gun.barrel.bore_diameter
    capped = p.cap in ("penetrating", "both")
    if p.type in SUB_CALIBRE:
        material = p.core_name
        mass, dc = p.penetrator_mass, p.penetrator_diameter
        n = 0.1 if p.type == "apfsds" else nose_factor(dc, p.ogive_length or 0.0, p.meplat_diameter or 0.0)
        return _core(material, mass, dc, n, mass, capped, "rod")
    parts = projectiles.parts(gun)
    total = p.mass
    if p.insert_material:
        mass = parts.mass_of("insert")
        ins = [pc for pc in parts.pieces if pc.role == "insert"]
        dc = 2 * max(pc.hi[0] + pc.hi[1] * pc.x0 for pc in ins)
        return _core(p.insert_material, mass, dc, 0.14, total, capped, "insert")
    core_mass = parts.mass_of("core")
    t = parts.layout.shape.jacket
    if core_mass < 0.15 * total and parts.jacket > core_mass:
        # The fill has taken the core's place: the shell's body is what hits.
        material = _JACKET_METAL[p.jacket_material]
        n = nose_factor(d, p.ogive_length or 0.0, p.meplat_diameter or 0.0)
        return _core(material, parts.jacket + core_mass, d, n, total, capped, "body")
    material = p.core_name
    dc = d - 2 * min(t, 0.45 * d)
    n = nose_factor(d, p.ogive_length or 0.0, p.meplat_diameter or 0.0)
    if p.hollow_point_diameter > 0 or p.exposed_core_length > 0:
        n = max(n, 0.6)   # an expanding nose opens up on the face
    if t == 0:
        core_mass = total - sum(pc.mass for pc in parts.pieces if pc.role in ("fill", "tip", "tracer") and
                                projectiles._kind(pc.material) != "metal")
    return _core(material, max(core_mass, 1e-6), dc, n, total, capped, "core")


def _core(material, mass, dc, n, total, capped, what) -> Core:
    rho = METALS[material].density
    length = mass / (rho * math.pi * dc**2 / 4)
    return Core(material, mass, dc, n, length, total, capped, METALS[material].frangible, what)


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
    return depth * pen.sharpening, max(length, 0.0)


def crater_depth(core: Core, armour: Armour, v: float) -> float:
    """Depth (m) of the crater a projectile that splashes on the face leaves."""
    pen = core.props
    s = min(1.0, (0.5 * pen.density * v * v + pen.strength) / armour.resistance)
    energy = 0.1 * s**4 * 0.5 * core.total_mass * v * v
    if core.frangible:
        energy *= 0.03   # it turns to powder; almost nothing goes into the plate
    volume = energy / (armour.hardness * BHN_TO_PA)
    return (3 * volume / (2 * math.pi)) ** (1 / 3)


def shatter_speed(core: Core, armour: Armour) -> float | None:
    """Impact speed (m/s) above which this core breaks up on this plate, or None if it never does."""
    s = core.props.shatter
    if not s:
        return None
    return s * math.sqrt(300.0 / armour.hardness) * (CAP_SHATTER if core.capped else 1.0)


def rigid_share(core: Core, armour: Armour, v: float) -> float:
    """How far the penetrator behaves as a rigid body (1) rather than eroding (0).

    A core much harder than the plate stays whole; one about as hard shatters or
    erodes. Above about 1.3 km/s everything erodes, as long rods do. A brittle core
    breaks up above its shatter speed.
    """
    h = core.props.hardness / armour.hardness
    w = _smoothstep((h - 0.9) / 0.6) * _smoothstep((1500.0 - v) / 500.0)
    vs = shatter_speed(core, armour)
    if vs:
        w *= 1 - _smoothstep((v - vs) / (0.2 * vs))
    return w


@dataclass
class Hit:
    depth: float          # m into a thick plate
    regime: str           # "rigid", "eroding" or "splash"
    rigid: float          # rigid share
    limit_thickness: float  # m of plate (along the line of flight) it just gets through
    shattered: bool = False


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
    vs = shatter_speed(core, armour)
    return Hit(depth, regime, w, depth + allowance, shattered=bool(vs and v > vs))


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


# ---------------------------------------------------------------------------
# Payloads
# ---------------------------------------------------------------------------
def overpressure(distance: float, tnt: float) -> float:
    """Peak side-on overpressure (Pa) at `distance` (m) from a burst of `tnt` kg TNT (Kinney and Graham)."""
    if tnt <= 0:
        return 0.0
    z = max(distance, 1e-3) / tnt ** (1 / 3)
    return P_ATM * 808 * (1 + (z / 4.5) ** 2) / math.sqrt((1 + (z / 0.048) ** 2) * (1 + (z / 0.32) ** 2)
                                                          * (1 + (z / 1.35) ** 2))


def blast_radius(tnt: float, pressure: float) -> float:
    """Distance (m) at which the burst's peak overpressure falls to `pressure` (Pa)."""
    if tnt <= 0:
        return 0.0
    lo, hi = 1e-3, 1e4
    for _ in range(60):
        mid = math.sqrt(lo * hi)
        if overpressure(mid, tnt) > pressure:
            lo = mid
        else:
            hi = mid
    return hi


BLAST_LEVELS = (("windows", 7e3), ("eardrums", 35e3), ("lungs", 200e3))
LETHAL_FRAGMENT = 80.0   # J: the classic lethal fragment energy


def fragmentation(case_mass: float, charge: float, gurney: float, wall: float, bore: float) -> dict | None:
    """Fragments of a cased charge: Gurney velocity, Mott's mean fragment, and how far they stay lethal."""
    if case_mass <= 0 or charge <= 0:
        return None
    cm = charge / case_mass
    v0 = gurney * math.sqrt(cm / (1 + 0.5 * cm))
    t = max(wall, 0.04 * bore)
    di = max(bore - 2 * t, 0.2 * bore)
    b = 2.0 * (2440.0 / gurney) ** 2          # Mott's constant, kg^1/2 m^-7/6 (steel, scaled from TNT's)
    mu = b * b * t ** (5 / 3) * di ** (2 / 3) * (1 + t / di) ** 2
    mean = 2 * mu
    count = max(case_mass / mean, 1.0)
    area = 1.2 * (mean / 7850.0) ** (2 / 3)   # presented area of a chunky fragment
    decay = 2 * mean / (AIR_DENSITY * 1.2 * area)   # m: its speed falls by e over this
    # The heaviest tenth of them (Mott: a share exp(-sqrt(m / mu)) is heavier than m) carry furthest.
    heavy = 5.3 * mu
    v_lethal = math.sqrt(2 * LETHAL_FRAGMENT / heavy)
    heavy_decay = 2 * heavy / (AIR_DENSITY * 1.2 * 1.2 * (heavy / 7850.0) ** (2 / 3))
    lethal = heavy_decay * math.log(v0 / v_lethal) if v0 > v_lethal else 0.0
    dense = math.sqrt(count / (4 * math.pi))   # out to here, at least one fragment per square metre
    # Steel plate the mean fragment gets through at its launch speed (a blunt chunk, rigid).
    frag = _core("steel", mean, (mean / 7850.0) ** (1 / 3), 0.8, mean, False, "fragment")
    pierce = penetrate(frag, ARMOURS["mild_steel"], v0).limit_thickness
    return {"velocity": v0, "count": count, "mean_mass": mean, "heavy_mass": heavy, "decay": decay,
            "lethal_radius": lethal, "dense_radius": dense, "pierces": pierce}


def shaped_charge(gun: Gun, parts: projectiles.Parts, muzzle_velocity: float | None) -> dict | None:
    """The jet of a shaped charge: penetration into RHA at the round's standoff."""
    p = gun.projectile
    if not p.liner_material:
        return None
    lay = parts.layout
    cd = lay.liner_diameter
    liner = LINERS[p.liner_material]
    explosive = FILLS[p.filler or "comp_b"]
    comp_b = FILLS["comp_b"]
    f_expl = math.sqrt(explosive.density * explosive.detonation**2 / (comp_b.density * comp_b.detonation**2))
    s = lay.standoff / cd
    f_standoff = 0.65 + 0.35 * min(s / 4, 1.0) if s <= 4 else 1 / (1 + 0.01 * (s - 4) ** 2)
    half = p.liner_angle
    f_angle = 0.9 if half < 15 else max(0.3, 1 - max(0.0, half - 35) / 50)
    spin = 0.0
    if p.type == "bullet" and gun.barrel.twist and muzzle_velocity:
        spin = muzzle_velocity / abs(gun.barrel.twist)   # rev/s
    f_spin = 1 / math.sqrt(1 + (spin * cd / 30.0) ** 2)
    depth = 5.6 * cd * math.sqrt(liner.density / 7850.0) * liner.quality * f_expl * f_standoff * f_angle * f_spin
    return {"cone_diameter": cd, "standoff": lay.standoff, "standoff_cd": s, "rha_depth": depth, "spin": spin,
            "spin_factor": f_spin, "standoff_factor": f_standoff, "liner": liner.label, "explosive": explosive.label}


def jet_depth(jet: dict, armour: Armour) -> float:
    """A jet's reach into a plate: deeper into lighter, softer plate (hydrodynamic: sqrt of the densities)."""
    return jet["rha_depth"] * math.sqrt(7850.0 / armour.density) * (ARMOURS["rha"].resistance / armour.resistance) ** 0.15


def charges(parts: projectiles.Parts) -> dict:
    """The explosive and incendiary in the projectile: masses, TNT equivalent, Gurney constant."""
    expl = parts.fills("explosive")
    inc = parts.fills("incendiary") + parts.fills("smoke") + parts.fills("flash")
    mass = sum(m for _, m in expl)
    tnt = sum(m * FILLS[k].tnt for k, m in expl)
    gurney = sum(m * FILLS[k].gurney for k, m in expl) / mass if mass else 0.0
    heat = sum(m * FILLS[k].heat for k, m in inc)
    return {"explosive": expl, "explosive_mass": mass, "tnt": tnt, "gurney": gurney,
            "incendiary": inc, "incendiary_mass": sum(m for _, m in inc), "heat": heat}


def fuze_state(gun: Gun, distance: float, time: float) -> dict:
    """Whether the fuze is armed when it gets there, and whether the round got there at all."""
    p = gun.projectile
    armed = distance >= p.arming_distance
    out = {"type": p.fuze, "armed": armed, "delay": p.fuze_delay, "airburst": None, "self_destruct": None}
    if p.fuze == "time" and p.fuze_time and time > p.fuze_time:
        out["airburst"] = p.fuze_time
    elif p.fuze not in ("none", "time") and p.fuze_time and time > p.fuze_time:
        out["self_destruct"] = p.fuze_time
    return out


def payload(gun: Gun, velocity: float, armour: Armour | None, thickness: float, los: float, perforated: bool,
            residual: float, distance: float, time: float, muzzle_velocity: float | None) -> dict:
    """What the round's fills do when it hits (armour None: a soft target)."""
    p = gun.projectile
    parts = projectiles.parts(gun)
    ch = charges(parts)
    fz = fuze_state(gun, distance, time)
    out = {"fuze": fz, "charges": {"explosive_mass": ch["explosive_mass"], "tnt": ch["tnt"],
                                   "incendiary_mass": ch["incendiary_mass"], "heat": ch["heat"],
                                   "explosive": [[k, FILLS[k].label, m] for k, m in ch["explosive"]],
                                   "incendiary": [[k, FILLS[k].label, m] for k, m in ch["incendiary"]]}}
    hard = armour is not None
    fires = fz["armed"] and not fz["airburst"] and not fz["self_destruct"] and p.fuze != "none"
    if p.fuze == "pyrotechnic":
        fires = fires and hard and velocity > 300.0
    if p.fuze == "time":
        fires = fz["armed"] and not fz["airburst"]   # it has an impact backup
    where = None
    if fz["airburst"] or fz["self_destruct"]:
        where = "air"
    elif fires:
        if p.fuze in ("impact", "time") or not hard:
            where = "face"
        elif perforated:
            where = "behind"
        else:
            where = "face"
    behind = residual * p.fuze_delay if where == "behind" else 0.0
    fz.update(fires=fires and where != "air", where=where, behind=behind)

    if ch["explosive_mass"] > 0:
        wall = parts.layout.shape.jacket
        metal = parts.jacket + sum(pc.mass for pc in parts.pieces if projectiles._kind(pc.material) == "metal"
                                   or pc.role in ("fuze", "cap", "liner"))
        frag = fragmentation(metal, ch["explosive_mass"], ch["gurney"] or 2440.0, wall, gun.barrel.bore_diameter)
        out["blast"] = {k: blast_radius(ch["tnt"], v) for k, v in BLAST_LEVELS}
        out["fragments"] = frag
        hesh = p.filler == "pe4" or (p.construction == "shell" and p.fuze == "base" and wall < 0.06 * gun.barrel.bore_diameter
                                     and ch["explosive_mass"] > 0.25 * p.mass)
        if hard and where == "face" and not p.liner_material:
            w3 = ch["tnt"] ** (1 / 3)
            out["breach"] = 0.02 * w3
            if hesh:
                out["scab"] = 0.09 * w3
    jet = shaped_charge(gun, parts, muzzle_velocity)
    if jet:
        out["jet"] = jet
        if hard:
            jet["depth"] = jet_depth(jet, armour)
            jet["works"] = bool(fires and where != "air")
    if ch["incendiary_mass"] > 0:
        lights = velocity > (150.0 if any(k == "zirconium" for k, _ in ch["incendiary"]) else 250.0)
        out["incendiary"] = {"lights": bool(lights and (hard or fires)), "energy": ch["heat"],
                             "carried": bool(perforated and lights), "kind": [k for k, _ in ch["incendiary"]]}
    core = p.insert_material or (p.core_name if p.type in SUB_CALIBRE else "")
    if core and METALS[core].pyrophoric and perforated:
        out["pyrophoric"] = True
    if p.tracer:
        burn = (p.tracer_length or 1.5 * gun.flight_diameter) / TRACERS[p.tracer].rate
        out["tracer"] = {"burn_time": burn, "alight": time < burn, "colour": p.tracer}
    return out


# ---------------------------------------------------------------------------
# Plates
# ---------------------------------------------------------------------------
def impact(gun: Gun, velocity: float, thickness: float, angle: float = 0.0, target: str = "ar500", *,
           distance: float = 0.0, time: float = 0.0, muzzle_velocity: float | None = None) -> dict:
    """What a hit at `velocity` (m/s) does to a plate of `target` `thickness` (m) thick, struck `angle`
    degrees off its normal, with its RHA equivalents and what the round's fills do. `distance` (m) and
    `time` (s) of flight decide whether the fuze is armed (or has gone off in the air)."""
    if target == GELATIN:
        return gel(gun, velocity, distance=distance, time=time, muzzle_velocity=muzzle_velocity)
    if target not in ARMOURS:
        raise ValueError(f"unknown target material {target!r}; choose from {', '.join(TARGETS)}")
    if thickness <= 0:
        raise ValueError("the plate's thickness must be positive")
    if not 0 <= angle < 85:
        raise ValueError("the angle off the plate's normal must be between 0 and 85 degrees")
    armour, rha = ARMOURS[target], ARMOURS["rha"]
    p = gun.projectile
    core = core_of(gun)
    los = thickness / math.cos(math.radians(angle))
    hit = penetrate(core, armour, velocity)
    hit_rha = penetrate(core, rha, velocity)
    perforated = hit.limit_thickness >= los
    ricochet_at = RICOCHET_ANGLE + (CAP_NORMALISE if core.capped else 0.0)
    if p.type == "apfsds":
        ricochet_at = 78.0   # a long rod at ordnance speed bites at angles that skip a bullet
    hesh = p.filler == "pe4"
    ricochet = angle >= ricochet_at and not hesh
    if ricochet:
        perforated = False
    residual = 0.0
    v_bl = ballistic_limit(core, armour, los, velocity) if perforated else None
    if perforated and v_bl is not None:
        plug = armour.density * math.pi * (core.diameter / 2) ** 2 * los
        residual = core.mass / (core.mass + plug) * math.sqrt(max(velocity**2 - v_bl**2, 0.0))
    # How much RHA this plate is worth against this round.
    if hit.depth > 0.5e-3 and hit_rha.depth > 0:
        efficiency = min(3.0, max(1.0 / 3.0, hit_rha.depth / hit.depth))
    else:
        efficiency = armour.resistance / rha.resistance
    energy = 0.5 * core.total_mass * velocity**2
    depth, limit, regime = hit.depth, hit.limit_thickness, hit.regime
    rha_depth, rha_limit = hit_rha.depth, hit_rha.limit_thickness

    pay = payload(gun, velocity, armour, thickness, los, perforated, residual, distance, time, muzzle_velocity)
    fz = pay["fuze"]
    verdict = None
    jet = pay.get("jet")
    if jet and jet.get("works") and not ricochet:
        jd = jet["depth"]
        if jd > depth:
            depth, limit, regime = jd, jd, "jet"
            rha_depth = rha_limit = max(rha_depth, jet["rha_depth"])
        if jd >= los and not perforated:
            perforated, residual, v_bl = True, 0.0, None
        pay["jet"]["residual"] = max(jd - los, 0.0)
    detonated = fz["fires"] and fz["where"] == "face" and not ricochet
    if fz["where"] == "air":
        verdict = "airburst" if fz["airburst"] else "self-destructed"
        perforated = False
    elif detonated and pay.get("breach") is not None:
        # It goes off on the face: the body breaks up there instead of punching through; the blast (or, for
        # HESH, the shock) is what the plate feels.
        if regime != "jet":
            perforated, residual, v_bl = False, 0.0, None
            limit = max(pay["breach"], pay.get("scab", 0.0))
            depth = min(depth, 0.3 * pay["breach"])
            rha_depth, rha_limit = depth, limit
            regime = "blast"
        if thickness <= pay["breach"]:
            verdict = "breached"
        elif pay.get("scab") and thickness <= pay["scab"]:
            verdict = "scabbed"
    if verdict is None:
        if ricochet:
            verdict = "ricochet"
        elif perforated:
            verdict = "perforated"
        elif depth >= CRATER:
            verdict = "cratered"
        else:
            verdict = "stopped"
    if core.frangible and verdict in ("cratered", "stopped"):
        verdict = "dusted" if depth < CRATER else verdict
    return {
        "kind": "plate",
        "target": target,
        "target_label": armour.label,
        "velocity": velocity,
        "energy": energy,
        "thickness": thickness,
        "angle": angle,
        "line_of_sight": los,
        "core": {"material": core.material, "label": core.props.label, "mass": core.mass, "what": core.what,
                 "diameter": core.diameter, "length": core.length, "nose_factor": core.nose_factor,
                 "capped": core.capped, "shatter_speed": shatter_speed(core, armour)},
        "construction": construction_of(p, gun.barrel.bore_diameter),
        "depth": depth,
        "regime": regime,
        "rigid_share": hit.rigid,
        "shattered": hit.shattered,
        "limit_thickness": limit,
        "perforated": perforated,
        "ricochet": ricochet,
        "verdict": verdict,
        "ballistic_limit": v_bl,
        "residual_velocity": residual,
        "rha_depth": rha_depth,
        "rha_limit_thickness": rha_limit,
        "plate_rhae": los * efficiency,
        "efficiency": efficiency,
        "payload": pay,
    }


def plate_at(gun: Gun, core: Core, armour: Armour, v: float, distance: float, jet: dict | None) -> tuple[float, float]:
    """(depth, limit thickness) at an impact speed, a shaped charge's jet counted once it is armed."""
    h = penetrate(core, armour, v)
    if jet and distance >= gun.projectile.arming_distance:
        jd = jet_depth(jet, armour)
        if jd > h.depth:
            return jd, jd
    return h.depth, h.limit_thickness


# ---------------------------------------------------------------------------
# Ballistic gelatin
# ---------------------------------------------------------------------------
GEL_DENSITY = 1040.0      # kg/m^3, 10 % ordnance gelatin at 4 C
GEL_STRENGTH = 1.27e6     # Pa, its resistance to being parted (a 9 mm ball round goes about 65 cm)
GEL_CAVITY = 3.0e6        # Pa: the temporary cavity's diameter is sqrt(4 dE/dx / (pi this))
GEL_STOP = 40.0           # m/s: slower than this it stops
CD_MUSHROOM = 0.5
CD_TUMBLE = 1.2
FBI = (0.305, 0.457)      # m: 12 to 18 in, the FBI's penetration window


def gel(gun: Gun, velocity: float, *, distance: float = 0.0, time: float = 0.0,
        muzzle_velocity: float | None = None) -> dict:
    """What the projectile does in a block of ballistic gelatin hit at `velocity` (m/s)."""
    p = gun.projectile
    bore = gun.barrel.bore_diameter
    kind = construction_of(p, bore)
    c = CONSTRUCTIONS[kind]
    pay = payload(gun, velocity, None, 0.0, 0.0, False, 0.0, distance, time, muzzle_velocity)
    base = {"kind": "gel", "target": GELATIN, "target_label": "10 % ballistic gelatin", "velocity": velocity,
            "energy": 0.5 * gun.flight_mass * velocity**2, "construction": kind, "construction_label": c.label,
            "payload": pay}
    fz = pay["fuze"]
    if fz["where"] == "air":
        return {**base, "verdict": "airburst" if fz["airburst"] else "self-destructed", "depth": 0.0, "series": None}
    if c.explodes and fz["fires"]:
        return {**base, "verdict": "detonated", "depth": 0.0, "series": None}

    d = gun.flight_diameter
    m0 = gun.flight_mass
    length = p.length if p.type != "finned" else p.length - p.boom_length
    n = nose_factor(d, p.ogive_length or 0.0, p.meplat_diameter or 0.0)
    cd_nose = min(0.35 + 0.9 * n, 1.25)
    # Expansion and fragmentation at this impact speed.
    expand = c.expand
    if expand > 1 and c.v_full > c.v_open:
        expand = 1 + (c.expand - 1) * _smoothstep((velocity - c.v_open) / (c.v_full - c.v_open))
    opening = 1.5 * d + 0.01            # m it takes to open
    frags = bool(c.v_frag and velocity > c.v_frag)
    keep = c.retention if expand > 1 else 1.0
    if expand > 1 and c.expand > 1:
        keep = 1 - (1 - c.retention) * (expand - 1) / (c.expand - 1)
    slender = length / d > 2.8 and (p.meplat_diameter or 0.0) < 0.35 * d and expand < 1.1 and kind not in (
        "fmj_fn", "lfn", "swc", "wc", "solid")
    yaw_at = 20 * d * c.yaw_early if slender else None
    frag_at = (yaw_at if yaw_at is not None else 2 * d) if frags else None

    dx = 5e-4
    x, v, m = 0.0, velocity, m0
    xs, vs, dedx, width, cavity = [], [], [], [], []
    tumbling = fragmented = False
    lost_energy = 0.0
    spread_until = 0.0
    while x < 1.5 and v > GEL_STOP:
        prog = min(x / opening, 1.0)
        e = 1 + (expand - 1) * prog
        mass = m * (1 - (1 - keep) * prog) if not fragmented else m
        if yaw_at is not None and x >= yaw_at:
            tumbling = True
        if frag_at is not None and x >= frag_at and not fragmented:
            fragmented = True
            shed = mass * (1 - c.frag_retention)
            lost_energy = 0.5 * shed * v * v
            spread_until = x + 0.06
            m = mass = mass - shed
        if tumbling:
            area, cd, w = d * length * 0.8, CD_TUMBLE, length
        else:
            area, cd, w = math.pi * (e * d) ** 2 / 4, CD_MUSHROOM if e > 1.05 else cd_nose, e * d
        force = area * (0.5 * GEL_DENSITY * cd * v * v + GEL_STRENGTH)
        extra = lost_energy / 0.06 if x < spread_until else 0.0   # the fragments' energy, over the next 6 cm
        v = math.sqrt(max(v * v - 2 * force / mass * dx, 0.0))
        x += dx
        if len(xs) == 0 or x - xs[-1] >= 2e-3:
            xs.append(x)
            vs.append(v)
            de = force + extra
            dedx.append(de)
            width.append(w)
            cavity.append(math.sqrt(4 * de / (math.pi * GEL_CAVITY)))
    retained = m * (1 - (1 - keep)) if not fragmented else m
    peak = max(range(len(dedx)), key=lambda i: dedx[i]) if dedx else 0
    in_window = FBI[0] <= x <= FBI[1]
    return {
        **base,
        "verdict": "through" if x >= 1.5 else "stopped",
        "depth": x,
        "expanded_diameter": expand * d,
        "expansion": expand,
        "retained_mass": retained,
        "retained_share": retained / m0,
        "yaw_depth": yaw_at,
        "fragmented": fragmented,
        "fragment_depth": frag_at if fragmented else None,
        "peak_dedx": dedx[peak] if dedx else 0.0,
        "peak_depth": xs[peak] if xs else 0.0,
        "temporary_cavity": max(cavity) if cavity else 0.0,
        "permanent_cavity": max(width) if width else d,
        "fbi": "under" if x < FBI[0] else ("in" if in_window else "over"),
        "series": {"depth": xs, "velocity": vs, "dedx": dedx, "width": width, "cavity": cavity},
    }
