"""Gun configuration.

Every physical parameter of the weapon lives here, so "customising the gun"
means editing one of these dataclasses (usually via a TOML file in configs/).
All values are SI: metres, kilograms, seconds, pascals, joules.
"""

from __future__ import annotations

import math
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

import numpy as np

from .autoloader import AMMUNITION, DRIVES
from .feed import AUTOLOADERS, FEED_TYPES
from .projectiles import CAPS, CONSTRUCTIONS, CORE_MATERIALS, FILLS, FUZES, JACKETS, LINERS, METALS, TRACERS
from .propellants import COMPOSITIONS, form_coefficients, grain_geometry, is_multi_perf, sliver_phase, suppressant


@dataclass
class Barrel:
    bore_diameter: float   # m
    travel: float          # m, projectile travel from seated position to muzzle
    chamber_volume: float  # m^3, empty chamber volume behind the seated projectile
    # Outside shape (3D view only). None = scaled reference.
    breech_diameter: float | None = None  # m, barrel shank at the chamber
    muzzle_diameter: float | None = None  # m, barrel at the muzzle
    # Gas space the fluid solver uses: "cylinder" is a bore-sized cylinder of
    # chamber_volume; "case" is the inside of the [case], shoulder and neck
    # included, up to the projectile base (chamber_volume is then ignored).
    chamber_shape: str = "cylinder"
    # Rifling (gun_sim/rifling.py). twist is the travel per turn: positive is a
    # right-hand twist, negative left-hand, 0 a smooth bore. None = scaled reference.
    twist: float | None = None         # m per turn
    groove_depth: float | None = None  # m, land height cut into the projectile
    freebore: float = 0.0              # m, travel before the bearing surface meets the lands
    leade_angle: float = 1.5           # degrees, half-angle of the forcing cone
    # Bore evacuator (gun_sim/evacuator.py): a reservoir round the barrel that the shot's gas
    # charges through inclined nozzles and that then blows it back out towards the muzzle,
    # drawing the fumes out of the bore. 0 = none.
    evacuator_position: float = 0.0          # m of projectile travel from the seat to the nozzles
    evacuator_volume: float = 0.0            # m^3, the reservoir
    evacuator_nozzles: int = 0               # count, round the barrel
    evacuator_nozzle_diameter: float = 0.0   # m
    evacuator_angle: float = 30.0            # degrees the nozzles lean from the bore axis, towards the muzzle
    # Revolver (gun_sim/revolver.py): the cylinder's chambers run `cylinder_length` from the case head to
    # its front face, and the barrel's rear face stands `cylinder_gap` ahead of that. Once the projectile's
    # base is out of the cylinder, gas escapes through the gap all round. 0 = no gap.
    cylinder_gap: float = 0.0                # m
    cylinder_length: float | None = None     # m; None = the overall length + 1 mm

    @property
    def bore_area(self) -> float:
        return math.pi * self.bore_diameter**2 / 4


# Reference shape used to fill in any geometry a config leaves out: a generic
# 7.62 mm full-power rifle round, scaled by the gun's bore diameter. Angles are
# in degrees and are not scaled.
_REF_BORE = 7.82e-3
_REF_GEOMETRY = {
    "barrel": {
        "breech_diameter": 30.0e-3,
        "muzzle_diameter": 16.0e-3,
        "twist": 0.2794,          # 1 turn in 11 in, about 36 calibres
        "groove_depth": 0.1e-3,
    },
    "projectile": {
        "length": 28.6e-3,
        "ogive_length": 15.5e-3,
        "meplat_diameter": 1.0e-3,
        "boat_tail_length": 4.0e-3,
    },
    "case": {
        "length": 51.2e-3,
        "overall_length": 71.0e-3,
        "rim_diameter": 11.94e-3,
        "rim_thickness": 1.27e-3,
        "groove_diameter": 10.0e-3,
        "groove_width": 1.2e-3,
        "base_diameter": 11.94e-3,
        "shoulder_diameter": 11.53e-3,
        "shoulder_position": 39.6e-3,
        "neck_wall": 0.38e-3,
        "body_wall": 0.45e-3,
        "head_thickness": 5.0e-3,
        "primer_diameter": 5.33e-3,
        "primer_depth": 3.0e-3,
    },
}


# "steel" is a soft (mild) steel core; "hardened_steel" an armour-piercing one; "tungsten" a heavy alloy.
# The full list (and every fill, jacket, tracer and liner) is in projectiles.py.
# "bullet": full calibre, spun by the rifling (a shell too); "apfsds": a fin-stabilised long rod in a
# discarding sabot; "apds": a spin-stabilised core in a discarding sabot; "finned": full calibre on a tail
# boom with fins (HEAT-FS).
PROJECTILE_TYPES = ("bullet", "apfsds", "apds", "finned")
SUB_CALIBRE = ("apfsds", "apds")


