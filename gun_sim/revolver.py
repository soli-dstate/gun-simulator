"""Revolvers: the cylinder, and the gas that escapes through the gap between it and the barrel.

Cylinder. Each round sits in a chamber of its own, `cylinder_radius` from the
cylinder's axis (by default just far enough out for the rims to clear each
other with a web of steel between). The hand, pushed up by the hammer as it is
cocked, turns the ratchet on the cylinder's back a chamber on over the middle of
the hammer's swing (INDEX_START to INDEX_END of it); the cylinder stop then
drops into its notch and locks it with the next chamber in line with the bore.
The cylinder arrives at the stop at the hand's speed, and the stop takes its
spin: half the cylinder's moment of inertia (with its rounds) times the square
of that speed.

Gap. The barrel's rear face stands `cylinder_gap` ahead of the cylinder. While
the bullet is still in its chamber it seals the gas in; once its base has left
the cylinder's front face (at a travel of cylinder_length less where it was
seated), the gas behind it escapes through the gap all round: an annular slot
pi d_bore wide and cylinder_gap tall, flowing as an orifice (choked, almost
always) with GAP_CD. The jet goes out sideways, so it gives the gun no push
along the bore, but the bore loses its mass and enthalpy, and so the bullet some
of its speed; the sound model makes a blast of its own from it. The barrel's
forcing cone, and the jump the bullet makes from its chamber across the gap
into the rifling, are the barrel's freebore and leade.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np

from . import feed

if TYPE_CHECKING:
    from .config import Gun

GAP_CD = 0.6              # discharge coefficient of the gap: a thin annular slot between two flat faces
INDEX_START, INDEX_END = 0.2, 0.85   # share of the hammer's swing over which the hand turns the cylinder
WEB = 1.5e-3              # m of steel between neighbouring chambers' rims
WALL = 1.8e-3             # m of steel outside the chambers


def revolver(gun: Gun) -> bool:
    return gun.action.type == "revolver"


def cylinder_length(gun: Gun) -> float:
    """From the cylinder's rear face (the case head) to its front face (m)."""
    given = gun.barrel.cylinder_length
    return given if given is not None else gun.case.overall_length + 1e-3


def gap_travel(gun: Gun) -> float:
    """Projectile travel from its seat until its base leaves the cylinder and opens the gap (m)."""
    return max(cylinder_length(gun) - gun.seat, 0.0)


def gap_area(gun: Gun) -> float:
    """The gap's flow area (m^2): the bore's circumference times the gap; 0 without one."""
    if not revolver(gun):
        return 0.0
    return math.pi * gun.barrel.bore_diameter * gun.barrel.cylinder_gap


def cylinder_radius(gun: Gun) -> float:
    """From the cylinder's axis to each chamber's (m): given, or room for the rims with a web between."""
    a = gun.action
    if a.cylinder_radius is not None:
        return a.cylinder_radius
    n = feed.chambers(gun)
    return (gun.case.rim_diameter + WEB) / (2 * math.sin(math.pi / n))


def cylinder_outer_radius(gun: Gun) -> float:
    c = gun.case
    return cylinder_radius(gun) + 0.5 * max(c.rim_diameter, c.base_diameter) + WALL


def cylinder_inertia(gun: Gun, loaded: int) -> float:
    """The cylinder's moment of inertia about its axis (kg m^2) with `loaded` rounds (or cases) in it.

    The empty cylinder is taken as a solid drum of its outer radius, less the chambers bored out of it.
    """
    r_out, r = cylinder_outer_radius(gun), cylinder_radius(gun)
    n = feed.chambers(gun)
    hole = 0.5 * gun.case.base_diameter
    # A solid drum's I = m R^2 / 2; the chambers take out n holes' worth at radius r.
    solid = 0.5 * r_out**2
    holes = n * (hole / r_out) ** 2 * (r * r + 0.5 * hole * hole)
    share = 1 - n * (hole / r_out) ** 2
    drum = gun.action.cylinder_mass * (solid - holes) / max(share, 0.2)
    return drum + loaded * feed.round_mass(gun) * r * r


def leak(area: float, p: float, temperature: float, ambient: float, gamma: float, r_gas: float) -> float:
    """Mass flow (kg/s) of the bore's gas out through the gap, as an orifice (choked or not)."""
    if area <= 0 or p <= ambient:
        return 0.0
    ratio = ambient / p
    k = GAP_CD * area * p / math.sqrt(r_gas * temperature)
    if ratio <= (2 / (gamma + 1)) ** (gamma / (gamma - 1)):
        return k * math.sqrt(gamma) * (2 / (gamma + 1)) ** ((gamma + 1) / (2 * (gamma - 1)))
    return k * math.sqrt(2 * gamma / (gamma - 1) * (ratio ** (2 / gamma) - ratio ** ((gamma + 1) / gamma)))


def gap_flow(t: list, mdot: list, edot: list, gun: Gun) -> dict | None:
    """The gap's record, as ShotResult.gap_flow: arrays t (s), mdot (kg/s), edot (W, enthalpy carried),
    and totals mass (kg) and energy (J)."""
    if not t:
        return None
    t, mdot, edot = np.array(t), np.array(mdot), np.array(edot)
    dt = np.diff(t, prepend=t[0])
    return {"t": t, "mdot": mdot, "edot": edot, "mass": float(np.sum(mdot * dt)), "energy": float(np.sum(edot * dt)),
            "position": gap_travel(gun), "area": gap_area(gun)}
