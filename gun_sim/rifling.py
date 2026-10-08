"""Rifling: engraving resistance, spin-up and gyroscopic stability.

Engraving. A projectile seated in the case neck first moves through the
freebore (`barrel.freebore`, the jump plus any unrifled throat) with only the
ordinary `bore_resistance`. Its bearing surface then meets the leade, the
forcing cone where the lands start, and is squeezed into the rifling. The extra
resistance this adds rises linearly to `projectile.engraving_pressure` over the
length of the cone it takes to cut a groove to full depth,

    L_c = groove_depth / tan(leade_angle),

then dies away exponentially over the bearing length once the lands have been
cut. This is the shape of the measured resistance-vs-travel curves that
interior ballistics codes use as input. engraving_pressure = 0 (the default)
leaves only the shot-start threshold and the bore resistance, as before.

Spin. In a constant-twist barrel the spin rate is tied to the velocity,
omega = 2 pi v / twist. Spinning the projectile up takes torque from the lands,
so the gas drives an effective mass

    m_eff = m + I_x (2 pi / twist)^2,

about 0.3 % more than the mass for a rifle bullet. The barrel feels the reaction
torque I_x (2 pi / twist) dv/dt, and the gun is given the opposite angular
momentum I_x omega at exit.

The axial moment of inertia I_x comes from the projectile's shape (boat tail,
shank, tangent or secant ogive, meplat, hollow point) with its mass spread
uniformly; a jacket over a denser core would lower it by a few per cent.

Stability is Miller's twist rule, Sg = 30 m / (t^2 d^3 l (1 + l^2)) in grains,
inches and calibres, corrected for velocity and air density. Sg below 1 tumbles,
1 to 1.4 is marginal, above about 1.5 is stable. Spin drift downrange follows
Litz's fit to 6-DoF results, drift = 1.25 (Sg + 1.2) t^1.83 inches for a time of
flight t in seconds, to the right for a right-hand twist.

A positive twist is right-handed, negative left-handed, and 0 is a smooth bore.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from .config import Gun
    from .results import ShotResult

GRAIN = 6.479891e-5   # kg
INCH = 0.0254         # m


def engraving_window(gun: Gun) -> tuple[float, float, float]:
    """Travel (m) where engraving starts, where it peaks, and its decay length."""
    bar, proj = gun.barrel, gun.projectile
    start = max(bar.freebore, 0.0)
    angle = math.radians(min(max(bar.leade_angle, 0.1), 45.0))
    cone = max(bar.groove_depth, 0.0) / math.tan(angle)
    bearing = proj.length - proj.ogive_length - proj.boat_tail_length
    decay = max(bearing, 0.5 * bar.bore_diameter)
    return start, start + cone, decay


def resistance(gun: Gun, x: float) -> float:
    """Resistive pressure on the projectile base (Pa) after travel x (m): bore friction plus engraving."""
    proj = gun.projectile
    r = proj.bore_resistance
    peak = proj.engraving_pressure
    if peak <= 0:
        return r
    start, full, decay = engraving_window(gun)
    if x < start:
        return r
    if x < full:
        return r + peak * (x - start) / (full - start)
    return r + peak * math.exp(-(x - full) / decay)


def profile(gun: Gun, points: int = 400) -> tuple[np.ndarray, np.ndarray]:
    """Outside radius r(x) of the projectile, x from the base (m)."""
    p = gun.projectile
    R = gun.barrel.bore_diameter / 2
    L = p.length
    ogive = min(max(p.ogive_length, 0.0), L)
    tail = min(max(p.boat_tail_length, 0.0), L - ogive)
    tail_r = max(R - tail * math.tan(math.radians(p.boat_tail_angle)), 0.2 * R)
    meplat = min(max(p.meplat_diameter / 2, 0.0), R)

    # Ogive arc through (0, R) at its start and (ogive, 0) at the tip.
    chord = math.hypot(ogive, R)
    rho = max(p.ogive_radius_ratio, 1.0) * chord**2 / (2 * R)
    h = math.sqrt(max(rho * rho - chord * chord / 4, 0.0))
    a = ogive / 2 - h * R / chord
    b = R / 2 - h * ogive / chord

    x = np.linspace(0.0, L, points)
    s = x - (L - ogive)
    nose = b + np.sqrt(np.maximum(rho * rho - (s - a) ** 2, 0.0))
    r = np.where(x < tail, tail_r + (R - tail_r) * x / max(tail, 1e-12), R)
    r = np.where(s > 0, np.clip(nose, meplat, R), r)
    return x, r


def moment_of_inertia(gun: Gun) -> float:
    """Axial moment of inertia I_x (kg m^2), mass spread uniformly over the shape."""
    p = gun.projectile
    x, r = profile(gun)
    volume = np.trapezoid(np.pi * r**2, x)
    inertia = np.trapezoid(np.pi * r**4 / 2, x)  # per unit density
    # Hollow-point cavity, from the tip down.
    rc = min(p.hollow_point_diameter / 2, float(r[-1]))
    depth = min(p.hollow_point_depth, p.length)
    if rc > 0 and depth > 0:
        volume -= np.pi * rc**2 * depth
        inertia -= np.pi * rc**4 / 2 * depth
    return p.mass * inertia / volume


def spin_factor(gun: Gun) -> float:
    """2 pi / twist (rad per metre of travel); 0 for a smooth bore."""
    twist = gun.barrel.twist
    return 2 * math.pi / twist if twist else 0.0


def effective_mass(gun: Gun) -> float:
    """Mass the gas accelerates, including spinning the projectile up."""
    return gun.projectile.mass + moment_of_inertia(gun) * spin_factor(gun) ** 2


def stability(gun: Gun, velocity: float, temperature: float = 15.0, pressure: float = 101325.0) -> float:
    """Miller gyroscopic stability factor Sg at this velocity (m/s), air temperature (C) and pressure (Pa)."""
    p, d = gun.projectile, gun.barrel.bore_diameter
    twist = abs(gun.barrel.twist or 0.0)
    if twist == 0 or velocity <= 0:
        return 0.0
    t_cal = twist / d
    l_cal = p.length / d
    sg = 30 * (p.mass / GRAIN) / (t_cal**2 * (d / INCH) ** 3 * l_cal * (1 + l_cal**2))
    sg *= (velocity / 0.3048 / 2800) ** (1 / 3)
    temp_f = temperature * 9 / 5 + 32
    return sg * (temp_f + 460) / (59 + 460) * 29.92 / (pressure / 3386.389)


def spin_drift(sg: float, time: np.ndarray, twist: float) -> np.ndarray:
    """Litz's spin drift (m, + to the right) against time of flight (s)."""
    if not twist or sg <= 0:
        return np.zeros_like(np.asarray(time, dtype=float))
    return math.copysign(1.0, twist) * 1.25 * (sg + 1.2) * np.asarray(time) ** 1.83 * INCH


def spin_report(gun: Gun, result: ShotResult) -> dict:
    """Spin and torque numbers for a shot (standard air for the stability factor)."""
    k = spin_factor(gun)
    inertia = moment_of_inertia(gun)
    v = result.muzzle_velocity
    omega = k * v
    peak_torque = 0.0
    if k and len(result.time) > 2:
        accel = np.gradient(result.velocity, result.time)
        peak_torque = float(inertia * abs(k) * accel.max())
    twist = gun.barrel.twist or 0.0
    return {
        "twist_calibres": abs(twist) / gun.barrel.bore_diameter if twist else 0.0,
        "moment_of_inertia": inertia,
        "spin_rate": omega,                        # rad/s, signed with the twist
        "spin_rpm": abs(omega) * 60 / (2 * math.pi),
        "spin_energy": 0.5 * inertia * omega**2,   # J
        "angular_impulse": -inertia * omega,       # N m s given to the gun
        "peak_torque": peak_torque,                # N m on the barrel
        "stability": stability(gun, v),
    }