@dataclass
class Projectile:
    mass: float                         # kg
    shot_start_pressure: float = 30e6   # Pa, base pressure needed to engrave and start moving
    bore_resistance: float = 0.0        # Pa, resistive pressure while travelling (friction)
    # Extra resistance while the rifling is cut into the projectile, peaking once
    # it is engraved to full depth (see gun_sim/rifling.py). 0 = none.
    engraving_pressure: float = 0.0     # Pa
    # Shape (3D view only for now; diameter is the bore diameter). None = scaled reference.
    length: float | None = None            # m, base to tip
    ogive_length: float | None = None      # m, tangent-ogive nose
    meplat_diameter: float | None = None   # m, flat tip
    boat_tail_length: float | None = None  # m, 0 for a flat base
    boat_tail_angle: float = 9.0           # degrees
    # Shape variants (3D view only; the solvers ignore them). Every length is 0 = absent.
    ogive_radius_ratio: float = 1.0        # ogive radius / tangent-ogive radius: 1 = tangent, > 1 = secant
    hollow_point_diameter: float = 0.0     # m, cavity in the tip
    hollow_point_depth: float = 0.0        # m
    cannelure_position: float = 0.0        # m, centre of the crimp groove, measured from the base
    cannelure_width: float = 0.0           # m
    cannelure_depth: float = 0.0           # m
    # Construction: jacket_thickness 0 = solid projectile of one metal.
    jacket_thickness: float = 0.0          # m, jacket over a core
    core_material: int | str = 0           # index into (or a name from) CORE_MATERIALS
    exposed_core_length: float = 0.0       # m, soft point: core left bare at the tip
    # Discarding sabot ("apfsds"): a fin-stabilised long rod held in the bore by a sabot whose
    # petals fall away at the muzzle. `mass` is the whole launch package (the gas drives it),
    # `length` the rod from its tail to its tip, and the gas pushes on the sabot's rear face,
    # `sabot_offset` ahead of the rod's tail (the fins reach back into the propellant). The
    # trajectory flies the rod alone. The shape fields above describe the rod's nose.
    # "apds" is the same with a spin-stabilised core and no fins; "finned" is full calibre on a tail boom
    # `boom_length` long with fins at its end (HEAT-FS), the gas pushing on the body's rear face.
    type: str = "bullet"                   # PROJECTILE_TYPES
    penetrator_mass: float | None = None   # kg, the rod and fins that fly on; None = 60 % of mass
    penetrator_diameter: float | None = None  # m; None = a fifth of the bore (APDS: 0.45)
    fin_span: float | None = None          # m, across the fins; None = 3.5 rod diameters (finned: 0.95 bores)
    fin_length: float | None = None        # m, along the rod; None = 6 rod diameters (finned: 0.6 bores)
    sabot_length: float | None = None      # m, along the rod; None = 1.2 bores (APDS: 85 % of the core)
    sabot_offset: float | None = None      # m, rod tail to the sabot's rear face; None = 1.5 fin lengths (APDS: 0)
    sabot_material: str = "aluminium"      # a JACKETS name: aluminium, steel or polymer
    boom_length: float = 0.0               # m, finned: the tail boom behind the body
    # What it is made of and what is in it (gun_sim/projectiles.py). Every length 0 = the default, a "" name = none.
    construction: str = ""                 # CONSTRUCTIONS: how it behaves in a target; "" = from its shape
    jacket_material: str = "gilding_metal"  # JACKETS
    insert_material: str = ""              # a penetrator inside the core: a CORE_MATERIALS name
    insert_length: float = 0.0             # m; 0 = 60 % of the room
    insert_diameter: float = 0.0           # m; 0 = 72 % of the cavity
    insert_position: float = 0.0           # m from the cavity's floor to its rear; 0 = up behind the fills
    filler: str = ""                       # FILLS (or a core material): explosive, incendiary, smoke, inert
    filler_length: float = 0.0             # m; 0 = all the room left (a shaped charge: half the cavity)
    filler_position: float = 0.0           # m from the cavity's floor to its rear; 0 = up front
    tip_filler: str = ""                   # FILLS in the nose ("polymer" = a polymer tip)
    tip_filler_length: float = 0.0         # m; 0 = 0.6 bores
    tracer: str = ""                       # TRACERS, in a cavity in the base
    tracer_length: float = 0.0             # m of composition; 0 = 1.5 bores (it burns down it)
    liner_material: str = ""               # LINERS: a shaped-charge cone in front of the filler (HEAT)
    liner_angle: float = 30.0              # degrees, the cone's half-angle
    liner_thickness: float = 0.0           # m; 0 = 2.5 % of its diameter
    cap: str = "none"                      # "none", "penetrating", "ballistic" or "both" (APCBC)
    fuze: str = "none"                     # FUZES
    fuze_delay: float = 0.0                # s after impact (delay, base, pyrotechnic)
    fuze_time: float = 0.0                 # s of flight: a time fuze's burst, any other's self-destruct (0 = none)
    arming_distance: float = 0.0           # m from the muzzle before the fuze is armed

    # Names that may be given as "" (none); the UI sends None for them.
    _NAMES = ("construction", "insert_material", "filler", "tip_filler", "tracer", "liner_material")

    def __post_init__(self):
        if isinstance(self.core_material, str):
            try:
                self.core_material = CORE_MATERIALS.index(self.core_material.lower())
            except ValueError:
                raise ValueError(
                    f"core_material must be one of {', '.join(CORE_MATERIALS)} (or 0..{len(CORE_MATERIALS) - 1})"
                ) from None
        for name in self._NAMES:
            if getattr(self, name) is None:
                setattr(self, name, "")
        if self.jacket_material is None:
            self.jacket_material = "gilding_metal"
        if self.sabot_material is None:
            self.sabot_material = "aluminium"
        if self.cap is None:
            self.cap = "none"
        if self.fuze is None:
            self.fuze = "none"

    @property
    def core_name(self) -> str:
        return CORE_MATERIALS[int(self.core_material)]

    def validate_shape(self) -> None:
        if self.type not in PROJECTILE_TYPES:
            raise ValueError(f"projectile.type must be one of {', '.join(PROJECTILE_TYPES)}, not {self.type!r}")
        if self.type in SUB_CALIBRE:
            if not 0 < self.penetrator_mass < self.mass:
                raise ValueError("projectile.penetrator_mass must be positive and less than the launch mass (rod and sabot)")
            for name in ("penetrator_diameter", "sabot_length") + (("fin_span", "fin_length") if self.type == "apfsds" else ()):
                if getattr(self, name) <= 0:
                    raise ValueError(f"projectile.{name} must be positive")
            if self.sabot_offset < 0 or self.sabot_offset + self.sabot_length > self.length:
                raise ValueError("projectile: the sabot (sabot_offset + sabot_length) must sit on the rod")
            if self.type == "apfsds" and self.fin_span < self.penetrator_diameter:
                raise ValueError("projectile.fin_span must be at least the rod's diameter")
        if self.sabot_material not in ("aluminium", "steel", "polymer"):
            raise ValueError("projectile.sabot_material must be aluminium, steel or polymer")
        if self.type == "finned":
            if not 0 < self.boom_length < 0.8 * self.length:
                raise ValueError("projectile.boom_length (finned) must be positive and shorter than 80 % of the length")
            if self.fin_length <= 0 or self.fin_span <= 0:
                raise ValueError("projectile.fin_span and fin_length must be positive")
        elif self.boom_length:
            raise ValueError("projectile.boom_length is a finned round's tail boom: set projectile.type = \"finned\"")
        if not 1.0 <= self.ogive_radius_ratio <= 10.0:
            raise ValueError("ogive_radius_ratio must be between 1 (tangent) and 10")
        if float(self.core_material) not in range(len(CORE_MATERIALS)):
            raise ValueError(f"core_material must be one of {', '.join(CORE_MATERIALS)} (0..{len(CORE_MATERIALS) - 1})")
        for name in ("hollow_point_diameter", "hollow_point_depth", "cannelure_position",
                     "cannelure_width", "cannelure_depth", "jacket_thickness", "exposed_core_length",
                     "insert_length", "insert_diameter", "insert_position", "filler_length", "filler_position",
                     "tip_filler_length", "tracer_length", "liner_thickness", "fuze_delay", "fuze_time",
                     "arming_distance"):
            if getattr(self, name) < 0:
                raise ValueError(f"projectile.{name} cannot be negative")
        self._validate_fills()

    def _validate_fills(self) -> None:
        def one_of(name, options, blank=True):
            v = getattr(self, name)
            if (v or blank is False) and v not in options:
                raise ValueError(f"projectile.{name} must be one of {', '.join(options)}{' (or none)' if blank else ''}, "
                                 f"not {v!r}")
        one_of("construction", CONSTRUCTIONS)
        one_of("jacket_material", JACKETS, blank=False)
        one_of("insert_material", METALS)
        one_of("filler", (*FILLS, *(m for m in METALS if m not in FILLS)))
        one_of("tip_filler", (*FILLS, *(m for m in METALS if m not in FILLS)))
        one_of("tracer", TRACERS)
        one_of("liner_material", LINERS)
        one_of("cap", CAPS, blank=False)
        one_of("fuze", FUZES, blank=False)
        if self.liner_material:
            if FILLS.get(self.filler or "comp_b", FILLS["inert"]).kind != "explosive":
                raise ValueError("a shaped-charge liner needs an explosive filler behind it (projectile.filler)")
            if not 10 <= self.liner_angle <= 70:
                raise ValueError("projectile.liner_angle must be between 10 and 70 degrees (the cone's half-angle)")
            if self.insert_material:
                raise ValueError("a shaped charge has no room for a penetrator insert")
        if self.fuze == "time" and self.fuze_time <= 0:
            raise ValueError("a time fuze needs its burst time (projectile.fuze_time)")
        if self.fuze_delay > 0.05:
            raise ValueError("projectile.fuze_delay must be at most 50 ms")
        if self.type in SUB_CALIBRE and (self.liner_material or self.filler in FILLS and FILLS[self.filler].kind == "explosive"):
            raise ValueError("a sub-calibre rod carries no explosive: use a full-calibre type for HE or HEAT")
    # External ballistics (gun_sim/exterior.py). The coefficient is in kg/m^2 (mass over
    # i * d^2; 1 lb/in^2 = 703.07 kg/m^2) for the chosen standard drag function. None =
    # estimated from mass, bore diameter and the shape fields above.
    drag_model: str = "G7"                          # "G1" or "G7"
    ballistic_coefficient: float | None = None      # kg/m^2


