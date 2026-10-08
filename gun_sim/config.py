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


CORE_MATERIALS = ("lead", "steel", "copper")


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
    core_material: int | str = 0           # 0/"lead", 1/"steel", 2/"copper"
    exposed_core_length: float = 0.0       # m, soft point: core left bare at the tip

    def __post_init__(self):
        if isinstance(self.core_material, str):
            try:
                self.core_material = CORE_MATERIALS.index(self.core_material.lower())
            except ValueError:
                raise ValueError(
                    f"core_material must be one of {', '.join(CORE_MATERIALS)} (or 0..{len(CORE_MATERIALS) - 1})"
                ) from None

    def validate_shape(self) -> None:
        if not 1.0 <= self.ogive_radius_ratio <= 10.0:
            raise ValueError("ogive_radius_ratio must be between 1 (tangent) and 10")
        if float(self.core_material) not in range(len(CORE_MATERIALS)):
            raise ValueError(f"core_material must be one of {', '.join(CORE_MATERIALS)} (0..{len(CORE_MATERIALS) - 1})")
        for name in ("hollow_point_diameter", "hollow_point_depth", "cannelure_position",
                     "cannelure_width", "cannelure_depth", "jacket_thickness", "exposed_core_length"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} cannot be negative")
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


@dataclass
class Ignition:
    pressure: float = 5e6  # Pa, chamber pressure produced by the igniter/primer
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


ACTION_TYPES = ("bolt", "gas", "direct_impingement", "blowback", "short_recoil", "roller_delayed", "lever_delayed", "gas_delayed")
STANCES = ("shoulder", "free")


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
    # Gas system.
    gas_port_position: float | None = None  # m of projectile travel from its seat to the port; None = 75 % of travel
    gas_port_diameter: float = 1.2e-3   # m
    piston_diameter: float = 10.0e-3    # m
    gas_volume: float = 1.0e-6          # m^3, gas cylinder with the piston forward
    gas_stroke: float = 0.008           # m, piston travel before the cylinder vents
    # Direct impingement: the tube from the gas block back to the carrier key.
    gas_tube_length: float | None = None  # m; None = from the port to the case head, plus a case length
    gas_tube_diameter: float = 1.8e-3     # m, inside
    # Stock and balance, for muzzle rise.
    bore_height: float = 0.03           # m, bore axis above where the recoil is taken (the shoulder)
    cg_distance: float = 0.40           # m, along the bore from the butt to the centre of mass
    radius_of_gyration: float = 0.25    # m, for pitching about the centre of mass


@dataclass
class Shooter:
    """What holds the gun. "free" is free recoil: nothing holds it at all."""
    stance: str = "shoulder"
    body_mass: float = 5.0              # kg of shooter that moves with the gun (shoulder and arms)
    shoulder_stiffness: float = 15e3    # N/m
    shoulder_damping: float = 400.0     # N s/m
    hold_stiffness: float = 90.0        # N m/rad, how hard the hold resists muzzle rise
    hold_damping: float = 9.0           # N m s/rad


STYLES = ("rifle", "ar15", "ak")


@dataclass
class Appearance:
    """How the 3D view dresses the action (the solvers ignore it): "rifle" is a
    sporting stock, "ar15" an AR-15 / M4 (upper and lower receiver, pistol grip,
    carry handle or rail, buffer tube and collapsible stock), "ak" a Kalashnikov
    (stamped receiver and dust cover, gas tube over the barrel, curved magazine)."""
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
    appearance: Appearance = field(default_factory=Appearance)

    def __post_init__(self):
        scale = self.barrel.bore_diameter / _REF_BORE
        for section, ref in _REF_GEOMETRY.items():
            part = getattr(self, section)
            for key, value in ref.items():
                if getattr(part, key) is None:
                    setattr(part, key, value * scale)

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
        self._validate_action()
        self._validate_device()
        if self.appearance.style not in STYLES:
            raise ValueError(f"appearance.style must be one of {", ".join(STYLES)}, not {self.appearance.style!r}")
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
        for name in ("body_mass", "shoulder_stiffness", "shoulder_damping", "hold_stiffness", "hold_damping"):
            if getattr(s, name) < 0:
                raise ValueError(f"shooter.{name} cannot be negative")

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
            "appearance": Appearance,
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
