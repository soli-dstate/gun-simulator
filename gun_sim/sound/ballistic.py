"""The projectile's own sound: the supersonic crack and the precursor blast.

Crack: a supersonic projectile drags a conical shock (the Mach cone) with it.
Far from the trajectory it becomes an N-wave, whose amplitude and length
follow Whitham's theory:

    dp = 0.53 p0 (M^2 - 1)^(1/8) d / (b^(3/4) l^(1/4))
    T  = 1.82 M b^(1/4) d / (c0 (M^2 - 1)^(3/8) l^(1/4))

with d the calibre, l the projectile length and b the miss distance. The
listener hears the part of the cone emitted where the arrival time
t_e + |listener - x(t_e)| / c0 is smallest. If that point is the muzzle
itself, the cone never sweeps over the listener (for example at the shooter's
ear) and there is no crack.

Precursor: before the projectile leaves, it drives the air column in the bore
ahead of it like a piston, and a shock runs out of the muzzle first.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .settings import GAMMA_AIR, R_AIR

# Drag coefficient against Mach number, shaped like the G7 reference
# projectile (a long boat-tailed spitzer), approximate.
_CD_MACH = np.array([0.0, 0.7, 0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.2, 1.4, 1.6, 2.0, 2.5, 3.0, 4.0, 5.0])
_CD_VALUE = np.array([0.120, 0.120, 0.124, 0.136, 0.170, 0.380, 0.404, 0.401, 0.387, 0.352,
                      0.325, 0.293, 0.266, 0.245, 0.217, 0.199])


def drag_coefficient(mach):
    return np.interp(mach, _CD_MACH, _CD_VALUE)


@dataclass
class Trajectory:
    t: np.ndarray  # s from muzzle exit
    x: np.ndarray  # m downrange
    v: np.ndarray  # m/s


def fly(v0: float, mass: float, diameter: float, rho_air: float, c0: float, x_max: float) -> Trajectory:
    """Straight-line flight with drag (gravity drop is irrelevant to the sound)."""
    area = math.pi * diameter**2 / 4
    k = 0.5 * rho_air * area / mass
    ts, xs, vs = [0.0], [0.0], [v0]
    t, x, v = 0.0, 0.0, v0
    dx = max(x_max / 4000, 0.01)
    while x < x_max and v > 30:
        # dv/dx = -k Cd v (drag deceleration over distance), midpoint step.
        a1 = -k * drag_coefficient(v / c0) * v
        vm = v + 0.5 * dx * a1
        a2 = -k * drag_coefficient(vm / c0) * vm
        v_new = max(v + dx * a2, 1.0)
        t += dx / (0.5 * (v + v_new))
        x += dx
        v = v_new
        ts.append(t); xs.append(x); vs.append(v)
    return Trajectory(np.array(ts), np.array(xs), np.array(vs))


@dataclass
class Crack:
    time: float          # s after muzzle exit
    overpressure: float  # Pa, peak of the N-wave
    duration: float      # s, front to rear shock
    mach: float          # projectile Mach number where the heard part was emitted
    miss_distance: float # m
    direction: np.ndarray  # unit vector the sound travels along (emission point -> listener)


def crack(traj: Trajectory, listener, c0: float, p0: float, diameter: float, length: float) -> Crack | None:
    """The crack heard at `listener` (x, y, z relative to the muzzle), or None."""
    lx, ly, lz = listener
    b = math.hypot(ly, lz)
    if b < diameter:
        b = diameter  # on the trajectory: the formula is for the far field
    dist = np.sqrt((lx - traj.x) ** 2 + b**2)
    arrival = traj.t + dist / c0
    i = int(np.argmin(arrival))
    if i == 0 or i == len(arrival) - 1:
        return None  # the cone never reaches the listener (or the run ended first)
    mach = traj.v[i] / c0
    if mach <= 1.0:
        return None
    m2 = mach * mach - 1
    dp = 0.53 * p0 * m2 ** 0.125 * diameter / (b ** 0.75 * length ** 0.25)
    dur = 1.82 * mach * b ** 0.25 * diameter / (c0 * m2 ** 0.375 * length ** 0.25)
    direction = np.array([lx - traj.x[i], ly, lz]) / dist[i]
    return Crack(float(arrival[i]), float(dp), float(dur), float(mach), float(b), direction)


def n_wave(t: np.ndarray, t0: float, dp: float, duration: float) -> np.ndarray:
    """An N-wave starting at t0. Each shock rises over a time set by its strength."""
    # Weak-shock thickness in air: roughly inversely proportional to strength.
    rise = min(max(2e-3 / dp, 0.5e-6), 0.1 * duration)
    s = t - t0
    ramp = dp * (1 - 2 * s / duration)
    front = 0.5 * (1 + np.tanh(s / rise))
    back = 0.5 * (1 + np.tanh((duration - s) / rise))
    return ramp * front * back


def precursor_flow(time: np.ndarray, travel: np.ndarray, velocity: np.ndarray, bore_travel: float,
                   bore_area: float, p0: float, t_air: float):
    """Air pushed out of the muzzle ahead of the projectile.

    The projectile drives a shock into the still air of the bore. Behind the
    shock the air moves with the projectile. Once the shock reaches the muzzle,
    that air streams out until the projectile exits. Returns cumulative
    (t, mass, energy) arrays, or None if the shock does not get out first.
    """
    if len(time) < 2:
        return None
    rho1 = p0 / (R_AIR * t_air)
    c1 = math.sqrt(GAMMA_AIR * R_AIR * t_air)
    g = GAMMA_AIR
    # Piston-driven shock speed for piston speed u: W = (g+1)/4 u + sqrt(((g+1)/4 u)^2 + c1^2)
    q = (g + 1) / 4 * velocity
    w = q + np.sqrt(q * q + c1 * c1)
    x_shock = np.concatenate(([0.0], np.cumsum(0.5 * (w[1:] + w[:-1]) * np.diff(time))))
    out = np.nonzero(x_shock >= bore_travel)[0]
    if not out.size:
        return None
    i0 = out[0]
    t = time[i0:]
    u2 = velocity[i0:]
    ms = w[i0:] / c1
    rho2 = rho1 * (g + 1) * ms**2 / ((g - 1) * ms**2 + 2)
    p2 = p0 * (1 + 2 * g / (g + 1) * (ms**2 - 1))
    mdot = rho2 * u2 * bore_area
    edot = mdot * (p2 / ((g - 1) * rho2) + p2 / rho2 + 0.5 * u2**2)
    dt = np.diff(t, prepend=t[0])
    mass = np.cumsum(mdot * dt)
    # Cannot push out more air than was in the bore ahead of the projectile.
    m_column = rho1 * bore_area * bore_travel
    scale = min(1.0, m_column / mass[-1]) if mass[-1] > 0 else 1.0
    return t, mass * scale, np.cumsum(edot * dt) * scale