@dataclass
class Propellant:
    """Propellant chemistry, burn law and grain shape.

    The thermochemistry and burn-law fields may be left out when a `composition`
    is named (see propellants.COMPOSITIONS); explicit values always win. A named
    `grain` fills in web, the form function and, for multi-perforated grains,
    the sliver phase. The geometry fields use 0 for "not given".
    """
    charge_mass: float      # kg
    force: float | None = None            # J/kg, propellant force (impetus) f = R * T_flame
    covolume: float | None = None         # m^3/kg, Noble-Abel covolume b
    gamma: float | None = None            # ratio of specific heats of the product gas
    density: float | None = None          # kg/m^3, solid grain density
    web: float | None = None              # m, full web thickness (grain burns from both faces)
    burn_rate_coeff: float | None = None  # a in Vieille's law r = a * p^n, units (m/s)/Pa^n
    burn_rate_exp: float | None = None    # n in Vieille's law
    # Form function psi(z) = chi * z * (1 + lambda * z + mu * z^2), where z is the
    # burnt fraction of the web and psi the burnt fraction of the mass. chi=1,
    # lambda=0, mu=0 is a "neutral" grain (e.g. long tube); lambda < 0 is degressive.
    form_chi: float | None = None
    form_lambda: float | None = None
    form_mu: float | None = None
    # Mean molar mass of the product gas. Sets its gas constant R = R_u / M, and
    # so its flame temperature f / R. Only the muzzle blast (sound) model needs it.
    molar_mass: float | None = None       # kg/mol, 0.025 if neither given nor from a composition
    # Library choices (see gun_sim/propellants.py).
    composition: str | None = None        # "single_base", "double_base" or "triple_base"
    grain: str | None = None              # e.g. "tube", "sphere", "flake", "7-perf", "19-perf"
    grain_length: float = 0.0             # m, tube/flake length or multi-perf 2c; 0 = not given
    grain_diameter: float = 0.0           # m, outer diameter of a multi-perf grain; 0 = not given
    perforation_diameter: float = 0.0     # m, bore of each perforation; 0 = not given
    # Sliver phase of a multi-perforated grain: psi = form_chi_s z (1 + form_lambda_s z)
    # for 1 < z <= form_z_k, where it reaches 1. Filled in from the grain geometry.
    form_chi_s: float | None = None
    form_lambda_s: float | None = None
    form_z_k: float = 1.0
    # Flash suppressant (see propellants.SUPPRESSANTS): a potassium salt making up
    # suppressant_fraction of the charge mass. force, molar_mass and the composition
    # describe the propellant without it; impetus and gas_constant include it.
    flash_suppressant: str | None = None  # "potassium_sulfate", "potassium_nitrate", "potassium_cryolite"
    suppressant_fraction: float = 0.0     # kg of salt per kg of charge

    # Fields that must be known before the propellant can be used.
    _REQUIRED = ("force", "covolume", "gamma", "density", "web", "burn_rate_coeff", "burn_rate_exp")

    def __post_init__(self):
        if self.composition is not None:
            if self.composition not in COMPOSITIONS:
                raise ValueError(f"unknown composition {self.composition!r}; "
                                 f"choose from {', '.join(COMPOSITIONS)}")
            for key, value in COMPOSITIONS[self.composition].items():
                if getattr(self, key) is None:
                    setattr(self, key, value)
        if self.molar_mass is None:
            self.molar_mass = 0.025

        if self.grain is not None:
            length = self.grain_length or None
            diameter = self.grain_diameter or None
            perf = self.perforation_diameter or None
            web, diameter = grain_geometry(self.grain, self.web, length, diameter, perf)
            if self.web is None:
                self.web = web
            if diameter is not None:
                self.grain_diameter = diameter
            chi, lam, mu = form_coefficients(self.grain, self.web, length, self.grain_diameter or None, perf)
            if self.form_chi is None:
                self.form_chi = chi
            if self.form_lambda is None:
                self.form_lambda = lam
            if self.form_mu is None:
                self.form_mu = mu

        missing = [name for name in self._REQUIRED if getattr(self, name) is None]
        if missing:
            raise ValueError(f"[propellant] is missing {', '.join(missing)}; give them explicitly "
                             f"or name a composition ({', '.join(COMPOSITIONS)})")

        if self.form_chi is None:
            self.form_chi = 1.0
        if self.form_lambda is None:
            self.form_lambda = 0.0
        if self.form_mu is None:
            self.form_mu = 0.0

        if self.grain is not None and is_multi_perf(self.grain) and self.form_chi_s is None:
            psi_1 = float(self._form(1.0))
            self.form_chi_s, self.form_lambda_s, self.form_z_k = sliver_phase(
                self.web, self.perforation_diameter, psi_1)

        if not 0.0 <= self.suppressant_fraction <= 0.1:
            raise ValueError("suppressant_fraction must be between 0 and 0.1")
        if self.suppressant_fraction and self.flash_suppressant is None:
            raise ValueError("suppressant_fraction needs a flash_suppressant")
        suppressant(self.flash_suppressant)   # rejects an unknown name
        if self.impetus <= 0:
            raise ValueError("the flash suppressant leaves the charge no impetus")

    @property
    def gas_constant(self) -> float:
        """Specific gas constant of the products, J/(kg K).

        The suppressant's particles go with the gas but add no pressure: R is per kg of both.
        """
        return 8.314462618 / self.molar_mass * (1 - self.suppressant_fraction)

    @property
    def impetus(self) -> float:
        """Force (J/kg of charge) with the flash suppressant: its mass makes no gas, and it
        takes (or gives) its heat from the flame, R T_flame = f (1 - w) - (gamma - 1) w sink."""
        w = self.suppressant_fraction
        return self.force * (1 - w) - (self.gamma - 1) * w * suppressant(self.flash_suppressant)["sink"]

    @property
    def z_burnout(self) -> float:
        """Web fraction z at which all the charge is burnt: 1, or z_k for multi-perf grains."""
        return self.form_z_k

    def _form(self, z):
        """Unclipped form function, so that a bad form can be detected."""
        z = np.asarray(z, dtype=float)
        z1 = np.minimum(z, 1.0)
        psi = self.form_chi * z1 * (1 + self.form_lambda * z1 + self.form_mu * z1**2)
        if self.form_chi_s is not None:
            z2 = np.minimum(z, self.form_z_k)
            psi2 = self.form_chi_s * z2 * (1 + self.form_lambda_s * z2)
            psi = np.where(z > 1.0, psi2, psi)
        return psi

    def burnt_fraction(self, z):
        """psi(z): fraction of charge mass burnt once fraction z of the web is gone.

        Accepts a float or an array, returns the same shape with values in [0, 1].
        """
        psi = np.clip(self._form(z), 0.0, 1.0)
        return float(psi) if psi.ndim == 0 else psi

    def web_regression_rate(self, p):
        """dz/dt at pressure p (Pa)."""
        return 2 * self.burn_rate_coeff * p**self.burn_rate_exp / self.web


@dataclass
class Case:
    """Cartridge case geometry (bottleneck, rimless or rimmed).

    Drawn by the 3D view; the fluid solver uses its inside with barrel.chamber_shape = "case".
    Lengths are measured from the case head. None = scaled reference value.
    """
    length: float | None = None             # m, head to mouth
    overall_length: float | None = None     # m, head to projectile tip (seating)
    rim_diameter: float | None = None       # m
    rim_thickness: float | None = None      # m
    groove_diameter: float | None = None    # m, extractor groove; >= base diameter for none
    groove_width: float | None = None       # m
    base_diameter: float | None = None      # m, body just above the groove
    shoulder_diameter: float | None = None  # m
    shoulder_position: float | None = None  # m, head to start of the shoulder
    shoulder_angle: float = 20.0            # degrees from the axis-normal plane
    neck_wall: float | None = None          # m
    body_wall: float | None = None          # m, near the shoulder (thickens towards the head)
    head_thickness: float | None = None     # m, solid web at the base
    primer_diameter: float | None = None    # m
    primer_depth: float | None = None       # m, primer pocket depth
    # Combustible case: the body is felted nitrocellulose that burns with the charge (count its
    # mass in the charge); only a metal stub base, `stub_length` long from the head, is left to
    # extract. False = a whole metal case.
    combustible: bool = False
    stub_length: float | None = None        # m; None = the head thickness plus a fifth of the base diameter
    material: str = "brass"                 # the metal case or stub: "brass" or "steel"


CASE_MATERIALS = {"brass": 8500.0, "steel": 7850.0}   # kg/m^3


@dataclass
class Ignition:
    pressure: float = 5e6  # Pa, chamber pressure produced by the igniter/primer
    # Energy the firing pin has to strike the primer with to fire it (a rifle primer's 0.15 J; a pistol
    # primer's cup is softer). Less, and it is a light strike (gun_sim/action.py).
    strike_energy: float = 0.15            # J
    # Two-phase grain bed only (solver.two_phase; gun_sim/grainbed.py): the primer's gas comes out
    # of the flash hole over `duration`, and a grain lights when its surface reaches this temperature.
    duration: float = 2e-4                     # s
    grain_ignition_temperature: float = 480.0  # K


@dataclass
class SolverSettings:
    cells: int = 100          # finite-volume cells between breech and projectile base
    cfl: float = 0.5          # Courant number for the fluid solver
    max_time: float = 0.05    # s, give up if the projectile hasn't left the muzzle
    record_every: int = 10    # fluid steps between history samples
    lumped_dt: float = 1e-7   # s, fixed step for the lumped-parameter model
    # Fluid model: wall friction and heat loss to the barrel while the projectile
    # is in the bore too (they always act during blowdown). Off by default so
    # the fluid model stays comparable with the lumped one, which has neither.
    wall_losses: bool = False
    # Fluid model: a two-phase grain bed (gun_sim/grainbed.py). The grains move, drag on the gas and
    # light as the primer's flame reaches them, instead of all lighting at once where they were loaded.
    two_phase: bool = False
    # 2D axisymmetric solver (gun_sim/axisym.py) for the muzzle device and the gas port.
    device_resolution: float = 4.0  # cells across the bore diameter
    device_time: float = 0.0025     # s after exit the muzzle device is solved in 2D (then a venting vessel)
    gas_port_2d: bool = True        # gas action: find the port's discharge coefficient in 2D
    # Muzzle flash and smoke (gun_sim/plume.py): the gas leaving the muzzle solved in 2D out into the air.
    plume_resolution: float = 2.0   # cells across the bore diameter at the muzzle (they grow further out)
    plume_time: float = 0.002       # s after exit the plume is solved for


DEVICE_TYPES = ("none", "brake", "suppressor", "flash_hider")


@dataclass
class MuzzleDevice:
    """A muzzle brake, suppressor or flash hider, solved in 2D (gun_sim/devices.py).

    All are axisymmetric: a tube of outer_diameter and length on the muzzle,
    with `baffles` plates whose holes are bore + bore_clearance across. A brake's
    chambers vent sideways through slots that open `vent_fraction` of the
    circumference; a suppressor is closed except for its front hole, with a
    blast chamber before the first baffle. Baffles lean back by baffle_angle
    (0 = flat plates; a cone baffle points its tip towards the muzzle). A flash
    hider has no baffles: a collar on the muzzle, then a bore that opens at
    flare_angle between prongs (`baffles` of them, drawn in 3D; the slots
    between them open vent_fraction of the circumference) to an open front.
    None = scaled from the bore.
    """
    type: str = "none"
    length: float | None = None           # m
    outer_diameter: float | None = None   # m
    baffles: int | None = None
    bore_clearance: float = 1.0e-3        # m, baffle hole diameter over the bore
    wall: float = 2.0e-3                  # m, tube wall and baffle thickness
    blast_chamber: float | None = None    # m, suppressor: muzzle to the first baffle
    baffle_angle: float = 0.0             # degrees
    vent_fraction: float = 0.5            # brake, flash hider: share of the circumference open at the vents/slots
    flare_angle: float = 4.0              # degrees, flash hider: half-angle its bore opens at
    mass: float | None = None             # kg, added to the gun; None = from its steel


ACTION_TYPES = ("bolt", "gas", "direct_impingement", "blowback", "short_recoil", "roller_delayed", "lever_delayed",
                "gas_delayed", "chain", "sliding_wedge", "revolver", "rotary")
