"""Library of standard cartridges and their service and commercial loads, for the easy-mode builder.

Every cartridge has its metric (NATO / CIP) designation and its imperial
(SAAMI / commercial) name, e.g. "7.62x51mm NATO" and ".308 Winchester".
Dimensions are the published (SAAMI / CIP / NATO drawing) ones, rounded; the
loads are typical published figures: bullet weight, muzzle velocity from a
stated barrel, and an approximate powder charge. The builder (designer.py)
tunes the powder's burn rate so the load makes its published velocity from that
barrel, then fires it from the barrel you choose.

Values here are written in the units they are usually quoted in (mm, grains,
m/s) and converted to SI on the way out.
"""

from __future__ import annotations

from dataclasses import dataclass, field

GRAIN = 64.79891e-6   # kg
MM = 1e-3
PSI = 6894.757        # Pa
MPA = 1e6

# How the cartridges are grouped, in the order the builder lists them.
KINDS = {
    "pistol": "Pistol",
    "revolver": "Revolver",
    "intermediate": "Intermediate rifle",
    "rifle": "Full-power rifle",
    "magnum": "Magnum rifle",
    "heavy": "Heavy machine gun / anti-materiel",
    "cannon": "Cannon",
}

# Propellant the builder starts from, by kind; its burn rate is then tuned to the load.
POWDERS = {
    "pistol": {"composition": "double_base", "grain": "flake", "web": 0.08 * MM, "grain_length": 1.2 * MM},
    "revolver": {"composition": "double_base", "grain": "flake", "web": 0.11 * MM, "grain_length": 1.3 * MM},
    "intermediate": {"composition": "double_base", "web": 0.16 * MM, "form_chi": 1.0, "form_lambda": 0.0},
    "rifle": {"composition": "single_base", "grain": "tube", "web": 0.30 * MM, "grain_length": 1.6 * MM},
    "magnum": {"composition": "single_base", "grain": "tube", "web": 0.40 * MM, "grain_length": 2.0 * MM},
    "heavy": {"composition": "single_base", "grain": "tube", "web": 0.60 * MM, "grain_length": 2.5 * MM},
}

# Bullet construction, as the builder and the target describe it.
BULLET_TYPES = {
    "fmj": "Full metal jacket",
    "ap": "Armour-piercing",
    "sp": "Soft point",
    "hp": "Hollow point",
    "match": "Match (open tip)",
    "lead": "Lead (unjacketed)",
    "apfsds": "APFSDS (long-rod penetrator)",
    "service": "Service round",
    "tracer": "Tracer",
    "api": "Armour-piercing incendiary",
    "apit": "Armour-piercing incendiary tracer",
    "mp": "Multipurpose (HE, incendiary, penetrator)",
    "frangible": "Frangible",
    "he": "High explosive",
    "hei": "High-explosive incendiary",
    "heat": "Shaped charge (HEAT)",
    "apds": "APDS",
    "tp": "Target practice",
    "saphei": "Semi-armour-piercing HEI",
}


@dataclass(frozen=True)
class Load:
    id: str
    name: str
    kind: str                 # BULLET_TYPES
    mass_gr: float            # grains
    velocity: float           # m/s from the reference barrel
    barrel_mm: float          # reference barrel length (breech face to muzzle)
    charge_gr: float          # approximate powder charge
    length: float             # mm, bullet length
    ogive: float              # mm
    meplat: float = 1.0       # mm
    boat_tail: float = 0.0    # mm
    jacket: float = 0.5       # mm; 0 = unjacketed (solid)
    core: str = "lead"
    bc: float = 0.0           # lb/in^2 against drag_model; 0 = estimate
    drag: str = "G7"
    hollow_point: tuple[float, float] = (0.0, 0.0)   # diameter, depth (mm)
    exposed_core: float = 0.0  # mm
    oal: float | None = None   # mm, overall length if not the cartridge's
    note: str = ""
    # What is inside it (projectile fields: penetrator insert, fillers, tracer, fuze...); lengths in mm.
    fills: dict = field(default_factory=dict)
    design: str | None = None  # a cannon's load: this projectiles.DESIGNS type on the preset gun

    @property
    def mass(self) -> float:
        return self.mass_gr * GRAIN

    @property
    def charge(self) -> float:
        return self.charge_gr * GRAIN


