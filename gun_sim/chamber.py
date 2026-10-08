"""Chamber geometry for the fluid solver: the gas space inside the cartridge case.

With `barrel.chamber_shape = "case"`, the fluid solver works on the real
inside of the case instead of a bore-sized cylinder. The gas column then runs
from the top of the case web (the solid head), up the body, through the
shoulder into the neck, and ends at the projectile base. Its cross-section A(x)
changes along the way. Beyond the projectile's seated position the area is the
bore's.

The inner wall is the same one the 3D view draws (caseProfile in
ui/static/js/viewer3d/cartridge.js), so the solver and the "At a glance"
numbers describe the same case. The code below follows that function closely,
in millimetres, including its clamps for impossible shapes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from .config import Gun

MM = 1e3


def case_cavity(gun: Gun) -> tuple[np.ndarray, np.ndarray]:
    """Inner wall of the case: (x, r) in metres, x from the case head, sorted by x."""
    c = gun.case
    bore = gun.barrel.bore_diameter * MM
    R = bore / 2 + 0.01
    L = c.length * MM
    rim_t = min(max(c.rim_thickness * MM, 0.05), L / 4)
    base_r = max(c.base_diameter * MM / 2, R + 0.2)
    neck_r = R + max(c.neck_wall * MM, 0.05)
    sh_r = max(min(c.shoulder_diameter * MM / 2, base_r), neck_r)
    nw, bw = max(c.neck_wall * MM, 0.05), max(c.body_wall * MM, 0.05)
    head = min(max(c.head_thickness * MM, rim_t), L / 2)
    pr = min(max(c.primer_diameter * MM / 2, 0.3), base_r - 1)
    flash_r = min(0.13 * bore, pr / 2)

    body_start = rim_t
    groove_r = c.groove_diameter * MM / 2
    rim_r = c.rim_diameter * MM / 2
    if groove_r < min(rim_r, base_r) - 0.05:
        body_start = rim_t + max(c.groove_width * MM, 0.1) + (base_r - groove_r)

    angle = math.radians(min(max(c.shoulder_angle, 5), 85))
    shoulder_len = (sh_r - neck_r) / math.tan(angle)
    xs = c.shoulder_position * MM
    if xs + shoulder_len > L - 0.5:
        xs = L - 0.5 - shoulder_len
    xs = max(xs, max(body_start, head) + 1)
    xn = xs + shoulder_len

    inner_sh_r = sh_r - bw
    inner_base_r = max(base_r - 1.8 * bw, flash_r + 1)
    xs_in = xs + bw * 0.6
    xn_in = min(xn + nw * 0.6, L - 0.2)
    fillet = min(1.2, (inner_base_r - flash_r) / 2, (xs_in - head) / 3)
    phi = np.linspace(-math.pi / 2, 0, 9)  # fillet from the web up into the body wall
    fillet_x = head + fillet + fillet * np.sin(phi)
    fillet_r = inner_base_r - fillet + fillet * np.cos(phi)

    x = np.concatenate((fillet_x, [xs_in, xn_in, L]))
    r = np.concatenate((fillet_r, [inner_sh_r, R, R]))
    order = np.argsort(x, kind="stable")
    return x[order] / MM, r[order] / MM


@dataclass
class ChamberProfile:
    """Cross-section of the gas space, piecewise constant on fine bins.

    x is measured from the top of the case web (the breech end of the gas), and
    the profile ends at the projectile's seated base. The integral of the area,
    `volume_at(x)`, is exact for this piecewise-constant area, so the fluid
    solver's cell volumes and face areas agree with each other.
    """
    edges: np.ndarray  # m, bin edges, edges[0] = 0
    area: np.ndarray   # m^2, area in each bin
    bore_area: float   # m^2, beyond the last edge

    def __post_init__(self):
        self._cumulative = np.concatenate(([0.0], np.cumsum(self.area * np.diff(self.edges))))

    @property
    def length(self) -> float:
        return float(self.edges[-1])

    @property
    def volume(self) -> float:
        return float(self._cumulative[-1])

    def area_at(self, x):
        """A(x) at the given positions; the bore's beyond the chamber."""
        i = np.searchsorted(self.edges, x, side="right") - 1
        inside = (i >= 0) & (i < len(self.area))
        return np.where(inside, self.area[np.clip(i, 0, len(self.area) - 1)], self.bore_area)

    def volume_at(self, x):
        """Volume from the breech end to x."""
        inside = np.interp(x, self.edges, self._cumulative)
        return inside + self.bore_area * np.maximum(np.asarray(x) - self.length, 0.0)

    @classmethod
    def cylinder(cls, gun: Gun) -> ChamberProfile:
        """The classic simplification: a bore-sized cylinder of the chamber's volume."""
        a = gun.barrel.bore_area
        return cls(np.array([0.0, gun.barrel.chamber_volume / a]), np.array([a]), a)

    @classmethod
    def from_case(cls, gun: Gun, bins: int = 400) -> ChamberProfile:
        x_cav, r_cav = case_cavity(gun)
        head = x_cav[0]
        seat = gun.case.overall_length - gun.projectile.length  # projectile base, from the case head
        if seat <= head:
            raise ValueError("the projectile base sits below the top of the case web "
                             "(case overall length too short for the projectile)")
        bore_r = gun.barrel.bore_diameter / 2
        edges = np.linspace(0.0, seat - head, bins + 1)
        mid = head + 0.5 * (edges[:-1] + edges[1:])
        # Past the case mouth (a long-seated projectile) the gas is in the bore.
        r = np.where(mid <= x_cav[-1], np.interp(mid, x_cav, r_cav), bore_r)
        return cls(edges, math.pi * r**2, gun.barrel.bore_area)


def chamber_profile(gun: Gun) -> ChamberProfile:
    """The gas space the fluid solver uses, from barrel.chamber_shape."""
    shape = gun.barrel.chamber_shape
    if shape == "cylinder":
        return ChamberProfile.cylinder(gun)
    if shape == "case":
        return ChamberProfile.from_case(gun)
    raise ValueError(f"barrel.chamber_shape must be 'cylinder' or 'case', not {shape!r}")