STANCES = ("shoulder", "hands", "free", "mount")
LOCKINGS = ("block", "tilt")
TRIGGER_TYPES = ("single_action", "double_action", "double_action_only", "striker")
FIRE_MODES = ("auto", "semi")
CYLINDER_LOADING = ("swing_out", "gate")


@dataclass
class Action:
    """How the gun reloads, and the mass properties that set its recoil (gun_sim/action.py).

    "bolt" is worked by hand; "gas" taps gas from a port in the barrel into a
    cylinder whose piston drives the bolt carrier; "direct_impingement" pipes
    that gas down a tube into the carrier itself, which the locked bolt's tail
    drives back like a piston in a cylinder; "blowback" has an unlocked
    bolt held shut only by its own mass and spring; "short_recoil" has the
    barrel and slide recoil locked together until the barrel stops and unlocks.
    Delayed blowbacks: "roller_delayed" and "lever_delayed" split the bolt into
    a light head and a carrier that rollers (a lever) drive delay_ratio times
    as fast; "gas_delayed" has gas from a port by the chamber push a piston on
    the slide forwards. None = worked out from the cartridge (see action.py).

    Externally powered and cannon breeches: "chain" is a chain gun, whose bolt
    rides a master link that a motor drives round a rectangular track, so the
    motor, not the shot, works the action (bolt_mass is the bolt and carrier);
    "sliding_wedge" is a vertical sliding-block breech, locked while the gun
    recoils, that the opening cam on the cradle drops as the gun runs out again
    (bolt_mass is the block, bolt_travel its drop, spring_rate and
    spring_preload its closing spring), and whose extractors throw the case or
    its stub out.

    "revolver": the rounds sit in the chambers of a cylinder that the hand turns
    a chamber on as the hammer is cocked (by the trigger, or a single action's
    by the thumb) and the cylinder stop locks in line with the bore. Nothing
    moves under the shot; the gas escapes through the gap between the cylinder
    and the barrel (barrel.cylinder_gap). bolt_mass is unused.

    "rotary": a rotary gun (gun_sim/rotary.py): a Gatling's cluster of barrels, each with its
    own bolt on a cam, or a revolver cannon's drum of chambers behind one barrel, turned by an
    electric or hydraulic motor, by the gun's own gas or by its barrels' recoil. bolt_mass is
    each bolt (or rammer), bolt_travel its stroke, barrel_mass each barrel, friction the drag
    on the rotor at its bolt circle, drive_mass the motor and gears felt there; motor_power,
    motor_rpm and pinion_teeth are the motor's; a gas drive uses the gas system's fields, and a
    recoil drive spring_rate and spring_preload for the barrels' return spring.
    """
    type: str = "bolt"
    gun_mass: float = 4.0               # kg, the whole gun unloaded, bolt included
    bolt_mass: float = 0.45             # kg, the part that cycles: bolt + carrier (+ piston), or a slide
    barrel_mass: float | None = None    # kg, short recoil: barrel moving with the slide; None = from its steel
    bolt_travel: float | None = None    # m, bolt stroke to the rear stop; None = enough to feed + 8 mm
    spring_rate: float = 700.0          # N/m, return spring
    spring_preload: float = 50.0        # N, return spring force with the bolt closed
    unlock_travel: float | None = None  # m, gas: carrier travel before the bolt unlocks (None = 6 mm, 7 mm direct impingement);
                                        # short recoil: barrel travel before it stops (None = 3 mm);
                                        # roller/lever delayed: carrier travel until the delay ends (None = 5 / 6 mm)
    # Roller/lever delayed blowback: carrier speed over bolt head speed while delayed
    # (None = 4 roller, 6 lever), and the bolt head's share of bolt_mass (None = a fifth).
    delay_ratio: float | None = None
    bolt_head_mass: float | None = None  # kg
    rear_restitution: float = 0.3       # bounce of the bolt off the rear stop (buffer)
    battery_restitution: float = 0.05   # bounce of the bolt as it closes
    feed_force: float = 15.0            # N, drag on the bolt while it strips and chambers a round
    friction: float = 0.0               # N, sliding friction on the bolt group all the way (rails, a tilting carrier)
    # Hammer (self-loading actions): cocked by the carrier, held by the sear, tripped by the
    # closing carrier in a burst. Off: each shot of a burst fires 3 ms after the bolt is home.
    hammer: bool = False
    hammer_inertia: float = 6e-6        # kg m^2, about its pivot
    hammer_spring_torque: float = 0.35  # N m, hammer spring with the hammer down on the firing pin
    hammer_spring_rate: float = 0.25    # N m/rad
    hammer_angle: float = 60.0          # degrees back from the firing pin to where the sear holds it
    hammer_cock_travel: float = 0.025   # m of carrier travel over which the carrier pushes it down
    hammer_trip_travel: float = 0.5e-3  # m: the carrier picks it up, and trips the auto sear, this far from home
    hammer_friction: float = 0.15       # friction coefficient of the hammer's face on the carrier
    # Rate reducer (AKM): an inertial lever the hammer swings with it over the start of its fall.
    rate_reducer_inertia: float = 0.0   # kg m^2; 0 = none
    rate_reducer_angle: float = 20.0    # degrees of the hammer's fall it drags the lever through
    # Striker (trigger.type = "striker"): a spring-driven firing pin in the slide. Closing, the slide
    # compresses its spring the first striker_precock of its travel against the trigger bar; the trigger
    # pull compresses it the rest of the way and lets it go.
    striker_mass: float = 6e-3          # kg, the striker and its spring's moving share
    striker_spring_preload: float = 5.0  # N with the striker forward on the primer
    striker_spring_rate: float = 2500.0  # N/m
    striker_travel: float = 6.5e-3      # m from forward to fully cocked
    striker_precock: float = 0.6        # share of the travel the slide cocks it
    # Short recoil: how the barrel unlocks from the slide (the 3D view's): "block", a locking block that
    # drops out from under the slide (Walther, Beretta), or "tilt", the barrel's breech dropping on a link
    # or cam (Browning).
    locking: str = "block"
    # Revolver: the cylinder, turned a chamber by the hand as the hammer is cocked, then locked by the stop.
    cylinder_mass: float = 0.3          # kg, empty
    cylinder_radius: float | None = None  # m, its axis to the chambers' (the bore's); None = room for the rims
    # Gas system.
    gas_port_position: float | None = None  # m of projectile travel from its seat to the port; None = 75 % of travel
    gas_port_diameter: float = 1.2e-3   # m
    piston_diameter: float = 10.0e-3    # m
    gas_volume: float = 1.0e-6          # m^3, gas cylinder with the piston forward
    gas_stroke: float = 0.008           # m, piston travel before the cylinder vents
    # Direct impingement: the tube from the gas block back to the carrier key.
    gas_tube_length: float | None = None  # m; None = from the port to the case head, plus a case length
    gas_tube_diameter: float = 1.8e-3     # m, inside
    # Chain gun: a DC motor (torque falling linearly with speed) drives the chain; the bolt
    # dwells locked while the master link crosses the front of the track and again, open,
    # across the back, where the feeder (driven off the same chain) indexes the next round.
    chain_rate: float = 200.0           # rounds/min the motor would drive with no load
    motor_power: float = 1500.0         # W, the motor's peak power (a quarter of stall force x free speed)
    drive_mass: float = 4.0             # kg: motor rotor, gears and chain as felt at the master link
    chain_width: float | None = None    # m, across the track (the dwells); None = 0.35 overall lengths
    sprocket_radius: float | None = None  # m, the track's corners; None = a quarter of its width
    # The drive's sound: the motor's speed with no load (the gearbox makes up the rest of the
    # ratio down to the sprocket), its first pinion's teeth, and the drive chain's pitch.
    motor_rpm: float = 6000.0
    pinion_teeth: int = 14
    drive_chain_pitch: float = 12.7e-3  # m (a 1/2" roller chain)
    # Rotary gun (gun_sim/rotary.py).
    rotary_layout: str = "gatling"      # "gatling" (a cluster of barrels) or "revolver" (a drum of chambers, one barrel)
    rotary_drive: str = "electric"      # "electric", "hydraulic", "gas" or "recoil"
    barrels: int = 6                    # gatling
    chambers: int = 5                   # revolver: the drum's chambers
    rotary_rate: float = 4000.0         # rounds/min: an electric motor's free speed, a hydraulic one's flow limit,
                                        # a self-driven gun's rated rate
    rotor_inertia: float | None = None  # kg m^2, the barrel cluster or drum, empty; None = from the barrels' steel
    cluster_radius: float | None = None  # m, rotor axis to each bore (chamber); None = the barrels side by side
    dwell_angle: float = 40.0           # degrees the bolt stays locked after the shot
    cam_lever: float = 0.02             # m of gas piston (recoil: barrel) travel per radian of the rotor
    recoil_stroke: float = 0.02         # m the barrels recoil in the receiver (recoil drive)
    starter_energy: float = 0.0         # J, gas and recoil drives: the starter cartridge's work on the rotor
    rotor_damping: float = 0.0          # N m s/rad, drag on the rotor growing with its speed (air, oil)
    valve_time: float = 0.05            # s, hydraulic drive: its valve opening
    # Sliding wedge: the opening cam turns the crank over the last cam_travel of the run-out.
    cam_travel: float = 0.12            # m of counter-recoil before battery
    extractor_ratio: float = 2.5        # case speed out of the breech over the block's speed when it strikes the extractors
    # Stock and balance, for muzzle rise.
    bore_height: float = 0.03           # m, bore axis above where the recoil is taken (the shoulder, or a mount's trunnions)
    cg_distance: float = 0.40           # m, along the bore from the butt (or the trunnions) to the centre of mass
    radius_of_gyration: float = 0.25    # m, for pitching about the centre of mass