@dataclass(frozen=True)
class Cartridge:
    id: str
    metric: str               # NATO / CIP designation
    imperial: str             # SAAMI / commercial name
    kind: str                 # KINDS
    bore: float               # mm, groove diameter
    twist: float              # inches per turn (standard); negative = left hand, 0 = smooth
    max_pressure: float       # Pa
    standard: str             # whose maximum pressure it is
    case: dict                # mm (and degrees for the shoulder angle)
    loads: tuple[Load, ...]
    aliases: tuple[str, ...] = ()
    template: str | None = None   # a preset gun this cartridge comes from as a whole (cannon)
    note: str = ""
    primer_energy: float = 0.15   # J the firing pin must strike with
    capacity: dict = field(default_factory=dict)  # rounds per platform, where not the platform's own

    @property
    def label(self) -> str:
        return f"{self.metric} · {self.imperial}" if self.imperial else self.metric

    def load(self, load_id: str | None) -> Load:
        if load_id is None:
            return self.loads[0]
        for ld in self.loads:
            if ld.id == load_id:
                return ld
        raise ValueError(f"{self.metric} has no load {load_id!r}; choose from {', '.join(ld.id for ld in self.loads)}")


def _case(length, oal, rim, rim_t, groove, groove_w, base, shoulder, shoulder_pos, angle, neck, body, head, primer,
          primer_depth=3.0):
    return {"length": length, "overall_length": oal, "rim_diameter": rim, "rim_thickness": rim_t,
            "groove_diameter": groove, "groove_width": groove_w, "base_diameter": base,
            "shoulder_diameter": shoulder, "shoulder_position": shoulder_pos, "shoulder_angle": angle,
            "neck_wall": neck, "body_wall": body, "head_thickness": head, "primer_diameter": primer,
            "primer_depth": primer_depth}


def _straight(length, oal, rim, rim_t, groove, base, mouth, head, primer, rimmed=False):
    """A straight-walled (pistol or revolver) case: the body tapers from the base to the mouth."""
    return _case(length, oal, rim, rim_t, rim if rimmed else groove, 1.0, base, mouth, length - 0.6, 85.0,
                 0.3, 0.38, head, primer, 2.9 if primer < 5 else 3.0)


