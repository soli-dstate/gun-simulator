"""What a projectile is made of, and where each part of it sits.

A projectile is a body (a jacket round a core, or a solid of one metal) with
fills inside it, each a real material with real effects:

* a **penetrator** (insert): a hard rod inside the core, of hardened steel,
  tungsten carbide, tungsten alloy, titanium or depleted uranium;
* a **filler** and a **tip filler**: high explosive (TNT, Comp B, RDX, PETN,
  octol, plastic explosive...), incendiary (IM-11, zirconium, magnesium,
  thermite, white phosphorus), a flash charge, an inert fill or a polymer tip;
* a **tracer** in the base, which burns for its length and lightens the
  projectile as it goes;
* a **shaped-charge liner** (HEAT): a cone of copper, molybdenum, tantalum,
  aluminium or steel in front of the explosive;
* **caps** (a soft penetrating cap and/or a hollow ballistic windshield) and a
  **fuze** (impact, delay, base-detonating, pyrotechnic or time).

`layout` places them along the projectile (axially symmetric pieces, each
bounded by straight lines in the r-x plane), the same way the 3D view draws them
(cartridge.js); `parts` turns the pieces into masses. `DESIGNS` are complete
projectile types (FMJ, JHP, LSWC, API-T, Raufoss, APCBC, APFSDS, HEAT-FS, HESH,
...) scaled to any bore by `design`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Materials
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Metal:
    """A metal a core or penetrator can be made of (terminal.py's penetrator properties)."""
    label: str
    density: float          # kg/m^3
    strength: float         # Pa, dynamic flow stress Y_p (Tate)
    hardness: float         # BHN
    shatter: float = 0.0    # m/s: a rigid core of it breaks up above this against 300 BHN steel (0 = never)
    pyrophoric: bool = False  # its fragments burn in air (depleted uranium)
    sharpening: float = 1.0   # adiabatic shear keeps an eroding rod's nose sharp: depth factor
    frangible: bool = False   # pressed powder: it turns to dust on a hard target


# Order matters: config.core_material may be an index into it.
METALS = {
    "lead": Metal("lead (antimony-hardened)", 11340.0, 0.05e9, 8.0),
    "steel": Metal("mild steel", 7850.0, 0.9e9, 200.0),
    "copper": Metal("copper", 8960.0, 0.35e9, 90.0),
    "tungsten": Metal("tungsten heavy alloy", 17600.0, 1.6e9, 360.0),
    "hardened_steel": Metal("hardened steel", 7850.0, 2.0e9, 650.0, shatter=1100.0),
    "tungsten_carbide": Metal("tungsten carbide", 14900.0, 4.0e9, 1300.0, shatter=1250.0),
    "titanium": Metal("titanium alloy (Ti-6Al-4V)", 4430.0, 1.0e9, 330.0),
    "depleted_uranium": Metal("depleted uranium alloy (U-0.75Ti)", 18600.0, 1.4e9, 380.0, pyrophoric=True,
                              sharpening=1.12),
    "aluminium": Metal("aluminium alloy", 2800.0, 0.45e9, 120.0),
    "brass": Metal("brass", 8500.0, 0.45e9, 130.0),
    "sintered_copper": Metal("sintered copper-tin (frangible)", 7000.0, 0.15e9, 60.0, frangible=True),
}
CORE_MATERIALS = tuple(METALS)

# The jacket over a core, a shell's body, or a sabot.
JACKETS = {
    "gilding_metal": ("gilding metal (95/5 copper-zinc)", 8800.0),
    "copper": ("copper", 8960.0),
    "clad_steel": ("copper-washed steel", 7850.0),
    "steel": ("steel (a shell's body)", 7850.0),
    "brass": ("brass", 8500.0),
    "aluminium": ("aluminium alloy", 2800.0),
    "polymer": ("polymer (a coated bullet, or a plastic sabot)", 1250.0),
}


@dataclass(frozen=True)
class Fill:
    label: str
    kind: str                # "explosive", "incendiary", "smoke", "flash" or "inert"
    density: float           # kg/m^3, as loaded
    tnt: float = 0.0         # blast TNT equivalence (by mass)
    detonation: float = 0.0  # m/s, detonation velocity
    gurney: float = 0.0      # m/s, the Gurney constant sqrt(2E)
    heat: float = 0.0        # J/kg released burning in air (incendiaries) or as a flash


FILLS = {
    # High explosives: densities as loaded, TNT equivalence by air blast, detonation velocity, Gurney constant.
    "tnt": Fill("TNT", "explosive", 1600.0, 1.00, 6900.0, 2440.0),
    "comp_b": Fill("Composition B (RDX/TNT 60/40)", "explosive", 1720.0, 1.33, 7980.0, 2700.0),
    "comp_a4": Fill("Composition A-4 (RDX 97 %, wax)", "explosive", 1650.0, 1.30, 8100.0, 2680.0),
    "petn": Fill("PETN (phlegmatised, as RX-51)", "explosive", 1700.0, 1.50, 8300.0, 2900.0),
    "octol": Fill("Octol (HMX/TNT 75/25)", "explosive", 1810.0, 1.54, 8480.0, 2800.0),
    "lx14": Fill("LX-14 (HMX plastic-bonded)", "explosive", 1830.0, 1.60, 8830.0, 2970.0),
    "pe4": Fill("PE4 / C-4 (plastic explosive)", "explosive", 1600.0, 1.34, 8040.0, 2600.0),
    "a_ix_1": Fill("A-IX-1 (RDX, phlegmatised)", "explosive", 1650.0, 1.30, 8100.0, 2650.0),
    "a_ix_2": Fill("A-IX-2 (RDX/aluminium/wax)", "explosive", 1770.0, 1.54, 7900.0, 2600.0),
    "tetryl": Fill("Tetryl", "explosive", 1710.0, 1.25, 7570.0, 2500.0),
    "amatol": Fill("Amatol (ammonium nitrate/TNT)", "explosive", 1600.0, 0.95, 6000.0, 2200.0),
    "explosive_d": Fill("Explosive D (ammonium picrate)", "explosive", 1550.0, 0.95, 6850.0, 2300.0),
    # Incendiaries: heat of burning in air.
    "im11": Fill("IM-11 incendiary (Mg/Al alloy, barium nitrate)", "incendiary", 2400.0, heat=8.0e6),
    "zirconium": Fill("zirconium powder (sparks on impact)", "incendiary", 4500.0, heat=12.0e6),
    "magnesium": Fill("magnesium", "incendiary", 1740.0, heat=24.7e6),
    "thermite": Fill("thermite (iron oxide/aluminium)", "incendiary", 3000.0, heat=4.0e6),
    "white_phosphorus": Fill("white phosphorus (smoke, incendiary)", "smoke", 1830.0, heat=24.0e6),
    "flash": Fill("flash/spotting charge (Mg/barium nitrate)", "flash", 2200.0, heat=7.0e6),
    # Inert.
    "polymer": Fill("polymer tip", "inert", 1200.0),
    "inert": Fill("inert fill (practice)", "inert", 1500.0),
    "lead": Fill("lead", "inert", 11340.0),
    "aluminium": Fill("aluminium", "inert", 2800.0),
    "steel": Fill("steel", "inert", 7850.0),
}
EXPLOSIVES = tuple(k for k, f in FILLS.items() if f.kind == "explosive")


@dataclass(frozen=True)
class Tracer:
    label: str
    colour: tuple[float, float, float]  # sRGB of its flame
    rate: float        # m/s the composition burns down its cavity
    density: float     # kg/m^3, pressed
    brightness: float = 1.0


TRACERS = {
    "red": Tracer("red (strontium nitrate, magnesium)", (1.0, 0.24, 0.12), 4.5e-3, 2700.0),
    "green": Tracer("green (barium nitrate)", (0.40, 1.0, 0.32), 4.5e-3, 2800.0),
    "white": Tracer("white (magnesium, sodium nitrate)", (1.0, 0.95, 0.85), 5.0e-3, 2400.0, 1.3),
    "orange": Tracer("orange (calcium)", (1.0, 0.55, 0.15), 4.5e-3, 2600.0),
    "dim": Tracer("dim / infrared (seen only through night vision)", (0.7, 0.18, 0.1), 3.0e-3, 2600.0, 0.12),
}


@dataclass(frozen=True)
class Liner:
    label: str
    density: float
    quality: float     # jet coherence (ductility) relative to copper


LINERS = {
    "copper": Liner("copper", 8960.0, 1.00),
    "molybdenum": Liner("molybdenum", 10220.0, 1.00),
    "tantalum": Liner("tantalum", 16650.0, 0.85),
    "steel": Liner("steel", 7850.0, 0.88),
    "aluminium": Liner("aluminium (anti-concrete)", 2800.0, 0.95),
}

FUZES = {
    "none": "none: the fill does not go off",
    "impact": "point-detonating, superquick: goes off on the face",
    "delay": "point-detonating with a delay: goes off fuze_delay after impact",
    "base": "base-detonating: goes off fuze_delay after impact, behind armour if it gets through",
    "pyrotechnic": "none as such: the incendiary flash sets the explosive off a moment after impact (Raufoss)",
    "time": "time: bursts in the air at fuze_time (programmable airburst)",
}
CAPS = ("none", "penetrating", "ballistic", "both")


@dataclass(frozen=True)
class Construction:
    """How a projectile behaves in a soft target (terminal.gel) and on steel."""
    label: str
    expand: float = 1.0          # expanded over original diameter, fully opened
    v_open: float = 0.0          # m/s: starts to open at this impact speed
    v_full: float = 0.0          # m/s: fully open
    retention: float = 1.0       # share of its mass it keeps
    v_frag: float = 0.0          # m/s: above this it fragments (0 = never)
    frag_retention: float = 0.6  # share it keeps once it fragments
    explodes: bool = False       # a shell: it goes off rather than penetrating
    frangible: bool = False
    yaw_early: float = 1.0       # an open tip yaws sooner (factor on the yaw depth)


CONSTRUCTIONS = {
    "fmj": Construction("Full metal jacket (ball)", v_frag=780.0, frag_retention=0.6),
    "fmj_fn": Construction("Flat-nose FMJ / truncated cone"),
    "lrn": Construction("Lead round nose", 1.15, 300.0, 450.0, 0.95),
    "lfn": Construction("Lead flat nose / hard cast"),
    "swc": Construction("Semi-wadcutter (cuts a full-calibre hole)"),
    "wc": Construction("Wadcutter"),
    "jhp": Construction("Jacketed hollow point", 1.7, 250.0, 340.0, 0.95, 620.0, 0.6),
    "hp": Construction("Lead hollow point", 1.8, 200.0, 300.0, 0.8, 450.0, 0.5),
    "jsp": Construction("Jacketed soft point", 1.9, 330.0, 650.0, 0.75, 1000.0, 0.5),
    "otm": Construction("Open-tip match", v_frag=650.0, frag_retention=0.55, yaw_early=0.6),
    "polymer_tip": Construction("Polymer tip (ballistic tip)", 2.0, 450.0, 700.0, 0.6, 750.0, 0.45),
    "bonded": Construction("Bonded soft point", 1.9, 450.0, 750.0, 0.92),
    "monolithic": Construction("Monolithic copper hollow point", 2.0, 550.0, 750.0, 0.98),
    "solid": Construction("Monolithic solid (non-expanding)"),
    "frangible": Construction("Frangible (pressed powder)", v_frag=300.0, frag_retention=0.15, frangible=True),
    "ap": Construction("Armour-piercing (the jacket strips, the core goes on)", v_frag=900.0, frag_retention=0.7),
    "shell": Construction("Explosive shell", explodes=True),
    "sabot": Construction("Sub-calibre penetrator"),
}


def construction_of(p, bore: float) -> str:
    """The projectile's construction: as set, or worked out from its shape and fills."""
    if p.construction:
        return p.construction
    if p.type in ("apfsds", "apds"):
        return "sabot"
    if p.liner_material or (p.filler in EXPLOSIVES and p.fuze != "none" and p.fuze != "pyrotechnic"):
        return "shell"
    if p.insert_material in ("hardened_steel", "tungsten_carbide", "tungsten", "depleted_uranium"):
        return "ap"
    if METALS[CORE_MATERIALS[int(p.core_material)]].frangible:
        return "frangible"
    jacketed = p.jacket_thickness > 0
    if p.tip_filler == "polymer":
        return "polymer_tip"
    if p.hollow_point_diameter > 0 and p.hollow_point_depth > 0:
        return "jhp" if jacketed else "hp"
    if p.exposed_core_length > 0 and jacketed:
        return "jsp"
    if not jacketed:
        return "lfn" if (p.meplat_diameter or 0.0) >= 0.5 * bore else "lrn"
    return "fmj"


def fill(name: str) -> Fill:
    if name in FILLS:
        return FILLS[name]
    if name in METALS:
        m = METALS[name]
        return Fill(m.label, "inert", m.density)
    raise KeyError(name)


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------
SHELL_BORE = 15e-3          # m: from this bore up a fuze body, base fuze and such are drawn as parts
EPS = 1e-12


@dataclass
class Shape:
    """The outside of a projectile (or an APFSDS's rod), base at x = 0, and the cavity inside its jacket."""
    length: float
    radius: float
    base_radius: float
    boat_tail: float
    ogive: float
    meplat_radius: float
    jacket: float

    @property
    def ogive_start(self) -> float:
        return self.length - self.ogive

    def outer(self, x: float) -> float:
        R = self.radius
        if x < self.boat_tail and self.boat_tail > 0:
            return self.base_radius + (R - self.base_radius) * x / self.boat_tail
        x0 = self.ogive_start
        if x <= x0 or self.ogive <= 1e-9:
            return R if x <= self.length else 0.0
        dr = max(R - self.meplat_radius, 1e-9)
        rho = (self.ogive**2 + dr**2) / (2 * dr)
        u = min(x - x0, self.ogive)
        return R - rho + math.sqrt(max(rho * rho - u * u, 0.0))

    def inner(self, x: float) -> float:
        return max(self.outer(x) - self.jacket, 0.0)


def shape(p, bore: float) -> Shape:
    """The projectile's outside: the whole projectile, an APFSDS's (APDS's) rod, or a finned round's body."""
    rod = p.type in ("apfsds", "apds")
    d = min(p.penetrator_diameter or 0.2 * bore, 0.9 * bore) if rod else bore
    R = d / 2
    length = max(p.length - ((p.boom_length or 0.0) if p.type == "finned" else 0.0), 1e-6)
    bt = 0.0 if rod else min(max(p.boat_tail_length or 0.0, 0.0), 0.4 * length)
    base = max(R - bt * math.tan(math.radians(min(max(p.boat_tail_angle, 0.0), 30.0))), 0.3 * R)
    ogive = min(max(p.ogive_length or 0.0, 0.0), length - bt)
    rm = min(max((p.meplat_diameter or 0.0) / 2, 0.0), 0.95 * R)
    t = 0.0 if rod else min(max(p.jacket_thickness, 0.0), 0.45 * R)
    return Shape(length, R, base, bt, ogive, rm, t)


Line = tuple[float, float]   # r = a + b x


def _at(line: Line | None, x: float, default: float) -> float:
    return default if line is None else line[0] + line[1] * x


@dataclass
class Piece:
    """One part of the projectile: material between lines lo and hi (None = the axis / the cavity wall)
    from x0 to x1. role: "core", "insert", "fill", "tip", "tracer", "liner", "fuze", "cap", "windshield",
    "air". `outside` pieces are bounded by the projectile's outside instead of its cavity."""
    material: str
    role: str
    x0: float
    x1: float
    lo: Line | None = None
    hi: Line | None = None
    outside: bool = False
    density: float = 0.0
    volume: float = 0.0
    mass: float = 0.0


@dataclass
class Layout:
    shape: Shape
    pieces: list[Piece]
    cavity: tuple[float, float]   # x range of the cavity inside the jacket
    cut: float                    # the body (jacket) ends here; the outside pieces sit above it
    standoff: float = 0.0         # m, liner mouth to the tip (shaped charge)
    liner_diameter: float = 0.0   # m


def _cylinder(r: float) -> Line:
    return (r, 0.0)


def _partition(explicit: list[Piece], regions: list[tuple[str, str, float, float]], x_lo: float, x_hi: float,
               core: str) -> list[Piece]:
    """Explicit pieces as they are, and everything else in the cavity from x_lo to x_hi: the region fill
    whose range it is in, else the core."""
    xs = {x_lo, x_hi}
    for p in explicit:
        xs.update((p.x0, p.x1))
    for _, _, a, b in regions:
        xs.update((a, b))
    xs = sorted(x for x in xs if x_lo - EPS <= x <= x_hi + EPS)
    out = list(explicit)
    for xa, xb in zip(xs, xs[1:]):
        if xb - xa < 1e-9:
            continue
        xm = 0.5 * (xa + xb)
        mat, role = next(((m, r) for m, r, a, b in regions if a - EPS <= xm <= b + EPS), (core, "core"))
        active = sorted((p for p in explicit if p.x0 - EPS <= xm <= p.x1 + EPS), key=lambda p: _at(p.lo, xm, 0.0))
        lo: Line | None = None
        wall = False
        for p in active:
            if _at(p.lo, xm, 0.0) > _at(lo, xm, 0.0) + 1e-9:
                out.append(Piece(mat, role, xa, xb, lo, p.lo))
            if p.hi is None:
                wall = True
                break
            if lo is None or _at(p.hi, xm, 0.0) > _at(lo, xm, 0.0):
                lo = p.hi
        if not wall:
            out.append(Piece(mat, role, xa, xb, lo, None))
    return out


def layout(p, bore: float) -> Layout:
    """Where every part of the projectile sits. Lengths in m from the base of the body (a finned round's
    body starts boom_length up its tail boom; an APFSDS's rod is the body)."""
    s = shape(p, bore)
    L, t, d = s.length, s.jacket, 2 * s.radius
    big = bore >= SHELL_BORE
    x_lo = t
    top = L - t if t > 0 else L
    if t > 0 and p.exposed_core_length > 0:
        top = L
    if p.hollow_point_diameter > 0 and p.hollow_point_depth > 0:
        top = min(top, L - p.hollow_point_depth)
    pieces: list[Piece] = []
    explosive = p.filler in EXPLOSIVES

    # Outside pieces, from the tip down: a windshield, a nose fuze, a polymer tip, a penetrating cap.
    cut = L
    ogive = s.ogive if s.ogive > 0.05 * d else 0.5 * d
    if p.cap in ("ballistic", "both"):
        xw = L - 0.55 * ogive
        pieces.append(Piece("windshield", "windshield", xw, L, outside=True))
        cut = xw
    if (p.fuze in ("impact", "delay", "time") and (explosive or p.liner_material or p.filler == "white_phosphorus")
            and big and p.cap not in ("ballistic", "both")):
        fl = min(0.8 * d, 0.7 * ogive, 0.3 * L)
        pieces.append(Piece("fuze", "fuze", cut - fl, cut, outside=True))
        cut -= fl
    if p.tip_filler == "polymer":
        tl = p.tip_filler_length or min(0.35 * d, 0.4 * ogive)
        pieces.append(Piece("polymer", "tip", cut - tl, cut, outside=True))
        cut -= tl
    if p.cap in ("penetrating", "both"):
        cl = 0.5 * d
        pieces.append(Piece("cap", "cap", cut - cl, cut, outside=True))
        cut -= cl
    top = min(top, cut)
    top = max(top, x_lo + 1e-6)

    explicit: list[Piece] = []
    regions: list[tuple[str, str, float, float]] = []
    lo_free, hi_free = x_lo, top
    standoff = liner_d = 0.0
    if p.fuze == "base" and big and (explosive or p.filler == "white_phosphorus"):
        bl = min(0.35 * d, 0.25 * (hi_free - lo_free))
        regions.append(("fuze", "fuze", lo_free, lo_free + bl))
        lo_free += bl
    if p.tracer:
        trl = min(p.tracer_length or 1.5 * d, 0.6 * (top - x_lo))
        rt = 0.55 * max(s.inner(x_lo + 1e-6) if t > 0 else s.outer(x_lo + 1e-6), 1e-6)
        explicit.append(Piece(f"tracer:{p.tracer}", "tracer", x_lo, x_lo + trl, None, _cylinder(rt)))
    if p.liner_material:
        # A shaped charge: explosive behind a cone that opens towards the target, air ahead of it.
        span = hi_free - lo_free
        xl = min(lo_free + (p.filler_length or 0.5 * span), hi_free - 0.05 * d)
        xl = max(xl, lo_free + 0.1 * span)
        rl = 0.97 * (s.inner(xl) if t > 0 else s.outer(xl))
        half = math.radians(min(max(p.liner_angle, 10.0), 70.0))
        h = min(rl / math.tan(half), 0.85 * (xl - lo_free))
        slope = rl / max(h, 1e-9)
        xa = xl - h
        th = (p.liner_thickness or 0.025 * 2 * rl) / max(math.cos(math.atan(slope)), 0.2)
        cone = (-slope * xa, slope)
        explicit.append(Piece("air", "air", xa, xl, None, cone))
        explicit.append(Piece(f"liner:{p.liner_material}", "liner", xa, xl, cone, (cone[0] + th, slope)))
        explicit.append(Piece("air", "air", xl, hi_free, None, None))
        regions.append((p.filler or "comp_b", "fill", lo_free, xl))
        standoff, liner_d = L - xl, 2 * rl
    else:
        cur = hi_free
        if p.tip_filler and p.tip_filler != "polymer":
            tl = min(p.tip_filler_length or 0.6 * d, cur - lo_free)
            regions.append((p.tip_filler, "tip", cur - tl, cur))
            cur -= tl
        if p.filler:
            if p.filler_position > 0:
                x0 = min(lo_free + p.filler_position, cur)
                x1 = min(x0 + (p.filler_length or cur - x0), cur)
            elif p.filler_length > 0:
                x1, x0 = cur, max(cur - p.filler_length, lo_free)
                cur = x0
            else:
                x0, x1 = lo_free, cur
            regions.append((p.filler, "fill", x0, x1))
            if p.filler_length == 0 and p.filler_position == 0:
                cur = lo_free   # it fills the rest: an insert sits inside it
        if p.insert_material:
            room = cur - lo_free if cur - lo_free > 0.2 * d else hi_free - lo_free
            il = min(p.insert_length or 0.6 * room, hi_free - lo_free)
            if p.insert_position > 0:
                x0 = min(lo_free + p.insert_position, hi_free - il)
            else:
                x0 = max((cur if cur - lo_free > 0.2 * d else hi_free) - il, lo_free)
            x1 = x0 + il
            wall = s.inner(x0) if t > 0 else s.outer(x0)
            ri = min(p.insert_diameter / 2 if p.insert_diameter else 0.72 * wall, 0.95 * wall)
            nose = min(2.4 * ri, 0.45 * il)
            explicit.append(Piece(p.insert_material, "insert", x0, x1 - nose, None, _cylinder(ri)))
            slope = -0.95 * ri / nose
            explicit.append(Piece(p.insert_material, "insert", x1 - nose, x1, None, (ri - slope * (x1 - nose), slope)))
    core = CORE_MATERIALS[int(p.core_material)]
    pieces += _partition(explicit, regions, x_lo, top, core)
    out = Layout(s, pieces, (x_lo, top), cut, standoff, liner_d)
    _measure(p, out)
    return out


def density_of(p, material: str) -> float:
    if material in METALS:
        return METALS[material].density
    if material in FILLS:
        return FILLS[material].density
    if material.startswith("tracer:"):
        return TRACERS[material[7:]].density
    if material.startswith("liner:"):
        return LINERS[material[6:]].density
    return {"fuze": 3500.0, "cap": 7850.0, "windshield": 2800.0, "air": 0.0}[material]


def _measure(p, lay: Layout, steps: int = 160) -> None:
    """Each piece's volume and mass (as built: not yet matched to the projectile's stated mass)."""
    s = lay.shape
    for pc in lay.pieces:
        pc.density = density_of(p, pc.material)
        if pc.x1 <= pc.x0 or pc.role == "air":
            continue
        h = (pc.x1 - pc.x0) / steps
        v = 0.0
        for i in range(steps):
            x = pc.x0 + (i + 0.5) * h
            if pc.outside:
                r = s.outer(x)
                ri = max(r - 0.04 * 2 * s.radius, 0.0) if pc.role == "windshield" else 0.0
                v += r * r - ri * ri
            else:
                wall = s.inner(x) if s.jacket > 0 else s.outer(x)
                hi = min(_at(pc.hi, x, wall), wall)
                lo = min(max(_at(pc.lo, x, 0.0), 0.0), wall)
                if hi > lo:
                    v += hi * hi - lo * lo
        pc.volume = math.pi * v * h
        pc.mass = pc.volume * pc.density


def _jacket_volume(p, lay: Layout, steps: int = 200) -> float:
    s = lay.shape
    if s.jacket <= 0:
        return 0.0
    h = lay.cut / steps
    v = 0.0
    x_lo, top = lay.cavity
    for i in range(steps):
        x = (i + 0.5) * h
        r = s.outer(x)
        ri = s.inner(x) if x_lo <= x <= top else 0.0
        v += r * r - ri * ri
    hp = 0.0
    if p.hollow_point_diameter > 0:
        hp = math.pi * (p.hollow_point_diameter / 2) ** 2 * min(p.hollow_point_depth, s.length) * 0.3
    return max(math.pi * v * h - hp, 0.0)


def _jacket_density(p) -> float:
    return JACKETS.get(p.jacket_material or "gilding_metal", JACKETS["gilding_metal"])[1]


@dataclass
class Parts:
    """The projectile's parts and their masses, scaled so they add up to what flies (gun.flight_mass)."""
    layout: Layout
    jacket: float               # kg
    pieces: list[Piece]         # masses scaled
    built: float                # kg the parts would weigh as drawn
    scale: float                # stated mass / built mass

    def mass_of(self, role: str, kind: str | None = None) -> float:
        return sum(pc.mass for pc in self.pieces if pc.role == role
                   and (kind is None or _kind(pc.material) == kind))

    def fills(self, kind: str) -> list[tuple[str, float]]:
        """(material, kg) of every fill of a kind ("explosive", "incendiary", ...)."""
        out: dict[str, float] = {}
        for pc in self.pieces:
            if pc.role in ("fill", "tip") and _kind(pc.material) == kind and pc.mass > 0:
                out[pc.material] = out.get(pc.material, 0.0) + pc.mass
        return list(out.items())


def material_label(material: str) -> str:
    """A piece's material in words."""
    if material in METALS:
        return METALS[material].label
    if material in FILLS:
        return FILLS[material].label
    if material.startswith("tracer:"):
        return f"tracer, {TRACERS[material[7:]].label}"
    if material.startswith("liner:"):
        return f"{LINERS[material[6:]].label} liner"
    return {"fuze": "fuze", "cap": "penetrating cap (soft steel)", "windshield": "ballistic cap (windshield)",
            "air": "air"}[material]


def _kind(material: str) -> str:
    if material in FILLS:
        return FILLS[material].kind
    if material in METALS:
        return "metal"
    return material.split(":")[0]


def built_mass(p, bore: float) -> float:
    """What the body (or rod) and its fills weigh as laid out, kg (a finned round's boom and fins included)."""
    lay = layout(p, bore)
    m = _jacket_volume(p, lay) * _jacket_density(p) + sum(pc.mass for pc in lay.pieces)
    if p.type == "finned":
        m += _boom_mass(p, bore)
    return m


def _boom_mass(p, bore: float) -> float:
    boom = p.boom_length or 0.0
    rb = BOOM_RADIUS * bore
    span = min(p.fin_span or 0.95 * bore, 0.98 * bore)
    fins = FINS * (p.fin_length or 0.6 * bore) * max(span / 2 - rb, 0.0) * 0.03 * bore * 7850.0
    return math.pi * rb * rb * boom * 2800.0 + fins


BOOM_RADIUS = 0.17   # a finned round's tail boom, in bores (radius)
FINS = 6


def parts(gun) -> Parts:
    """The parts of what flies from the muzzle (an APFSDS's rod, not its sabot), masses matched to it."""
    p, bore = gun.projectile, gun.barrel.bore_diameter
    lay = layout(p, bore)
    jacket = _jacket_volume(p, lay) * _jacket_density(p)
    built = jacket + sum(pc.mass for pc in lay.pieces) + (_boom_mass(p, bore) if p.type == "finned" else 0.0)
    scale = gun.flight_mass / built if built > 0 else 1.0
    scaled = [Piece(**{**pc.__dict__, "mass": pc.mass * scale}) for pc in lay.pieces]
    return Parts(lay, jacket * scale, scaled, built, scale)


# ---------------------------------------------------------------------------
# Designs: whole projectile types, scaled to the bore
# ---------------------------------------------------------------------------
# Every field a design sets; anything it leaves out goes back to this.
BLANK = {
    "type": "bullet", "construction": "", "jacket_material": "gilding_metal", "jacket_thickness": 0.0,
    "core_material": "lead", "exposed_core_length": 0.0, "hollow_point_diameter": 0.0, "hollow_point_depth": 0.0,
    "ogive_radius_ratio": 1.0, "cannelure_position": 0.0, "cannelure_width": 0.0, "cannelure_depth": 0.0,
    "boat_tail_length": 0.0, "boat_tail_angle": 9.0, "meplat_diameter": 0.0,
    "insert_material": "", "insert_length": 0.0, "insert_diameter": 0.0, "insert_position": 0.0,
    "filler": "", "filler_length": 0.0, "filler_position": 0.0, "tip_filler": "", "tip_filler_length": 0.0,
    "tracer": "", "tracer_length": 0.0, "liner_material": "", "liner_angle": 30.0, "liner_thickness": 0.0,
    "cap": "none", "fuze": "none", "fuze_delay": 0.0, "fuze_time": 0.0, "arming_distance": 0.0,
    "penetrator_mass": None, "penetrator_diameter": None, "fin_span": None, "fin_length": None,
    "sabot_length": None, "sabot_offset": None, "sabot_material": "aluminium", "boom_length": 0.0,
    "drag_model": "G7", "ballistic_coefficient": None,
}

# Shapes in calibres: length, ogive, meplat, boat tail.
_SPITZER = {"length": 3.7, "ogive_length": 2.0, "meplat_diameter": 0.1, "boat_tail_length": 0.5}
_ROUND = {"length": 1.6, "ogive_length": 0.9, "meplat_diameter": 0.3, "drag_model": "G1"}
_FLAT = {"length": 1.55, "ogive_length": 0.65, "meplat_diameter": 0.62, "drag_model": "G1"}
_SHELL = {"length": 4.6, "ogive_length": 2.2, "meplat_diameter": 0.15, "boat_tail_length": 0.25,
          "boat_tail_angle": 7.0, "drag_model": "G1"}
_SHOT = {"length": 3.4, "ogive_length": 1.4, "meplat_diameter": 0.05, "boat_tail_length": 0.15,
         "boat_tail_angle": 6.0, "drag_model": "G1"}

# Lengths below are in calibres (the bore); the design multiplies them out.
_LENGTHS = {"length", "ogive_length", "meplat_diameter", "boat_tail_length", "jacket_thickness", "exposed_core_length",
            "hollow_point_diameter", "hollow_point_depth", "insert_length", "insert_diameter", "insert_position",
            "filler_length", "filler_position", "tip_filler_length", "tracer_length", "liner_thickness",
            "penetrator_diameter", "fin_span", "fin_length", "sabot_length", "sabot_offset", "boom_length",
            "cannelure_position", "cannelure_width", "cannelure_depth"}


@dataclass(frozen=True)
class Design:
    label: str
    group: str               # "Bullets", "Armour-piercing and special", "Cannon shells", "Kinetic energy"
    blurb: str
    values: dict


def _d(label, group, blurb, *shapes, **values) -> Design:
    v = {}
    for s in shapes:
        v.update(s)
    v.update(values)
    return Design(label, group, blurb, v)


_J = 0.075   # jacket, calibres
B, S, C, K = "Bullets", "Armour-piercing and special", "Cannon shells", "Kinetic energy"
DESIGNS = {
    # ---- bullets
    "fmj": _d("FMJ spitzer (ball)", B, "A lead core in a gilding-metal jacket closed over the nose, open at the base.",
              _SPITZER, jacket_thickness=_J, construction="fmj"),
    "fmj_rn": _d("FMJ round nose", B, "The pistol ball round: a round-nosed jacketed lead core.",
                 _ROUND, jacket_thickness=0.05, construction="fmj"),
    "fmj_fn": _d("FMJ flat nose / truncated cone", B, "A jacketed flat nose: it feeds like ball and punches a cleaner hole.",
                 _FLAT, jacket_thickness=0.05, construction="fmj_fn"),
    "tmj": _d("TMJ (total metal jacket)", B, "Plated all over, base included: no bare lead.",
              _ROUND, jacket_thickness=0.03, jacket_material="copper", construction="fmj"),
    "lrn": _d("LRN (lead round nose)", B, "Plain cast or swaged lead.", _ROUND, construction="lrn"),
    "lfn": _d("LFN / hard cast flat nose", B, "Hard-cast lead with a wide flat meplat: it doesn't expand, it crushes.",
              _FLAT, meplat_diameter=0.72, construction="lfn"),
    "lswc": _d("LSWC (lead semi-wadcutter)", B, "A short nose on a sharp shoulder that cuts a full-calibre hole.",
               {"length": 1.45, "ogive_length": 0.42, "meplat_diameter": 0.62, "drag_model": "G1"}, construction="swc"),
    "wc": _d("WC (wadcutter)", B, "A flat-ended lead cylinder for paper targets: it punches clean holes.",
             {"length": 1.15, "ogive_length": 0.0, "meplat_diameter": 0.95, "drag_model": "G1"}, construction="wc"),
    "coated": _d("Polymer-coated lead (RN)", B, "Lead with a polymer coat instead of a jacket: no lead smear.",
                 _ROUND, jacket_thickness=0.012, jacket_material="polymer", construction="lrn"),
    "jhp": _d("JHP (jacketed hollow point)", B, "A cavity in the nose that opens the jacket out into petals.",
              _ROUND, meplat_diameter=0.6, hollow_point_diameter=0.4, hollow_point_depth=0.5, jacket_thickness=0.05,
              construction="jhp"),
    "lhp": _d("LHP (lead hollow point)", B, "A soft lead hollow point: opens fast, sheds lead.",
              _ROUND, meplat_diameter=0.6, hollow_point_diameter=0.42, hollow_point_depth=0.5, construction="hp"),
    "jsp": _d("JSP (jacketed soft point)", B, "The jacket stops short of the tip; the bare lead mushrooms.",
              _SPITZER, length=3.4, ogive_length=1.6, meplat_diameter=0.25, boat_tail_length=0.0, jacket_thickness=_J,
              exposed_core_length=0.3, construction="jsp"),
    "otm": _d("OTM (open-tip match)", B, "Drawn from the base, leaving a tiny opening at the tip: accurate, not expanding.",
              _SPITZER, length=4.0, ogive_length=2.3, meplat_diameter=0.13, hollow_point_diameter=0.1,
              hollow_point_depth=0.6, jacket_thickness=_J, construction="otm"),
    "polymer_tip": _d("Polymer tip (ballistic tip)", B, "A polymer tip in the jacket's mouth: a sharp nose that drives in "
                      "and opens the bullet fast.", _SPITZER, length=3.6, meplat_diameter=0.04, jacket_thickness=_J,
                      tip_filler="polymer", tip_filler_length=0.42, exposed_core_length=0.35, construction="polymer_tip"),
    "bonded": _d("Bonded soft point", B, "The core is soldered to a copper jacket so it holds together as it opens.",
                 _SPITZER, length=3.5, ogive_length=1.7, meplat_diameter=0.22, jacket_thickness=0.09,
                 jacket_material="copper", exposed_core_length=0.25, construction="bonded"),
    "monolithic": _d("Monolithic copper hollow point", B, "Solid copper (lead-free) with a deep nose cavity that "
                     "opens into petals: it keeps nearly all its weight.", _SPITZER, length=3.9, core_material="copper",
                     hollow_point_diameter=0.18, hollow_point_depth=0.9, meplat_diameter=0.3, construction="monolithic"),
    "solid": _d("Monolithic solid (brass)", B, "Turned brass with a flat meplat: no expansion, straight-line penetration.",
                _SPITZER, length=3.3, ogive_length=1.4, meplat_diameter=0.5, core_material="brass",
                boat_tail_length=0.0, construction="solid"),
    "frangible": _d("Frangible (sintered copper)", B, "Pressed copper-tin powder: it turns to dust on steel, "
                    "so no ricochet or splash.", _SPITZER, length=3.0, core_material="sintered_copper",
                    construction="frangible"),
    "tracer": _d("Ball tracer (M856 / M62 type)", B, "Ball with a red tracer in a cavity at the base, "
                 "lit by the propellant gas; it burns out a few hundred metres downrange.",
                 _SPITZER, length=4.0, boat_tail_length=0.4, jacket_thickness=_J, tracer="red", tracer_length=1.6,
                 construction="fmj"),
    # ---- armour-piercing and special
    "steel_core": _d("Steel penetrator ball (M855 / SS109 type)", S, "A steel penetrator in front of a lead core: it "
                     "gets through light steel that stops plain ball.", _SPITZER, length=4.0, jacket_thickness=_J, insert_material="steel",
                     insert_length=1.6, insert_diameter=0.55, construction="fmj"),
    "ap": _d("AP (hardened steel core)", S, "A long hardened-steel core in a lead sleeve and jacket (.30 M2 AP, "
             ".50 M2 AP, 7N10).", _SPITZER, length=4.3, jacket_thickness=_J, insert_material="hardened_steel",
             insert_length=2.9, insert_diameter=0.72, construction="ap"),
    "ap_wc": _d("AP (tungsten carbide core)", S, "A tungsten-carbide core seated in an aluminium cup (M993, M995, 7N24).",
                _SPITZER, length=4.2, jacket_thickness=_J, core_material="aluminium", insert_material="tungsten_carbide",
                insert_length=2.3, insert_diameter=0.68, construction="ap"),
    "api": _d("API (armour-piercing incendiary)", S, "A hardened-steel core with incendiary in the nose that flashes "
              "on impact (B-32, M8).", _SPITZER, length=4.4, jacket_thickness=_J, insert_material="hardened_steel",
              insert_length=2.6, insert_diameter=0.7, tip_filler="im11", tip_filler_length=0.8, construction="ap"),
    "apit": _d("API-T (armour-piercing incendiary tracer)", S, "API with a tracer in the base (BZT, M20).",
               _SPITZER, length=4.5, jacket_thickness=_J, insert_material="hardened_steel", insert_length=2.2,
               insert_diameter=0.68, tip_filler="im11", tip_filler_length=0.7, tracer="red", tracer_length=1.2,
               construction="ap"),
    "incendiary": _d("Incendiary (M1 / ZP type)", S, "An incendiary charge in the nose of a ball bullet.",
                     _SPITZER, length=4.0, jacket_thickness=_J, filler="im11", filler_length=1.3, construction="fmj"),
    "raufoss": _d("Multipurpose (Raufoss NM140 / Mk 211)", S, "A tungsten-carbide penetrator in a steel cup, high "
                  "explosive in front of it and an incendiary nose: the flash sets the explosive off, the jacket "
                  "fragments and the penetrator goes on through.", _SPITZER, length=4.6, jacket_thickness=_J,
                  core_material="steel", insert_material="tungsten_carbide", insert_length=1.5, insert_diameter=0.52,
                  filler="petn", filler_length=0.9, tip_filler="zirconium", tip_filler_length=0.7,
                  fuze="pyrotechnic", fuze_delay=2.5e-4, construction="ap"),
    "slap": _d("SLAP (saboted light armour penetrator)", S, "A tungsten penetrator in a plastic sabot that falls away "
               "at the muzzle (.50 M903).", type="apds", length=2.9, penetrator_diameter=0.42, core_material="tungsten",
               ogive_length=1.0, meplat_diameter=0.03, sabot_length=2.2, sabot_offset=0.0, sabot_material="polymer",
               tracer="red", tracer_length=0.5, construction="sabot", drag_model="G7"),
    # ---- cannon shells
    "he": _d("HE (high explosive)", C, "A steel shell filled with Comp B on a point-detonating fuze: blast and "
             "fragments.", _SHELL, jacket_thickness=0.12, jacket_material="steel", filler="comp_b", fuze="impact",
             arming_distance=20.0, construction="shell"),
    "he_tnt": _d("HE-FRAG (TNT, thick wall)", C, "A thicker, notched wall and TNT: fewer, heavier fragments.",
                 _SHELL, jacket_thickness=0.17, jacket_material="steel", filler="tnt", fuze="impact",
                 arming_distance=20.0, construction="shell"),
    "hei": _d("HEI-T (high explosive incendiary tracer)", C, "Aluminised explosive (A-IX-2) for blast and fire, a "
              "tracer, and a self-destruct when the tracer burns out.", _SHELL, jacket_thickness=0.1,
              jacket_material="steel", filler="a_ix_2", tracer="red", tracer_length=0.5, fuze="impact", fuze_time=8.0,
              arming_distance=15.0, construction="shell"),
    "he_ab": _d("HE airburst (programmable time fuze)", C, "A time fuze set to burst over the target.",
                _SHELL, jacket_thickness=0.12, jacket_material="steel", filler="comp_b", fuze="time", fuze_time=2.0,
                construction="shell"),
    "saphei": _d("SAPHEI (semi-armour-piercing HEI)", C, "A thick, hardened nose that gets through light armour, "
                 "then a base fuze sets the explosive and incendiary off inside.", _SHELL, ogive_length=1.6,
                 meplat_diameter=0.05, jacket_thickness=0.2, jacket_material="steel", filler="comp_a4",
                 tip_filler="im11", tip_filler_length=0.5, fuze="base", fuze_delay=3e-4, construction="shell"),
    "hesh": _d("HESH / HEP (squash head)", C, "A thin shell of plastic explosive with a soft nose that flattens on the "
               "plate before the base fuze fires it: the shock knocks a scab off the back face.",
               {"length": 3.8, "ogive_length": 1.0, "meplat_diameter": 0.55, "drag_model": "G1"},
               jacket_thickness=0.04, jacket_material="steel", filler="pe4", fuze="base", fuze_delay=1e-4, tracer="red",
               tracer_length=0.4, construction="shell"),
    "heat": _d("HEAT (spin-stabilised)", C, "A shaped charge: a copper cone in front of the explosive collapses into a "
               "jet. Spun by the rifling, the jet spreads and loses much of its reach.", _SHELL, ogive_length=2.4,
               jacket_thickness=0.05, jacket_material="steel", liner_material="copper", liner_angle=30.0,
               filler="comp_b", filler_length=1.5, fuze="impact", arming_distance=20.0, construction="shell"),
    "heat_fs": _d("HEAT-FS (fin-stabilised)", C, "A shaped charge on a tail boom with fins: it doesn't spin, so the "
                  "jet stays whole, and a long nose probe sets it off at the best standoff (DM12, M830).",
                  type="finned", length=7.6, boom_length=2.6, ogive_length=2.6, meplat_diameter=0.2,
                  jacket_thickness=0.05, jacket_material="steel", liner_material="copper", liner_angle=30.0,
                  filler="octol", filler_length=1.7, fuze="impact", arming_distance=30.0, fin_span=0.95,
                  fin_length=0.6, tracer="red", tracer_length=0.3, construction="shell", drag_model="G1"),
    "smoke_wp": _d("Smoke (white phosphorus)", C, "A burster spreads burning white phosphorus: smoke and fire.",
                   _SHELL, jacket_thickness=0.08, jacket_material="steel", filler="white_phosphorus", fuze="impact",
                   construction="shell"),
    "tp": _d("TP-T (target practice tracer)", C, "Inert: the weight and flight of the service round, and a tracer.",
             _SHELL, jacket_thickness=0.12, jacket_material="steel", filler="inert", tracer="red", tracer_length=0.5,
             construction="fmj"),
    # ---- kinetic energy
    "ap_shot": _d("AP (solid shot)", K, "Solid hardened steel.", _SHOT, core_material="hardened_steel",
                  construction="ap"),
    "apc": _d("APC (capped)", K, "A softer steel cap on the nose spreads the impact and keeps the shot from "
              "shattering on hard armour.", _SHOT, core_material="hardened_steel", cap="penetrating",
              construction="ap"),
    "apbc": _d("APBC (ballistic cap)", K, "A hollow windshield over a blunt shot: less drag, the blunt nose bites "
               "sloped plate.", _SHOT, length=3.6, ogive_length=1.7, core_material="hardened_steel", cap="ballistic",
               construction="ap"),
    "apcbc": _d("APCBC (capped, ballistic cap)", K, "Both caps.", _SHOT, length=3.8, ogive_length=1.8,
                core_material="hardened_steel", cap="both", tracer="red", tracer_length=0.4, construction="ap"),
    "aphe": _d("APHE (APCBC-HE)", K, "A capped shot with a small explosive cavity and a delayed base fuze: it bursts "
               "behind the armour.", _SHOT, length=3.8, ogive_length=1.8, core_material="hardened_steel", cap="both",
               filler="explosive_d", filler_length=0.6, filler_position=0.45, fuze="base", fuze_delay=1.2e-3,
               construction="ap"),
    "apcr": _d("APCR / HVAP (composite rigid)", K, "A tungsten core in a light alloy body: high velocity, a hard "
               "small-diameter punch.", _SHOT, length=3.6, jacket_thickness=0.18, jacket_material="aluminium",
               core_material="aluminium", insert_material="tungsten", insert_length=2.0, insert_diameter=0.42,
               cap="ballistic", construction="ap"),
    "apds": _d("APDS (discarding sabot)", K, "A spin-stabilised tungsten core in a sabot that falls away at the "
               "muzzle.", type="apds", length=2.9, penetrator_diameter=0.42, core_material="tungsten",
               ogive_length=1.0, meplat_diameter=0.03, sabot_length=2.4, sabot_offset=0.0, cap="ballistic",
               tracer="red", tracer_length=0.4, construction="sabot", drag_model="G1"),
    "apfsds": _d("APFSDS (tungsten long rod)", K, "A fin-stabilised long rod in a sabot: all the energy on a tiny "
                 "cross-section.", type="apfsds", length=6.2, penetrator_diameter=0.2, core_material="tungsten",
                 ogive_length=0.5, meplat_diameter=0.017, tracer="red", tracer_length=0.12, construction="sabot",
                 drag_model="LR"),
    "apfsds_du": _d("APFSDS (depleted uranium)", K, "The same rod in depleted uranium: it sharpens itself as it "
                    "erodes, and its dust burns behind the armour.", type="apfsds", length=6.2,
                    penetrator_diameter=0.2, core_material="depleted_uranium", ogive_length=0.5,
                    meplat_diameter=0.017, tracer="red", tracer_length=0.12, construction="sabot", drag_model="LR"),
}


def design(key: str, bore: float, current: dict | None = None) -> dict:
    """The projectile section for a design at this bore: shape and fills from the design, the in-bore
    resistances kept from `current`, and the mass from what the parts weigh."""
    from .config import Projectile

    if key not in DESIGNS:
        raise ValueError(f"unknown projectile design {key!r}; choose from {', '.join(DESIGNS)}")
    keep = {k: v for k, v in (current or {}).items()
            if k in ("shot_start_pressure", "bore_resistance", "engraving_pressure")}
    out = {**BLANK, "boat_tail_angle": 9.0}
    for k, v in DESIGNS[key].values.items():
        out[k] = v * bore if k in _LENGTHS and v is not None else v
    out.update(keep)
    rod = out["type"] in ("apfsds", "apds")
    if out["boat_tail_length"] == 0.0:
        out["boat_tail_angle"] = 0.0
    if out["type"] == "apfsds":
        rd = out["penetrator_diameter"]
        out.update(fin_span=min(3.5 * rd, 0.95 * bore), fin_length=6 * rd, sabot_length=1.2 * bore)
        out["sabot_offset"] = 1.5 * out["fin_length"]
    p = Projectile(mass=1.0, **{k: v for k, v in out.items() if k != "mass"})
    if rod:
        p.penetrator_mass = 1.0
    body = built_mass(p, bore)
    if rod:
        sabot_d = JACKETS[out["sabot_material"]][1]
        rd = out["penetrator_diameter"]
        sabot = 0.55 * math.pi / 4 * (bore**2 - rd**2) * out["sabot_length"] * sabot_d
        out["penetrator_mass"] = body
        out["mass"] = body + sabot
    else:
        out["mass"] = body
    out["ballistic_coefficient"] = None
    return out


# Lengths along the projectile, scaled together when a bullet design is fitted to the bullet already there.
_AXIAL = ("length", "ogive_length", "boat_tail_length", "hollow_point_depth", "insert_length", "insert_position",
          "filler_length", "filler_position", "tip_filler_length", "tracer_length", "exposed_core_length")


def fit_design(key: str, gun) -> dict:
    """A design on this gun. A bullet design that replaces a bullet keeps the bullet's length (its features
    scaled along it), so it still fits the case and the gun; anything else takes the design's own length."""
    from dataclasses import asdict

    bore = gun.barrel.bore_diameter
    current = asdict(gun.projectile)
    out = design(key, bore, current)
    d = DESIGNS[key]
    if (gun.projectile.type == "bullet" and out["type"] == "bullet" and d.group in (B, S)
            and gun.projectile.construction != "shell" and not gun.projectile.liner_material):
        k = gun.projectile.length / out["length"]
        for name in _AXIAL:
            if out.get(name):
                out[name] *= k
        for name in ("cannelure_position", "cannelure_width", "cannelure_depth"):
            out[name] = current[name]
        from .config import Projectile
        out["mass"] = built_mass(Projectile(**out), bore)
    return out


def designs_schema() -> dict:
    return {k: {"label": d.label, "group": d.group, "blurb": d.blurb} for k, d in DESIGNS.items()}


def catalogue() -> dict:
    """Names, labels and colours of every material, for the UI."""
    return {
        "metals": {k: m.label for k, m in METALS.items()},
        "jackets": {k: v[0] for k, v in JACKETS.items()},
        "fills": {k: {"label": f.label, "kind": f.kind} for k, f in FILLS.items()},
        "tracers": {k: {"label": t.label, "colour": t.colour, "brightness": t.brightness} for k, t in TRACERS.items()},
        "liners": {k: v.label for k, v in LINERS.items()},
        "fuzes": FUZES,
        "constructions": {k: c.label for k, c in CONSTRUCTIONS.items()},
    }