@dataclass
class Feed:
    """The magazine or belt the rounds come from (gun_sim/feed.py).

    "single_stack", "double_stack" and "quad_stack" are box magazines (one
    column, two staggered, two double stacks side by side under a funnel);
    "drum" winds them in a spiral on a sprung rotor under a short tower; "belt"
    links them in a belt drawn across a feed tray by a cam on the bolt group;
    "dual_belt" has a belt coming in from each side, `capacity` each, and feeds
    from the `select`ed one; "hand" is a loader putting each round into the
    breech, from a ready rack of `capacity` rounds; "cylinder" is a revolver's,
    `capacity` chambers, reloaded by swinging it out (all the cases ejected at
    once, a speedloader putting the rounds in) or one at a time through a
    loading `gate`. "linkless": a rotary gun's chute (or conveyor) of
    unlinked rounds from its drum or box, `link_mass` each element and
    `belt_hang` of it hanging. A tank gun's autoloaders: "az" the T-72's electromechanical
    carousel, "mz" the T-64's and T-80's hydraulic one, "bustle" a conveyor in
    the turret bustle (the Leclerc's electric, the Type 90's electromechanical
    drive), "oscillating" the drums of an oscillating turret (AMX-13). None =
    filled in for the type.
    """
    type: str = "double_stack"
    capacity: int | None = None             # rounds (None = 10, 30, 60, 75, 100; a cylinder's 6 chambers)
    spring_empty: float | None = None       # N, magazine spring on the follower, empty
    spring_full: float | None = None        # N, on the top round, full
    follower_mass: float | None = None      # kg (a drum's rotor, as felt at the lips)
    friction: float = 0.15                  # top round on the bolt and the feed lips (lubricated brass on steel)
    hold_open: bool = True                  # the follower lifts the bolt catch on an empty magazine
    feed_angle: float | None = None         # degrees the lips tip the round's nose towards the bore; None = aimed at it
    ramp_angle: float = 35.0                # degrees, feed ramp from the bore axis
    # Belt.
    link_mass: float = 0.004                # kg per link
    belt_hang: float = 0.25                 # m of belt hanging from the feed tray
    belt_cam_start: float | None = None     # m of carrier travel where the feed cam starts drawing the belt (None = 20 % of the stroke)
    belt_cam: float | None = None           # m of carrier travel over which it draws one link (None = 35 % of the stroke)
    select: str = "left"                    # dual belt: the belt that feeds ("left" or "right")
    loading: str = "swing_out"              # cylinder: "swing_out" (crane and ejector star) or "gate" (one at a time)
    # Autoloader (gun_sim/autoloader.py). None = the type's.
    drive: str | None = None                # "electric", "electromechanical", "hydraulic" or "spring"
    ammunition: str | None = None           # "two_piece" (projectile and charge rammed separately) or "unitary"
    load_angle: float | None = None         # degrees: the gun is brought to this elevation to load
    gun_elevation: float = 0.0              # degrees the gun is laid at when it fires
    elevation_rate: float = 4.0             # deg/s the gun is driven to its loading angle and back
    index_steps: int = 1                    # positions the carousel (conveyor) turns to bring the chosen round up
    drive_power: float | None = None        # W, each of its drives
    ram_speed: float | None = None          # m/s, the rammer's top speed


@dataclass
class Trigger:
    """The trigger, and how the shooter works it (gun_sim/action.py).

    "single_action": the pull only lets a cocked hammer go (cocked by the
    action, or a single-action revolver's by the shooter's thumb).
    "double_action": the first pull cocks the hammer and lets it go; after that
    the action leaves it cocked (DA/SA). A double-action revolver's every pull
    cocks it and turns the cylinder. "double_action_only": every pull cocks it.
    "striker": the pull finishes cocking a striker the slide has part-cocked,
    and lets it go.

    mode "auto" fires a burst as the closing action trips the auto sear (or,
    without a hammer, as soon as it is back in battery); "semi" fires each shot
    with a pull of its own, `split` seconds after the last, once the action is
    back in battery. A revolver is always fired a pull at a time.
    """
    type: str = "single_action"
    mode: str = "auto"
    pull: float = 25.0          # N, single action (or a striker's) pull
    travel: float = 3.0e-3      # m
    da_pull: float = 50.0       # N, double action
    da_travel: float = 12e-3    # m
    pull_time: float = 0.12     # s the shooter takes over a double-action pull, or to thumb-cock a hammer
    split: float = 0.3          # s between shots fired as fast as the shooter can


@dataclass
class Mount:
    """The recoil system of a gun on a mount (shooter.stance = "mount"; gun_sim/action.py).

    The recoiling parts (action.gun_mass) slide back in the cradle against a
    spring, a hydropneumatic recuperator (gas compressed by a piston) and a
    hydraulic buffer (oil forced through an orifice, which a throttling rod
    closes down over the stroke so the force stays nearly level), with linear
    damping and friction, up to a hard stop at `stroke`. The recuperator and
    spring run the gun out again; the last `counter_buffer` of the run-out is
    cushioned by the counter-recoil buffer. The cradle is held in elevation by
    the elevation gear. Every element is off at 0.
    """
    stroke: float = 0.03                      # m, recoil travel to the hard stop
    spring_rate: float = 0.0                  # N/m, mechanical recoil spring (a soft mount's)
    spring_preload: float = 0.0               # N
    damping: float = 0.0                      # N s/m, linear damper
    friction: float = 0.0                     # N, slides and seals
    recuperator_pressure: float = 0.0         # Pa, its gas in battery
    recuperator_volume: float = 0.0           # m^3, its gas in battery
    recuperator_area: float = 0.0             # m^2, its piston
    buffer_area: float = 0.0                  # m^2, the buffer's piston (0 = no buffer)
    buffer_orifice: float = 0.0               # m^2 open at the start of recoil
    buffer_orifice_end: float | None = None   # m^2 open at full stroke (the throttling rod); None = the same
    counter_orifice: float | None = None      # m^2 the oil returns through in the run-out; None = buffer_orifice
    counter_buffer: float = 0.0               # m: over this last part of the run-out the return orifice closes to a tenth
    oil_density: float = 870.0                # kg/m^3
    stop_restitution: float = 0.2             # bounce off the hard stop
    elevation_stiffness: float = 2e7          # N m/rad, the elevation gear holding the cradle
    elevation_damping: float = 2e5            # N m s/rad


@dataclass
class Shooter:
    """What holds the gun. "shoulder" and "hands" are a spring and damper to the rest of the body, with
    some of it moving with the gun (for a handgun, the hands and forearms; bore_height is then the bore
    over the web of the hand, cg_distance from there forwards to the centre of mass); "free" is free
    recoil: nothing holds it at all; "mount" is a mount's recoil system ([mount])."""
    stance: str = "shoulder"
    body_mass: float = 5.0              # kg of shooter that moves with the gun (shoulder and arms)
    shoulder_stiffness: float = 15e3    # N/m
    shoulder_damping: float = 400.0     # N s/m
    hold_stiffness: float = 90.0        # N m/rad, how hard the hold resists muzzle rise
    hold_damping: float = 9.0           # N m s/rad


STYLES = ("rifle", "ar15", "ak", "autocannon", "tank", "1911", "beretta", "polymer", "revolver", "single_action",
          "rotary", "m134", "m61", "gau8", "gsh623", "slostin", "bk27")
ROTARY_STYLES = ("rotary", "m134", "m61", "gau8", "gsh623", "slostin", "bk27")
HANDGUN_STYLES = ("1911", "beretta", "polymer", "revolver", "single_action")


@dataclass
class Appearance:
    """How the 3D view dresses the action (the solvers ignore it): "rifle" is a
    sporting stock, "ar15" an AR-15 / M4 (upper and lower receiver, pistol grip,
    carry handle or rail, buffer tube and collapsible stock), "ak" a Kalashnikov
    (stamped receiver and dust cover, gas tube over the barrel, curved magazine),
    "autocannon" a chain gun's box receiver and drive on a recoil-adapter mount,
    "tank" a tank gun's breech ring, cradle, recoil cylinders, thermal sleeve and
    bore evacuator. Handguns: "1911" a steel slide and frame with a grip safety,
    spur hammer and wooden grips; "beretta" an open-top slide over the barrel,
    a locking block and an aluminium frame; "polymer" a squared-off slide on a
    polymer frame, striker-fired; "revolver" a double-action revolver's frame,
    swing-out cylinder on its crane, full-lug barrel and ventilated rib;
    "single_action" a single-action army's frame, loading gate, ejector rod and
    one-piece grip. Rotary guns (action.type "rotary"): "rotary" a plain barrel
    cluster or drum in a receiver, and the models of the presets, "m134" (the
    Minigun), "m61" (the Vulcan), "gau8" (the Avenger), "gsh623", "slostin" and
    "bk27"."""
    style: str = "rifle"