CARTRIDGES: dict[str, Cartridge] = {c.id: c for c in [
    # ------------------------------------------------------------------ pistol
    Cartridge(
        "9x19", "9×19mm Parabellum", "9mm Luger", "pistol", 9.02, 9.84, 235 * MPA, "CIP 2,350 bar",
        _case(19.15, 29.69, 9.96, 1.27, 8.79, 1.0, 9.93, 9.68, 18.6, 85.0, 0.315, 0.35, 3.2, 4.45, 2.9),
        (
            Load("fmj124", "124 gr FMJ (NATO ball, M882)", "fmj", 124, 360, 114, 4.5, 15.5, 8.2, 2.6, jacket=0.45,
                 bc=0.150, drag="G1"),
            Load("fmj115", "115 gr FMJ (range ammunition)", "fmj", 115, 350, 102, 4.8, 14.6, 8.0, 2.6, jacket=0.45,
                 bc=0.135, drag="G1"),
            Load("jhp124", "124 gr JHP +P (duty)", "hp", 124, 380, 114, 5.3, 15.3, 7.0, 4.6, jacket=0.45,
                 bc=0.145, drag="G1", hollow_point=(3.5, 4.5), oal=29.3),
            Load("jhp147", "147 gr JHP subsonic", "hp", 147, 300, 114, 3.6, 17.0, 7.0, 4.6, jacket=0.45,
                 bc=0.170, drag="G1", hollow_point=(3.5, 4.0), oal=29.2),
            Load("fr100", "100 gr frangible (sintered copper)", "frangible", 100, 380, 114, 5.3, 15.0, 8.0, 2.8,
                 jacket=0.0, core="sintered_copper", bc=0.120, drag="G1", fills={"construction": "frangible"}),
            Load("lrn124", "124 gr lead round nose (coated)", "lead", 124, 340, 114, 4.4, 15.6, 8.4, 2.6, jacket=0.02,
                 bc=0.150, drag="G1", fills={"jacket_material": "polymer", "construction": "lrn"}),
        ),
        aliases=("9mm", "9mm NATO", "9mm Para"), primer_energy=0.06,
    ),
    Cartridge(
        "45acp", "11.43×23mm", ".45 ACP", "pistol", 11.48, -16.0, 21000 * PSI, "SAAMI 21,000 psi",
        _case(22.81, 32.40, 12.19, 1.24, 10.06, 1.0, 12.09, 12.05, 22.0, 85.0, 0.27, 0.38, 3.6, 5.33),
        (
            Load("fmj230", "230 gr FMJ (M1911 ball)", "fmj", 230, 253, 127, 4.6, 17.0, 9.0, 3.8, jacket=0.5,
                 bc=0.160, drag="G1"),
            Load("jhp230", "230 gr JHP", "hp", 230, 270, 127, 5.4, 16.8, 7.5, 6.0, jacket=0.5, bc=0.150, drag="G1",
                 hollow_point=(4.5, 5.0), oal=31.8),
            Load("jhp185", "185 gr JHP +P", "hp", 185, 305, 127, 6.5, 14.5, 6.5, 6.5, jacket=0.5, bc=0.120, drag="G1",
                 hollow_point=(5.0, 5.0), oal=31.2),
        ),
        aliases=(".45 Auto", "45 ACP"), primer_energy=0.08,
    ),
    Cartridge(
        "40sw", "10×22mm", ".40 S&W", "pistol", 10.16, 16.0, 35000 * PSI, "SAAMI 35,000 psi",
        _straight(21.59, 28.83, 10.77, 1.4, 8.8, 10.77, 10.74, 3.4, 4.45),
        (
            Load("fmj180", "180 gr FMJ", "fmj", 180, 300, 102, 5.0, 15.0, 7.0, 4.0, jacket=0.45, bc=0.165, drag="G1"),
            Load("jhp165", "165 gr JHP", "hp", 165, 335, 102, 6.0, 14.0, 6.5, 5.0, jacket=0.45, bc=0.140, drag="G1",
                 hollow_point=(4.0, 4.5)),
        ),
        aliases=("40 S&W", ".40"), primer_energy=0.06,
    ),
    Cartridge(
        "380acp", "9×17mm Browning Short", ".380 ACP", "pistol", 9.02, 16.0, 21500 * PSI, "SAAMI 21,500 psi",
        _straight(17.27, 25.0, 9.5, 1.0, 8.4, 9.5, 9.47, 3.0, 4.45),
        (
            Load("fmj95", "95 gr FMJ", "fmj", 95, 290, 95, 3.2, 12.5, 6.5, 2.5, jacket=0.4, bc=0.075, drag="G1"),
            Load("jhp90", "90 gr JHP", "hp", 90, 300, 95, 3.4, 11.5, 5.5, 4.2, jacket=0.4, bc=0.070, drag="G1",
                 hollow_point=(3.4, 3.5)),
        ),
        aliases=(".380 Auto", "9mm Kurz", "9mm Short"), primer_energy=0.06,
    ),
    Cartridge(
        "10mm", "10×25mm", "10mm Auto", "pistol", 10.16, 16.0, 37500 * PSI, "SAAMI 37,500 psi",
        _straight(25.2, 32.0, 10.8, 1.4, 8.8, 10.8, 10.74, 3.6, 5.33),
        (
            Load("fmj180", "180 gr FMJ (full power)", "fmj", 180, 380, 117, 8.4, 15.0, 7.0, 4.0, jacket=0.45,
                 bc=0.165, drag="G1"),
            Load("jhp200", "200 gr hard cast", "lead", 200, 360, 117, 8.0, 16.5, 6.5, 6.0, jacket=0.0, bc=0.160,
                 drag="G1"),
        ),
        primer_energy=0.08,
    ),
    Cartridge(
        "57x28", "5.7×28mm", "5.7 FN", "pistol", 5.70, 9.0, 345 * MPA, "CIP 3,450 bar",
        _case(28.9, 43.2, 7.95, 1.0, 6.9, 0.9, 7.95, 7.8, 22.6, 25.0, 0.3, 0.4, 3.0, 4.45, 2.9),
        (
            Load("ss190", "31 gr SS190 (steel penetrator)", "ap", 31, 716, 263, 6.2, 21.6, 12.0, 0.5, jacket=0.4,
                 core="hardened_steel", bc=0.120, drag="G7"),
            Load("ss197", "40 gr SS197SR V-Max", "match", 40, 655, 263, 5.6, 19.5, 11.5, 0.8, jacket=0.4,
                 bc=0.105, drag="G7", hollow_point=(0.8, 3.0)),
        ),
        aliases=("5.7x28", "5.7 NATO"), primer_energy=0.08,
    ),
    # ------------------------------------------------------------------ revolver
    Cartridge(
        "38spl", "9×29mmR", ".38 Special", "revolver", 9.07, 18.75, 17000 * PSI, "SAAMI 17,000 psi",
        _straight(29.34, 39.37, 11.18, 1.4, 11.18, 9.63, 9.60, 3.6, 4.45, rimmed=True),
        (
            Load("lrn158", "158 gr lead round nose", "lead", 158, 230, 102, 3.6, 17.0, 8.0, 3.5, jacket=0.0,
                 bc=0.146, drag="G1"),
            Load("fmj130", "130 gr FMJ", "fmj", 130, 255, 102, 4.2, 14.5, 7.5, 3.0, jacket=0.4, bc=0.120, drag="G1"),
        ),
        aliases=(".38 Spl", "38 Special"), primer_energy=0.08,
    ),
    Cartridge(
        "357mag", "9×33mmR", ".357 Magnum", "revolver", 9.07, 18.75, 35000 * PSI, "SAAMI 35,000 psi",
        _straight(32.77, 40.0, 11.18, 1.4, 11.18, 9.63, 9.60, 3.6, 4.45, rimmed=True),
        (
            Load("jsp158", "158 gr JSP", "sp", 158, 380, 152, 14.5, 17.0, 7.0, 4.5, jacket=0.4, bc=0.165, drag="G1",
                 exposed_core=2.0),
            Load("jhp125", "125 gr JHP", "hp", 125, 440, 152, 16.0, 13.5, 6.0, 5.0, jacket=0.4, bc=0.130, drag="G1",
                 hollow_point=(3.5, 4.5)),
        ),
        aliases=("357 Mag", ".357"), primer_energy=0.08,
    ),
    Cartridge(
        "44mag", "10.9×33mmR", ".44 Remington Magnum", "revolver", 10.90, -14.0, 36000 * PSI, "SAAMI 36,000 psi",
        _straight(32.6, 40.6, 13.06, 1.52, 13.06, 11.61, 11.60, 4.0, 5.33, rimmed=True),
        (
            Load("jsp240", "240 gr JSP", "sp", 240, 410, 152, 23.0, 18.0, 7.0, 6.0, jacket=0.5, bc=0.170, drag="G1",
                 exposed_core=2.5),
            Load("cast300", "300 gr hard cast", "lead", 300, 370, 152, 21.0, 20.5, 6.5, 7.0, jacket=0.0, bc=0.200,
                 drag="G1"),
        ),
        aliases=(".44 Mag", "44 Magnum"), primer_energy=0.08,
    ),
    Cartridge(
        "45colt", "11.5×33mmR", ".45 Colt", "revolver", 11.48, -16.0, 14000 * PSI, "SAAMI 14,000 psi",
        _straight(32.6, 40.3, 12.95, 1.52, 12.95, 12.17, 12.16, 3.8, 5.33, rimmed=True),
        (
            Load("lrnfp255", "255 gr lead flat nose", "lead", 255, 260, 190, 6.3, 18.5, 7.0, 6.5, jacket=0.0,
                 bc=0.150, drag="G1"),
        ),
        aliases=(".45 Long Colt", "45 LC"), primer_energy=0.08,
    ),
    # ------------------------------------------------------------------ intermediate
    Cartridge(
        "556", "5.56×45mm NATO", ".223 Remington", "intermediate", 5.70, 7.0, 430 * MPA, "NATO EPVAT 4,300 bar",
        _case(44.70, 57.40, 9.60, 1.14, 8.43, 1.14, 9.58, 9.00, 36.53, 23.0, 0.33, 0.45, 4.0, 4.45),
        (
            Load("m855", "62 gr M855 / SS109 (steel penetrator)", "fmj", 62, 948, 508, 26.5, 23.1, 13.5, 0.8, 2.6,
                 core="steel", bc=0.151),
            Load("m193", "55 gr M193 ball", "fmj", 55, 990, 508, 26.0, 19.0, 11.0, 0.8, 2.0, bc=0.121),
            Load("mk262", "77 gr Mk 262 (open-tip match)", "match", 77, 838, 508, 24.0, 25.4, 14.0, 1.0, 3.0,
                 bc=0.190, hollow_point=(0.8, 4.0)),
            Load("m856", "63.7 gr M856 tracer (red)", "tracer", 63.7, 925, 508, 26.5, 26.5, 13.5, 0.8, 2.6,
                 bc=0.147, fills={"tracer": "red", "tracer_length": 9.5}),
            Load("m856a1", "64 gr M856A1 tracer (dim ignition)", "tracer", 64, 925, 508, 26.5, 26.5, 13.5, 0.8, 2.6,
                 bc=0.147, fills={"tracer": "red", "tracer_length": 11.0}),
            Load("m855a1", "62 gr M855A1 EPR (copper slug, steel penetrator)", "ap", 62, 961, 508, 26.5, 25.0, 13.0, 1.4,
                 2.4, core="copper", bc=0.155,
                 fills={"insert_material": "hardened_steel", "insert_length": 9.5, "insert_diameter": 4.2}),
            Load("m995", "52 gr M995 AP (tungsten carbide)", "ap", 52, 1013, 508, 26.0, 23.5, 13.0, 0.8, 2.0,
                 core="aluminium", bc=0.140,
                 fills={"insert_material": "tungsten_carbide", "insert_length": 15.0, "insert_diameter": 4.0}),
            Load("sp55", "55 gr soft point (.223 Rem)", "sp", 55, 990, 610, 25.0, 18.5, 10.5, 1.5, 0.0, bc=0.120,
                 exposed_core=2.0),
        ),
        aliases=("5.56 NATO", ".223", "223 Rem"),
    ),
    Cartridge(
        "545", "5.45×39mm", "5.45 Soviet", "intermediate", 5.62, 7.87, 355 * MPA, "CIP 3,550 bar",
        _case(39.82, 57.00, 10.00, 1.50, 8.60, 1.20, 10.00, 9.25, 31.00, 20.0, 0.30, 0.45, 4.0, 5.33),
        (
            Load("7n6", "53 gr 7N6 (mild-steel core)", "fmj", 53, 880, 415, 21.0, 25.5, 15.0, 0.6, 3.0, core="steel",
                 bc=0.168),
            Load("7n10", "55 gr 7N10 (hardened-steel core)", "ap", 55.5, 880, 415, 21.0, 25.5, 15.0, 0.6, 3.0,
                 core="hardened_steel", bc=0.168),
            Load("7n24", "63 gr 7N24 AP (tungsten carbide)", "ap", 63.3, 840, 415, 21.0, 25.0, 14.5, 0.6, 3.0,
                 core="tungsten_carbide", bc=0.175),
            Load("7t3m", "50 gr 7T3M tracer", "tracer", 50.3, 883, 415, 21.0, 26.5, 15.0, 0.6, 2.5, bc=0.160,
                 fills={"tracer": "red", "tracer_length": 9.0}),
        ),
        aliases=("5.45x39", "5.45 Russian"),
    ),
    Cartridge(
        "762x39", "7.62×39mm", "7.62 Soviet", "intermediate", 7.92, 9.45, 355 * MPA, "CIP 3,550 bar",
        _case(38.70, 56.00, 11.35, 1.50, 9.56, 1.30, 11.35, 10.07, 30.50, 18.0, 0.35, 0.50, 4.5, 5.33),
        (
            Load("m43", "123 gr M43 / 57-N-231 (mild-steel core)", "fmj", 122, 715, 415, 23.0, 26.8, 14.5, 1.2, 3.6,
                 jacket=0.6, core="steel", bc=0.139),
            Load("bp", "123 gr 7N23 BP (hardened-steel core)", "ap", 122, 740, 415, 23.5, 26.8, 14.5, 1.2, 3.6,
                 jacket=0.6, core="hardened_steel", bc=0.139),
            Load("t45", "115 gr T-45 tracer (green)", "tracer", 115, 720, 415, 23.0, 28.0, 14.5, 1.2, 3.6, jacket=0.6,
                 core="steel", bc=0.135, fills={"tracer": "green", "tracer_length": 11.0, "jacket_material": "clad_steel"}),
            Load("bz", "119 gr BZ API (hardened steel, incendiary)", "api", 119, 730, 415, 23.5, 27.5, 14.5, 1.2, 3.6,
                 jacket=0.6, bc=0.137, fills={"insert_material": "hardened_steel", "insert_length": 16.0,
                                              "insert_diameter": 5.4, "tip_filler": "im11", "tip_filler_length": 5.0,
                                              "jacket_material": "clad_steel"}),
            Load("fmj123", "123 gr FMJ (lead core, commercial)", "fmj", 123, 710, 415, 23.0, 25.5, 13.5, 1.5, 2.0,
                 jacket=0.6, bc=0.130),
            Load("sp154", "154 gr soft point", "sp", 154, 640, 415, 21.0, 27.5, 13.0, 2.5, 0.0, jacket=0.6,
                 bc=0.140, exposed_core=2.5),
        ),
        aliases=("7.62x39", "7.62 Russian", "M43"),
    ),
    Cartridge(
        "300blk", "7.62×35mm", ".300 AAC Blackout", "intermediate", 7.82, 8.0, 55000 * PSI, "SAAMI 55,000 psi",
        _case(34.67, 57.40, 9.60, 1.14, 8.43, 1.14, 9.58, 9.20, 28.9, 16.0, 0.33, 0.45, 4.0, 4.45),
        (
            Load("otm125", "125 gr open-tip match (supersonic)", "match", 125, 670, 406, 19.0, 26.5, 15.0, 1.0, 3.0,
                 jacket=0.55, bc=0.180, hollow_point=(0.8, 4.0)),
            Load("sub220", "220 gr subsonic", "match", 220, 310, 229, 9.5, 37.5, 19.0, 1.2, 4.0, jacket=0.6,
                 bc=0.300, hollow_point=(1.0, 5.0)),
        ),
        aliases=("300 BLK", "300 AAC", ".300 Blackout"),
    ),
    # ------------------------------------------------------------------ full-power rifle
    Cartridge(
        "762x51", "7.62×51mm NATO", ".308 Winchester", "rifle", 7.82, 12.0, 415 * MPA, "NATO EPVAT 4,150 bar",
        _case(51.18, 71.10, 11.94, 1.27, 10.0, 1.2, 11.94, 11.53, 39.6, 20.0, 0.38, 0.45, 5.0, 5.33),
        (
            Load("m80", "147 gr M80 ball", "fmj", 147, 838, 559, 46.0, 28.6, 15.5, 1.0, 4.0, jacket=0.6, bc=0.200),
            Load("m118lr", "175 gr M118LR (Sierra MatchKing)", "match", 175, 790, 559, 42.0, 31.2, 17.0, 1.0, 4.0,
                 jacket=0.6, bc=0.243, hollow_point=(0.9, 4.0)),
            Load("m61", "150 gr M61 AP (hardened steel)", "ap", 150.5, 838, 559, 46.0, 33.5, 17.0, 1.0, 4.0,
                 jacket=0.6, bc=0.190, fills={"insert_material": "hardened_steel", "insert_length": 24.0,
                                              "insert_diameter": 6.0}),
            Load("m993", "127 gr M993 AP (tungsten carbide)", "ap", 126.6, 910, 559, 47.0, 33.0, 17.0, 1.0, 4.0,
                 jacket=0.6, core="aluminium", bc=0.180,
                 fills={"insert_material": "tungsten_carbide", "insert_length": 20.0, "insert_diameter": 5.8}),
            Load("m62", "142 gr M62 tracer (red)", "tracer", 142, 838, 559, 46.0, 33.0, 17.0, 1.0, 4.0, jacket=0.6,
                 bc=0.195, fills={"tracer": "red", "tracer_length": 12.0}),
            Load("m276", "142 gr M276 dim tracer", "tracer", 142, 838, 559, 46.0, 33.0, 17.0, 1.0, 4.0, jacket=0.6,
                 bc=0.195, fills={"tracer": "dim", "tracer_length": 12.0}),
            Load("sp165", "165 gr soft point (.308 Win)", "sp", 165, 820, 610, 44.0, 29.5, 15.0, 2.0, 3.0,
                 jacket=0.6, bc=0.435, drag="G1", exposed_core=2.5),
        ),
        aliases=("7.62 NATO", ".308", "308 Win"),
    ),
    Cartridge(
        "3006", "7.62×63mm", ".30-06 Springfield", "rifle", 7.82, 10.0, 60000 * PSI, "SAAMI 60,000 psi",
        _case(63.35, 84.84, 12.01, 1.24, 10.0, 1.2, 11.96, 11.20, 49.5, 17.5, 0.40, 0.45, 5.0, 5.33),
        (
            Load("m2ball", "152 gr M2 ball", "fmj", 152, 853, 610, 50.0, 28.5, 15.0, 1.0, 4.0, jacket=0.6, bc=0.205),
            Load("m2ap", "166 gr M2 AP (hardened steel)", "ap", 165.7, 828, 610, 52.0, 34.0, 17.5, 1.0, 4.0,
                 jacket=0.6, core="hardened_steel", bc=0.205),
            Load("sp180", "180 gr soft point", "sp", 180, 820, 610, 55.0, 31.5, 15.5, 2.5, 0.0, jacket=0.6,
                 bc=0.383, drag="G1", exposed_core=3.0),
        ),
        aliases=("30-06", ".30-06"),
    ),
    Cartridge(
        "65cm", "6.5×48mm", "6.5 Creedmoor", "rifle", 6.71, 8.0, 62000 * PSI, "SAAMI 62,000 psi",
        _case(48.77, 71.76, 11.95, 1.37, 10.2, 1.2, 11.95, 11.73, 39.3, 30.0, 0.35, 0.45, 5.0, 5.33),
        (
            Load("eld140", "140 gr ELD Match", "match", 140, 826, 610, 41.5, 35.0, 21.0, 0.8, 5.0, jacket=0.5,
                 bc=0.326, hollow_point=(0.8, 5.0)),
            Load("eldx143", "143 gr ELD-X (hunting)", "match", 143, 823, 610, 41.0, 35.0, 21.0, 0.8, 5.0,
                 jacket=0.5, bc=0.315, hollow_point=(0.8, 5.0)),
        ),
        aliases=("6.5 CM", "6.5 Creed"),
    ),
    Cartridge(
        "762x54r", "7.62×54mmR", "7.62 Russian", "rifle", 7.92, 9.45, 390 * MPA, "CIP 3,900 bar",
        _case(53.72, 77.16, 14.48, 1.60, 14.48, 1.0, 12.37, 11.61, 41.0, 21.0, 0.40, 0.50, 5.0, 5.33),
        (
            Load("lps", "148 gr LPS (mild-steel core)", "fmj", 148, 828, 620, 48.0, 32.5, 17.0, 1.2, 4.0, jacket=0.6,
                 core="steel", bc=0.187),
            Load("7n1", "151 gr 7N1 sniper", "match", 151, 823, 620, 48.0, 32.5, 17.5, 1.0, 4.0, jacket=0.6,
                 core="steel", bc=0.200),
            Load("b32", "154 gr B-32 API (hardened steel, incendiary)", "api", 154, 808, 620, 47.0, 35.5, 18.0, 1.2, 4.0,
                 jacket=0.6, bc=0.190, fills={"insert_material": "hardened_steel", "insert_length": 22.0,
                                              "insert_diameter": 6.0, "tip_filler": "im11", "tip_filler_length": 6.0,
                                              "jacket_material": "clad_steel"}),
            Load("bzt", "148 gr BZT API-T", "apit", 148, 818, 620, 47.0, 36.0, 18.0, 1.2, 4.0, jacket=0.6, bc=0.185,
                 fills={"insert_material": "hardened_steel", "insert_length": 17.0, "insert_diameter": 5.8,
                        "tip_filler": "im11", "tip_filler_length": 5.0, "tracer": "red", "tracer_length": 9.0,
                        "jacket_material": "clad_steel"}),
            Load("t46", "148 gr T-46 tracer (green)", "tracer", 148, 798, 620, 47.0, 34.0, 17.5, 1.2, 4.0, jacket=0.6,
                 core="steel", bc=0.180, fills={"tracer": "green", "tracer_length": 12.0, "jacket_material": "clad_steel"}),
        ),
        aliases=("7.62x54R", "7.62x54mmR"),
    ),
    Cartridge(
        "303brit", "7.7×56mmR", ".303 British", "rifle", 7.92, 10.0, 365 * MPA, "CIP 3,650 bar",
        _case(56.44, 78.1, 13.72, 1.60, 13.72, 1.0, 11.68, 10.24, 46.5, 17.0, 0.40, 0.45, 5.0, 5.33),
        (
            Load("mk7", "174 gr Mk VII ball", "fmj", 174, 744, 640, 37.5, 33.0, 17.0, 1.2, 3.0, jacket=0.6, bc=0.230),
            Load("sp180", "180 gr soft point", "sp", 180, 750, 640, 40.0, 31.0, 15.0, 2.5, 0.0, jacket=0.6,
                 bc=0.370, drag="G1", exposed_core=3.0),
        ),
        aliases=("303", ".303"),
    ),
    # ------------------------------------------------------------------ magnum rifle
    Cartridge(
        "300wm", "7.62×67mm B", ".300 Winchester Magnum", "magnum", 7.82, 10.0, 64000 * PSI, "SAAMI 64,000 psi",
        _case(66.55, 84.84, 13.03, 1.37, 11.6, 1.3, 13.0, 12.42, 57.5, 25.0, 0.38, 0.42, 5.0, 5.33),
        (
            Load("mk248m1", "220 gr Mk 248 Mod 1 (MatchKing)", "match", 220, 869, 610, 67.0, 40.0, 22.0, 1.0, 5.0, oal=86.4,
                 jacket=0.6, bc=0.310, hollow_point=(0.9, 4.0)),
            Load("mk248m0", "190 gr Mk 248 Mod 0", "match", 190, 884, 610, 70.0, 36.5, 20.0, 1.0, 4.5, jacket=0.6,
                 bc=0.277, hollow_point=(0.9, 4.0)),
        ),
        aliases=(".300 Win Mag", "300 WM"),
    ),
    Cartridge(
        "338lm", "8.6×70mm", ".338 Lapua Magnum", "magnum", 8.61, 10.0, 420 * MPA, "CIP 4,200 bar",
        _case(69.2, 93.5, 14.93, 1.52, 13.0, 1.4, 14.91, 13.82, 60.0, 20.0, 0.40, 0.50, 6.0, 5.33),
        (
            Load("scenar250", "250 gr Scenar", "match", 250, 905, 690, 93.0, 41.5, 24.0, 1.0, 6.0, jacket=0.6,
                 bc=0.322, hollow_point=(1.0, 5.0)),
            Load("smk300", "300 gr MatchKing", "match", 300, 825, 690, 88.0, 46.0, 26.0, 1.0, 6.0, jacket=0.6,
                 bc=0.383, hollow_point=(1.0, 5.0)),
        ),
        aliases=(".338 LM", "338 Lapua"),
    ),
    # ------------------------------------------------------------------ heavy
    Cartridge(
        "50bmg", "12.7×99mm NATO", ".50 BMG", "heavy", 12.95, 15.0, 54800 * PSI, "SAAMI 54,800 psi",
        _case(99.31, 138.43, 20.42, 2.08, 17.6, 2.0, 20.42, 18.82, 77.0, 15.0, 0.60, 0.80, 8.0, 8.9, 4.0),
        (
            Load("m33", "661 gr M33 ball (mild-steel core)", "fmj", 661, 887, 1143, 240.0, 58.5, 30.0, 1.5, 7.0,
                 jacket=0.9, core="steel", bc=0.670, drag="G1"),
            Load("m2ap", "708 gr M2 AP (hardened steel)", "ap", 708, 856, 1143, 238.0, 59.0, 30.0, 1.5, 7.0,
                 jacket=0.9, bc=0.640, drag="G1",
                 fills={"insert_material": "hardened_steel", "insert_length": 40.0, "insert_diameter": 10.9}),
            Load("m8", "622 gr M8 API", "api", 622, 887, 1143, 235.0, 59.0, 30.0, 1.5, 7.0, jacket=0.9, bc=0.620,
                 drag="G1", fills={"insert_material": "hardened_steel", "insert_length": 38.0, "insert_diameter": 10.4,
                                   "tip_filler": "im11", "tip_filler_length": 10.0}),
            Load("m20", "619 gr M20 API-T", "apit", 619, 887, 1143, 235.0, 60.0, 30.0, 1.5, 7.0, jacket=0.9, bc=0.610,
                 drag="G1", fills={"insert_material": "hardened_steel", "insert_length": 30.0, "insert_diameter": 10.2,
                                   "tip_filler": "im11", "tip_filler_length": 9.0, "tracer": "red",
                                   "tracer_length": 16.0}),
            Load("m17", "707 gr M17 tracer", "tracer", 707, 873, 1143, 238.0, 60.0, 30.0, 1.5, 7.0, jacket=0.9, bc=0.630,
                 drag="G1", core="steel", fills={"tracer": "red", "tracer_length": 20.0}),
            Load("mk211", "671 gr Mk 211 Raufoss (multipurpose)", "mp", 671, 915, 1143, 240.0, 61.0,
                 31.0, 1.5, 7.0, jacket=0.9, core="steel", bc=0.650, drag="G1",
                 fills={"insert_material": "tungsten_carbide", "insert_length": 19.0, "insert_diameter": 7.0,
                        "filler": "petn", "filler_length": 8.0, "tip_filler": "zirconium", "tip_filler_length": 9.0,
                        "fuze": "pyrotechnic", "fuze_delay": 2.5e-4}),
            Load("amax750", "750 gr A-MAX (match)", "match", 750, 820, 1143, 230.0, 66.0, 36.0, 1.5, 9.0,
                 jacket=0.9, bc=1.050, drag="G1", hollow_point=(1.2, 6.0)),
        ),
        aliases=(".50 Browning", "50 cal", "12.7 NATO"), primer_energy=0.4,
    ),
    # ------------------------------------------------------------------ cannon (built from their presets)
    Cartridge(
        "30x173", "30×173mm", "", "cannon", 30.0, 0.0, 0.0, "", {},
        (Load("preset", "the preset's round", "service", 0, 0, 0, 0, 0, 0),
         Load("hei", "HEI-T (self-destructing)", "hei", 0, 0, 0, 0, 0, 0, design="hei"),
         Load("apds", "APDS-T (tungsten core)", "apds", 0, 0, 0, 0, 0, 0, design="apds"),
         Load("saphei", "SAPHEI-T", "saphei", 0, 0, 0, 0, 0, 0, design="saphei"),
         Load("he_ab", "HE airburst (programmable)", "he", 0, 0, 0, 0, 0, 0, design="he_ab"),
         Load("tp", "TP-T (practice)", "tp", 0, 0, 0, 0, 0, 0, design="tp")),
        aliases=("30mm",), template="mk44_bushmaster_ii",
    ),
    Cartridge(
        "120x570", "120×570mm", "", "cannon", 120.0, 0.0, 0.0, "", {},
        (Load("preset", "the preset's round", "apfsds", 0, 0, 0, 0, 0, 0),
         Load("du", "APFSDS-T (depleted uranium)", "apfsds", 0, 0, 0, 0, 0, 0, design="apfsds_du"),
         Load("heat_fs", "HEAT-FS (DM12 / M830 type)", "heat", 0, 0, 0, 0, 0, 0, design="heat_fs"),
         Load("he", "HE (programmable airburst, DM11 type)", "he", 0, 0, 0, 0, 0, 0, design="he_ab")),
        aliases=("120mm",), template="rh120_l55",
    ),
]}