@dataclass
class Gun:
    name: str
    barrel: Barrel
    projectile: Projectile
    propellant: Propellant
    case: Case = field(default_factory=Case)
    ignition: Ignition = field(default_factory=Ignition)
    solver: SolverSettings = field(default_factory=SolverSettings)
    action: Action = field(default_factory=Action)
    shooter: Shooter = field(default_factory=Shooter)
    muzzle_device: MuzzleDevice = field(default_factory=MuzzleDevice)
    feed: Feed = field(default_factory=Feed)
    appearance: Appearance = field(default_factory=Appearance)
    mount: Mount = field(default_factory=Mount)
    trigger: Trigger = field(default_factory=Trigger)

    def __post_init__(self):
        scale = self.barrel.bore_diameter / _REF_BORE
        for section, ref in _REF_GEOMETRY.items():
            part = getattr(self, section)
            for key, value in ref.items():
                if getattr(part, key) is None:
                    setattr(part, key, value * scale)
        p, bore = self.projectile, self.barrel.bore_diameter
        if p.type == "apfsds":
            if p.penetrator_mass is None:
                p.penetrator_mass = 0.6 * p.mass
            if p.penetrator_diameter is None:
                p.penetrator_diameter = 0.2 * bore
            d = p.penetrator_diameter
            if p.fin_span is None:
                p.fin_span = min(3.5 * d, 0.95 * bore)
            if p.fin_length is None:
                p.fin_length = 6 * d
            if p.sabot_length is None:
                p.sabot_length = 1.2 * bore
            if p.sabot_offset is None:
                p.sabot_offset = 1.5 * p.fin_length
        elif p.type == "apds":
            if p.penetrator_mass is None:
                p.penetrator_mass = 0.6 * p.mass
            if p.penetrator_diameter is None:
                p.penetrator_diameter = 0.45 * bore
            if p.sabot_length is None:
                p.sabot_length = 0.85 * p.length
            if p.sabot_offset is None:
                p.sabot_offset = 0.0
        elif p.type == "finned":
            if p.fin_span is None:
                p.fin_span = 0.95 * bore
            if p.fin_length is None:
                p.fin_length = 0.6 * bore
        c = self.case
        if c.stub_length is None:
            c.stub_length = c.head_thickness + 0.2 * c.base_diameter

    @property
    def seat(self) -> float:
        """Where the gas pushes the seated projectile, m from the case head: its base, a sabot's rear face, or a
        finned round's body (its boom and fins reach back into the propellant)."""
        p = self.projectile
        return self.case.overall_length - p.length + self.seat_offset

    @property
    def seat_offset(self) -> float:
        p = self.projectile
        if p.type in SUB_CALIBRE:
            return p.sabot_offset
        return p.boom_length if p.type == "finned" else 0.0

    @property
    def flight_mass(self) -> float:
        """What flies on from the muzzle (kg): the projectile, or a sabot round's rod once the sabot has gone."""
        p = self.projectile
        return p.penetrator_mass if p.type in SUB_CALIBRE else p.mass

    @property
    def flight_diameter(self) -> float:
        p = self.projectile
        return p.penetrator_diameter if p.type in SUB_CALIBRE else self.barrel.bore_diameter

    @property
    def chamber_length(self) -> float:
        """Length of a bore-diameter cylinder with the same volume as the chamber."""
        return self.barrel.chamber_volume / self.barrel.bore_area

    @property
    def powder_space(self) -> float:
        """Volume inside the case from the top of the web to the seated projectile base, m^3."""
        from .chamber import ChamberProfile
        return ChamberProfile.from_case(self).volume

    @property
    def effective_chamber_volume(self) -> float:
        """Chamber volume the solvers use: chamber_volume, or the case's powder space."""
        if self.barrel.chamber_shape == "case":
            return self.powder_space
        return self.barrel.chamber_volume

    def validate(self) -> None:
        self.projectile.validate_shape()
        p = self.propellant
        # Unclipped, so a form that overshoots 1 is reported rather than clipped away.
        if not math.isclose(float(p._form(p.z_burnout)), 1.0, rel_tol=1e-6):
            raise ValueError("form function must reach psi = 1 at z_burnout, i.e. "
                             "chi * (1 + lambda + mu) = 1 for a single-phase grain")
        if self.barrel.freebore < 0 or self.barrel.groove_depth < 0 or self.projectile.engraving_pressure < 0:
            raise ValueError("freebore, groove depth and engraving pressure cannot be negative")
        if not 0.1 <= self.barrel.leade_angle <= 45:
            raise ValueError("barrel.leade_angle must be between 0.1 and 45 degrees")
        if self.barrel.chamber_shape not in ("cylinder", "case"):
            raise ValueError(f"barrel.chamber_shape must be 'cylinder' or 'case', not {self.barrel.chamber_shape!r}")
        ig = self.ignition
        if ig.pressure < 0 or not 1e-6 <= ig.duration <= 5e-3:
            raise ValueError("ignition.pressure cannot be negative and ignition.duration must be between 1 µs and 5 ms")
        if not 320 <= ig.grain_ignition_temperature <= 1500:
            raise ValueError("ignition.grain_ignition_temperature must be between 320 and 1500 K")
        if not 0.005 <= ig.strike_energy <= 2:
            raise ValueError("ignition.strike_energy must be between 0.005 and 2 J")
        self._validate_action()
        self._validate_trigger()
        self._validate_device()
        self._validate_feed()
        self._validate_mount()
        self._validate_evacuator()
        self._validate_cylinder()
        if self.appearance.style not in STYLES:
            raise ValueError(f"appearance.style must be one of {", ".join(STYLES)}, not {self.appearance.style!r}")
        c = self.case
        if c.material not in CASE_MATERIALS:
            raise ValueError(f"case.material must be one of {', '.join(CASE_MATERIALS)}, not {c.material!r}")
        if c.combustible and not c.head_thickness <= c.stub_length < c.length:
            raise ValueError("case.stub_length must be at least the head thickness and shorter than the case")
        solid_volume = p.charge_mass / p.density
        chamber = self.effective_chamber_volume
        if solid_volume >= chamber:
            raise ValueError(
                f"charge ({solid_volume * 1e6:.2f} cm^3 of solid) does not fit in the "
                f"chamber ({chamber * 1e6:.2f} cm^3)"
            )

    def _validate_action(self) -> None:
        a, s = self.action, self.shooter
        if a.type not in ACTION_TYPES:
            raise ValueError(f"action.type must be one of {', '.join(ACTION_TYPES)}, not {a.type!r}")
        if s.stance not in STANCES:
            raise ValueError(f"shooter.stance must be one of {', '.join(STANCES)}, not {s.stance!r}")
        moving = a.bolt_mass + ((a.barrel_mass or 0.0) if a.type == "short_recoil" else 0.0)
        if a.gun_mass <= 0 or a.bolt_mass <= 0 or moving >= a.gun_mass:
            raise ValueError("action: the gun must be heavier than the parts that cycle inside it")
        for name in ("barrel_mass", "bolt_travel", "unlock_travel", "gas_port_position", "bolt_head_mass",
                     "gas_tube_length"):
            value = getattr(a, name)
            if value is not None and value <= 0:
                raise ValueError(f"action.{name} must be positive (or left out)")
        if a.gas_port_position is not None and a.gas_port_position >= self.barrel.travel:
            raise ValueError("action.gas_port_position must be inside the barrel (less than barrel.travel)")
        for name in ("rear_restitution", "battery_restitution"):
            if not 0 <= getattr(a, name) <= 1:
                raise ValueError(f"action.{name} must be between 0 and 1")
        for name in ("spring_rate", "spring_preload", "feed_force", "gas_port_diameter", "piston_diameter",
                     "gas_volume", "gas_stroke", "bore_height", "cg_distance", "radius_of_gyration"):
            if getattr(a, name) < 0:
                raise ValueError(f"action.{name} cannot be negative")
        if a.type in ("gas", "direct_impingement", "gas_delayed") and (a.gas_volume <= 0 or a.piston_diameter <= 0
                                                 or a.gas_port_diameter <= 0):
            raise ValueError("a gas action needs a gas port, a piston and a gas cylinder volume")
        if a.type == "direct_impingement" and a.gas_tube_diameter <= 0:
            raise ValueError("direct impingement needs a gas tube (action.gas_tube_diameter)")
        if a.type == "gas_delayed" and a.gas_volume <= math.pi / 4 * a.piston_diameter**2 * a.gas_stroke:
            raise ValueError("gas-delayed: the piston would bottom out in its cylinder before it vents "
                             "(a bigger gas_volume or a shorter gas_stroke)")
        if a.delay_ratio is not None and not 1 <= a.delay_ratio <= 20:
            raise ValueError("action.delay_ratio must be between 1 and 20")
        if a.bolt_head_mass is not None and a.bolt_head_mass >= a.bolt_mass:
            raise ValueError("action.bolt_head_mass must be less than bolt_mass (the head and carrier together)")
        if a.friction < 0 or a.hammer_friction < 0 or a.rate_reducer_inertia < 0 or a.hammer_spring_rate < 0:
            raise ValueError("action.friction, hammer_friction, hammer_spring_rate and rate_reducer_inertia "
                             "cannot be negative")
        if a.hammer_inertia <= 0 or a.hammer_spring_torque <= 0 or a.hammer_cock_travel <= 0 or a.hammer_trip_travel < 0:
            raise ValueError("action.hammer_inertia, hammer_spring_torque and hammer_cock_travel must be positive, "
                             "and hammer_trip_travel cannot be negative")
        if not 10 <= a.hammer_angle <= 120:
            raise ValueError("action.hammer_angle must be between 10 and 120 degrees")
        if not 0 <= a.rate_reducer_angle <= a.hammer_angle:
            raise ValueError("action.rate_reducer_angle must be between 0 and hammer_angle")
        if a.type == "chain":
            if not 10 <= a.chain_rate <= 3000 or a.motor_power <= 0 or a.drive_mass < 0:
                raise ValueError("chain gun: chain_rate must be 10 to 3000 rounds/min, motor_power positive "
                                 "and drive_mass not negative")
            for name in ("chain_width", "sprocket_radius"):
                value = getattr(a, name)
                if value is not None and value <= 0:
                    raise ValueError(f"action.{name} must be positive (or left out)")
            if not 100 <= a.motor_rpm <= 60000 or not 6 <= a.pinion_teeth <= 100 or not 2e-3 <= a.drive_chain_pitch <= 0.1:
                raise ValueError("chain gun: motor_rpm must be 100 to 60000, pinion_teeth 6 to 100 and "
                                 "drive_chain_pitch 2 to 100 mm")
            if a.sprocket_radius is not None and a.chain_width is not None and 2 * a.sprocket_radius > a.chain_width:
                raise ValueError("action.sprocket_radius must be at most half the chain_width")
        if a.type == "rotary":
            self._validate_rotary()
        if a.type == "sliding_wedge":
            if a.cam_travel <= 0 or a.extractor_ratio <= 0:
                raise ValueError("sliding wedge: cam_travel and extractor_ratio must be positive")
            if s.stance != "mount":
                raise ValueError("a sliding-wedge breech is opened by the gun running out on its recoil system: "
                                 "set shooter.stance = \"mount\"")
            if a.cam_travel >= self.mount.stroke:
                raise ValueError("action.cam_travel must be shorter than the recoil stroke (mount.stroke)")
        if a.locking not in LOCKINGS:
            raise ValueError(f"action.locking must be one of {', '.join(LOCKINGS)}, not {a.locking!r}")
        if (a.striker_mass <= 0 or a.striker_travel <= 0 or a.striker_spring_preload < 0
                or a.striker_spring_rate < 0 or not 0 <= a.striker_precock <= 1):
            raise ValueError("action: striker_mass and striker_travel must be positive, its spring not negative, "
                             "and striker_precock between 0 and 1")
        if a.cylinder_mass <= 0 or (a.cylinder_radius is not None and a.cylinder_radius <= 0):
            raise ValueError("action.cylinder_mass must be positive, and cylinder_radius positive (or left out)")
        for name in ("body_mass", "shoulder_stiffness", "shoulder_damping", "hold_stiffness", "hold_damping"):
            if getattr(s, name) < 0:
                raise ValueError(f"shooter.{name} cannot be negative")

    def _validate_rotary(self) -> None:
        from .rotary import DRIVES, FEEDS, LAYOUTS
        a = self.action
        if a.rotary_layout not in LAYOUTS:
            raise ValueError(f"action.rotary_layout must be one of {', '.join(LAYOUTS)}, not {a.rotary_layout!r}")
        if a.rotary_drive not in DRIVES:
            raise ValueError(f"action.rotary_drive must be one of {', '.join(DRIVES)}, not {a.rotary_drive!r}")
        if a.barrels != int(a.barrels) or not 2 <= a.barrels <= 12:
            raise ValueError("action.barrels must be a whole number from 2 to 12")
        if a.chambers != int(a.chambers) or not 3 <= a.chambers <= 8:
            raise ValueError("action.chambers must be a whole number from 3 to 8")
        a.barrels, a.chambers = int(a.barrels), int(a.chambers)
        if not 100 <= a.rotary_rate <= 15000:
            raise ValueError("action.rotary_rate must be between 100 and 15000 rounds/min")
        for name in ("rotor_inertia", "cluster_radius"):
            value = getattr(a, name)
            if value is not None and value <= 0:
                raise ValueError(f"action.{name} must be positive (or left out)")
        if not 10 <= a.dwell_angle <= 120:
            raise ValueError("action.dwell_angle must be between 10 and 120 degrees")
        if not 1e-3 <= a.cam_lever <= 0.5 or not 1e-3 <= a.recoil_stroke <= 0.3:
            raise ValueError("action.cam_lever must be between 1 and 500 mm/rad, recoil_stroke between 1 and 300 mm")
        if a.starter_energy < 0 or a.rotor_damping < 0 or a.valve_time < 0 or a.drive_mass < 0:
            raise ValueError("action.starter_energy, rotor_damping, valve_time and drive_mass cannot be negative")
        if a.rotary_drive in ("electric", "hydraulic") and a.motor_power <= 0:
            raise ValueError(f"a{'n' if a.rotary_drive == 'electric' else ''} {a.rotary_drive} drive needs its "
                             "motor's power (action.motor_power)")
        if a.rotary_drive in ("gas", "recoil") and a.starter_energy <= 0:
            raise ValueError(f"a {a.rotary_drive}-driven rotary gun needs a starter to turn it up to its first shot "
                             "(action.starter_energy)")
        if a.rotary_drive == "gas" and (a.gas_volume <= 0 or a.piston_diameter <= 0 or a.gas_port_diameter <= 0
                                        or a.gas_stroke <= 0):
            raise ValueError("a gas-driven rotary gun needs a gas port, a piston, a gas cylinder volume and a "
                             "gas stroke")
        if self.feed.type not in FEEDS:
            raise ValueError(f"a rotary gun's feeder takes its rounds from a belt or a linkless chute: feed.type "
                             f"{', '.join(FEEDS)}")
        if self.trigger.mode != "auto":
            raise ValueError("a rotary gun fires bursts: trigger.mode = \"auto\"")

    def _validate_trigger(self) -> None:
        t, kind = self.trigger, self.action.type
        if t.type not in TRIGGER_TYPES:
            raise ValueError(f"trigger.type must be one of {', '.join(TRIGGER_TYPES)}, not {t.type!r}")
        if t.mode not in FIRE_MODES:
            raise ValueError(f"trigger.mode must be one of {', '.join(FIRE_MODES)}, not {t.mode!r}")
        if t.pull <= 0 or t.travel <= 0 or t.da_pull <= 0 or t.da_travel <= 0:
            raise ValueError("trigger: the pulls and their travels must be positive")
        if not 0.01 <= t.pull_time <= 2 or not 0.02 <= t.split <= 10:
            raise ValueError("trigger.pull_time must be between 0.01 and 2 s, and split between 0.02 and 10 s")
        if kind == "revolver":
            if t.type == "striker":
                raise ValueError("a revolver is fired by its hammer: trigger.type single_action, double_action "
                                 "or double_action_only")
            if t.split <= t.pull_time:
                raise ValueError("trigger.split must be longer than pull_time: the hammer is cocked between shots")
        if t.type in ("double_action", "double_action_only") and kind not in ("revolver", "bolt", "chain", "sliding_wedge",
                                                                             "rotary"):
            if not self.action.hammer:
                raise ValueError("a double-action trigger cocks a hammer: set action.hammer = true")
            if t.type == "double_action_only" and t.split <= t.pull_time:
                raise ValueError("trigger.split must be longer than pull_time: each pull cocks the hammer")
        if t.type == "striker" and (kind in ("bolt", "chain", "sliding_wedge", "rotary") or self.action.hammer):
            raise ValueError("a striker is cocked by a self-loading action instead of a hammer: "
                             "set action.hammer = false and a self-loading action.type")

    def _validate_cylinder(self) -> None:
        b, kind, f = self.barrel, self.action.type, self.feed
        if (kind == "revolver") != (f.type == "cylinder"):
            raise ValueError("a revolver's rounds are in its cylinder: action.type \"revolver\" goes with "
                             "feed.type \"cylinder\", and only with it")
        if f.loading not in CYLINDER_LOADING:
            raise ValueError(f"feed.loading must be one of {', '.join(CYLINDER_LOADING)}, not {f.loading!r}")
        if b.cylinder_gap < 0 or b.cylinder_gap > 2e-3:
            raise ValueError("barrel.cylinder_gap must be between 0 and 2 mm")
        if b.cylinder_gap and kind != "revolver":
            raise ValueError("barrel.cylinder_gap is a revolver's: set action.type = \"revolver\" (or the gap to 0)")
        if b.cylinder_length is not None:
            if b.cylinder_length < self.case.overall_length:
                raise ValueError("barrel.cylinder_length must be at least the case's overall length: "
                                 "the bullet may not stand out of the cylinder")
            if b.cylinder_length - self.seat >= b.travel:
                raise ValueError("barrel.cylinder_length leaves no barrel ahead of the cylinder")
        if kind == "revolver" and f.capacity is not None and not 2 <= f.capacity <= 12:
            raise ValueError("a revolver's cylinder has 2 to 12 chambers (feed.capacity)")

    def _validate_feed(self) -> None:
        f = self.feed
        if f.type not in FEED_TYPES:
            raise ValueError(f"feed.type must be one of {', '.join(FEED_TYPES)}, not {f.type!r}")
        if f.capacity is not None:
            most = 2000 if f.type in ("belt", "dual_belt", "linkless") else 250
            if f.capacity != int(f.capacity) or not 1 <= f.capacity <= most:
                raise ValueError(f"feed.capacity must be a whole number of rounds from 1 to {most}")
            f.capacity = int(f.capacity)
        for name in ("spring_empty", "spring_full", "follower_mass"):
            value = getattr(f, name)
            if value is not None and value < 0:
                raise ValueError(f"feed.{name} cannot be negative")
        if f.spring_empty is not None and f.spring_full is not None and f.spring_full < f.spring_empty:
            raise ValueError("feed.spring_full must be at least spring_empty (the spring is most compressed when full)")
        if not 0 <= f.friction <= 1:
            raise ValueError("feed.friction must be between 0 and 1")
        if f.feed_angle is not None and not -45 <= f.feed_angle <= 45:
            raise ValueError("feed.feed_angle must be between -45 and 45 degrees")
        if not 5 <= f.ramp_angle <= 80:
            raise ValueError("feed.ramp_angle must be between 5 and 80 degrees")
        if f.link_mass < 0 or f.belt_hang < 0:
            raise ValueError("feed.link_mass and belt_hang cannot be negative")
        if f.select not in ("left", "right"):
            raise ValueError("feed.select must be \"left\" or \"right\"")
        if f.type == "linkless" and self.action.type != "rotary":
            raise ValueError("a linkless chute feeds a rotary gun: action.type \"rotary\"")
        if self.action.type == "chain" and f.type not in ("belt", "dual_belt"):
            raise ValueError("a chain gun's feeder takes its rounds from a belt: feed.type \"belt\" or \"dual_belt\"")
        if f.type == "hand" and self.action.type not in ("bolt", "sliding_wedge"):
            raise ValueError("feed.type \"hand\" (a loader) needs a hand-worked breech: action.type \"bolt\" or \"sliding_wedge\"")
        if f.type in AUTOLOADERS:
            if self.action.type != "sliding_wedge":
                raise ValueError("an autoloader rams into a cannon's breech: action.type \"sliding_wedge\"")
            if f.drive is not None and f.drive not in DRIVES:
                raise ValueError(f"feed.drive must be one of {', '.join(DRIVES)}, not {f.drive!r}")
            if f.ammunition is not None and f.ammunition not in AMMUNITION:
                raise ValueError(f"feed.ammunition must be one of {', '.join(AMMUNITION)}, not {f.ammunition!r}")
            if f.load_angle is not None and not -10 <= f.load_angle <= 20:
                raise ValueError("feed.load_angle must be between -10 and 20 degrees")
            if not -10 <= f.gun_elevation <= 30:
                raise ValueError("feed.gun_elevation must be between -10 and 30 degrees")
            if not 0.2 <= f.elevation_rate <= 60:
                raise ValueError("feed.elevation_rate must be between 0.2 and 60 deg/s")
            if f.index_steps != int(f.index_steps) or not 0 <= f.index_steps <= 250:
                raise ValueError("feed.index_steps must be a whole number of positions, 0 to 250")
            f.index_steps = int(f.index_steps)
            if f.drive_power is not None and not 10 <= f.drive_power <= 200e3:
                raise ValueError("feed.drive_power must be between 10 W and 200 kW")
            if f.ram_speed is not None and not 0.2 <= f.ram_speed <= 10:
                raise ValueError("feed.ram_speed must be between 0.2 and 10 m/s")
        for name in ("belt_cam_start", "belt_cam"):
            value = getattr(f, name)
            if value is not None and value <= 0:
                raise ValueError(f"feed.{name} must be positive (or left out)")

    def _validate_mount(self) -> None:
        m = self.mount
        for name in ("spring_rate", "spring_preload", "damping", "friction", "recuperator_pressure", "recuperator_volume",
                     "recuperator_area", "buffer_area", "buffer_orifice", "counter_buffer", "elevation_stiffness",
                     "elevation_damping"):
            if getattr(m, name) < 0:
                raise ValueError(f"mount.{name} cannot be negative")
        if m.stroke <= 0 or m.oil_density <= 0 or not 0 <= m.stop_restitution <= 1:
            raise ValueError("mount.stroke and oil_density must be positive, stop_restitution between 0 and 1")
        if m.recuperator_pressure and m.recuperator_area * m.stroke >= m.recuperator_volume:
            raise ValueError("mount: the recuperator's piston would sweep all its gas before full recoil "
                             "(more recuperator_volume, or less recuperator_area)")
        if m.buffer_area:
            if m.buffer_orifice <= 0:
                raise ValueError("mount: a buffer needs an orifice (buffer_orifice)")
            for name in ("buffer_orifice_end", "counter_orifice"):
                value = getattr(m, name)
                if value is not None and value <= 0:
                    raise ValueError(f"mount.{name} must be positive (or left out)")

    def _validate_evacuator(self) -> None:
        b = self.barrel
        if not b.evacuator_position:
            return
        if not 0 < b.evacuator_position < b.travel:
            raise ValueError("barrel.evacuator_position must be inside the barrel (less than barrel.travel)")
        if b.evacuator_volume <= 0 or b.evacuator_nozzles < 1 or b.evacuator_nozzle_diameter <= 0:
            raise ValueError("a bore evacuator needs a volume, at least one nozzle and a nozzle diameter")
        if not 0 <= b.evacuator_angle < 90:
            raise ValueError("barrel.evacuator_angle must be between 0 and 90 degrees")
        if self.action.type in ("gas", "direct_impingement", "gas_delayed"):
            raise ValueError("a bore evacuator with a gas-operated action is not supported (they share the "
                             "bore gas the solvers record at one point)")

    def _validate_device(self) -> None:
        d, cfg = self.muzzle_device, self.solver
        if d.type not in DEVICE_TYPES:
            raise ValueError(f"muzzle_device.type must be one of {', '.join(DEVICE_TYPES)}, not {d.type!r}")
        if not 2 <= cfg.device_resolution <= 12:
            raise ValueError("solver.device_resolution must be between 2 and 12 cells across the bore")
        if not 2e-4 <= cfg.device_time <= 0.02:
            raise ValueError("solver.device_time must be between 0.2 and 20 ms")
        if not 2 <= cfg.plume_resolution <= 8:
            raise ValueError("solver.plume_resolution must be between 2 and 8 cells across the bore")
        if not 2e-4 <= cfg.plume_time <= 0.01:
            raise ValueError("solver.plume_time must be between 0.2 and 10 ms")
        if d.type == "none":
            return
        for name in ("length", "outer_diameter", "blast_chamber", "mass"):
            value = getattr(d, name)
            if value is not None and value <= 0:
                raise ValueError(f"muzzle_device.{name} must be positive (or left out)")
        if d.baffles is not None and not 1 <= d.baffles <= 20:
            raise ValueError("muzzle_device.baffles must be between 1 and 20")
        if d.bore_clearance < 0 or d.wall <= 0:
            raise ValueError("muzzle_device.bore_clearance cannot be negative and wall must be positive")
        if not 0 <= d.baffle_angle <= 70:
            raise ValueError("muzzle_device.baffle_angle must be between 0 and 70 degrees")
        if not 0.05 <= d.vent_fraction <= 0.95:
            raise ValueError("muzzle_device.vent_fraction must be between 0.05 and 0.95")
        if not 0 <= d.flare_angle <= 30:
            raise ValueError("muzzle_device.flare_angle must be between 0 and 30 degrees")
        bore = self.barrel.bore_diameter
        od = d.outer_diameter
        if od is not None and od < bore + d.bore_clearance + 4 * d.wall:
            raise ValueError("muzzle_device.outer_diameter is too small for the bore, clearance and walls")

    @classmethod
    def from_dict(cls, data: dict) -> Gun:
        sections = {
            "barrel": Barrel,
            "projectile": Projectile,
            "propellant": Propellant,
            "case": Case,
            "ignition": Ignition,
            "solver": SolverSettings,
            "action": Action,
            "shooter": Shooter,
            "muzzle_device": MuzzleDevice,
            "feed": Feed,
            "appearance": Appearance,
            "mount": Mount,
            "trigger": Trigger,
        }
        kwargs = {"name": data.get("name", "unnamed")}
        for key, section_cls in sections.items():
            if key in data:
                known = {f.name for f in fields(section_cls)}
                unknown = set(data[key]) - known
                if unknown:
                    raise ValueError(f"unknown keys in [{key}]: {', '.join(sorted(unknown))}")
                kwargs[key] = section_cls(**data[key])
        gun = cls(**kwargs)
        gun.validate()
        return gun

    @classmethod
    def load(cls, path: str | Path) -> Gun:
        with open(path, "rb") as f:
            return cls.from_dict(tomllib.load(f))
