"""External ballistics: the flight of the projectile after it leaves the muzzle.

The projectile is a point mass (3 degrees of freedom) under gravity and air
drag. Drag follows the standard "G-function" convention of long-range shooting:
a reference projectile's drag coefficient Cd(Mach) is tabulated (G1: the old
flat-based Ingalls/Krupp shape, G7: a long boat-tailed spitzer), and a real
projectile is described by its ballistic coefficient BC, how much better than
the reference it carries its momentum:

    a_drag = -(pi/8) rho Cd(M) |v_rel| v_rel / BC        BC = m / (i d^2)

with v_rel the velocity relative to the air (so wind enters here), M = |v_rel|/c,
and i the form factor, the projectile's drag relative to the reference at the same
calibre. Sectional density m/d^2 over i is the BC. The reference projectile has
BC = 1 lb/in^2 = 703.07 kg/m^2 at i = 1. **BC is in kg/m^2 throughout**; use
`LB_IN2` to convert from the lb/in^2 printed on ammunition boxes.

If a projectile has no stated BC, `estimate_bc` derives a G7 form factor from its
shape (ogive, meplat, boat tail) with a simple heuristic; see `g7_form_factor`.

Frame: x downrange, y up, z to the right of the line of fire. The line of sight
(LOS) is horizontal, `sight_height` above the bore axis at the muzzle. Heights
in a `Trajectory` are measured from the LOS (negative = below it, the usual
"drop"). The gun is zeroed by raising the barrel until the path crosses the LOS
at the zero range. `trajectory` adds spin drift for a rifled barrel (Litz's
fit, see rifling.py) to the drift. Not modelled: Coriolis, lift/yaw, and the
change of air density with height along the path.

Integration is classical RK4 with a fixed time step (pure Python floats, no
scipy). The Cd curve is piecewise linear, so 1 ms steps are more than enough.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass, field

import numpy as np

from . import rifling
from .config import SUB_CALIBRE, Gun, Projectile

G = 9.80665             # m/s^2
LB_IN2 = 703.0696       # kg/m^2 per lb/in^2 (ballistic coefficient / sectional density unit)
MOA = math.pi / (180 * 60)  # rad per minute of angle

# ---------------------------------------------------------------------------
# Standard drag functions: (Mach, Cd). The published tables (as used by JBM and
# the Sierra/Hornady/Berger solvers), Cd referenced to the cross-section of the
# calibre. Linear interpolation between rows; constant beyond the ends.
# ---------------------------------------------------------------------------
_G1 = [
    (0.00, 0.2629), (0.05, 0.2558), (0.10, 0.2487), (0.15, 0.2413), (0.20, 0.2344),
    (0.25, 0.2278), (0.30, 0.2214), (0.35, 0.2155), (0.40, 0.2104), (0.45, 0.2061),
    (0.50, 0.2032), (0.55, 0.2020), (0.60, 0.2034), (0.70, 0.2165), (0.725, 0.2230),
    (0.75, 0.2313), (0.775, 0.2417), (0.80, 0.2546), (0.825, 0.2706), (0.85, 0.2901),
    (0.875, 0.3136), (0.90, 0.3415), (0.925, 0.3734), (0.95, 0.4084), (0.975, 0.4448),
    (1.00, 0.4805), (1.025, 0.5136), (1.05, 0.5427), (1.075, 0.5677), (1.10, 0.5883),
    (1.125, 0.6053), (1.15, 0.6191), (1.20, 0.6393), (1.25, 0.6518), (1.30, 0.6589),
    (1.35, 0.6621), (1.40, 0.6625), (1.45, 0.6607), (1.50, 0.6573), (1.55, 0.6528),
    (1.60, 0.6474), (1.65, 0.6413), (1.70, 0.6347), (1.75, 0.6280), (1.80, 0.6210),
    (1.85, 0.6141), (1.90, 0.6072), (1.95, 0.6003), (2.00, 0.5934), (2.05, 0.5867),
    (2.10, 0.5804), (2.15, 0.5743), (2.20, 0.5685), (2.25, 0.5630), (2.30, 0.5577),
    (2.35, 0.5527), (2.40, 0.5481), (2.45, 0.5438), (2.50, 0.5397), (2.60, 0.5325),
    (2.70, 0.5264), (2.80, 0.5211), (2.90, 0.5168), (3.00, 0.5133), (3.10, 0.5105),
    (3.20, 0.5084), (3.30, 0.5067), (3.40, 0.5054), (3.50, 0.5040), (3.60, 0.5030),
    (3.70, 0.5022), (3.80, 0.5016), (3.90, 0.5010), (4.00, 0.5006), (4.20, 0.4998),
    (4.40, 0.4995), (4.60, 0.4992), (4.80, 0.4990), (5.00, 0.4988),
]
_G7 = [
    (0.00, 0.1198), (0.05, 0.1197), (0.10, 0.1196), (0.15, 0.1194), (0.20, 0.1193),
    (0.25, 0.1194), (0.30, 0.1194), (0.35, 0.1194), (0.40, 0.1193), (0.45, 0.1193),
    (0.50, 0.1194), (0.55, 0.1193), (0.60, 0.1194), (0.65, 0.1197), (0.70, 0.1202),
    (0.725, 0.1207), (0.75, 0.1215), (0.775, 0.1226), (0.80, 0.1242), (0.825, 0.1266),
    (0.85, 0.1306), (0.875, 0.1368), (0.90, 0.1464), (0.925, 0.1660), (0.95, 0.2054),
    (0.975, 0.2993), (1.00, 0.3803), (1.025, 0.4015), (1.05, 0.4043), (1.075, 0.4034),
    (1.10, 0.4014), (1.125, 0.3987), (1.15, 0.3955), (1.20, 0.3884), (1.25, 0.3810),
    (1.30, 0.3732), (1.35, 0.3657), (1.40, 0.3580), (1.50, 0.3440), (1.55, 0.3376),
    (1.60, 0.3315), (1.65, 0.3260), (1.70, 0.3209), (1.75, 0.3160), (1.80, 0.3117),
    (1.85, 0.3078), (1.90, 0.3042), (1.95, 0.3010), (2.00, 0.2980), (2.05, 0.2951),
    (2.10, 0.2922), (2.15, 0.2892), (2.20, 0.2864), (2.25, 0.2835), (2.30, 0.2807),
    (2.35, 0.2779), (2.40, 0.2752), (2.45, 0.2725), (2.50, 0.2697), (2.55, 0.2670),
    (2.60, 0.2643), (2.65, 0.2615), (2.70, 0.2588), (2.75, 0.2561), (2.80, 0.2533),
    (2.85, 0.2506), (2.90, 0.2479), (2.95, 0.2451), (3.00, 0.2424), (3.10, 0.2368),
    (3.20, 0.2313), (3.30, 0.2258), (3.40, 0.2205), (3.50, 0.2154), (3.60, 0.2106),
    (3.70, 0.2060), (3.80, 0.2017), (3.90, 0.1975), (4.00, 0.1935), (4.20, 0.1861),
    (4.40, 0.1793), (4.60, 0.1730), (4.80, 0.1672), (5.00, 0.1618),
]
# A fin-stabilised long rod (an APFSDS penetrator), Cd referenced to the rod's cross-section, fins
# and windshield included. Not a published standard: an illustrative curve of the shape such rods
# have (a transonic peak from the fins, falling slowly through the hypersonic range), set so a 22 mm,
# 5 kg tungsten rod loses about 60 m/s per km at 1,700 m/s. Used with form factor 1 (BC = m / d^2).
_LR = [
    (0.00, 0.95), (0.60, 0.95), (0.80, 1.00), (0.90, 1.10), (1.00, 1.45), (1.10, 1.60), (1.20, 1.60),
    (1.50, 1.45), (2.00, 1.20), (2.50, 1.05), (3.00, 0.95), (3.50, 0.87), (4.00, 0.81), (4.50, 0.76),
    (5.00, 0.72), (5.50, 0.69), (6.00, 0.66),
]
DRAG_TABLES = {
    "G1": ([m for m, _ in _G1], [c for _, c in _G1]),
    "G7": ([m for m, _ in _G7], [c for _, c in _G7]),
    "LR": ([m for m, _ in _LR], [c for _, c in _LR]),
}
DRAG_MODELS = tuple(DRAG_TABLES)


def drag_coefficient(mach: float, model: str = "G7") -> float:
    """Cd of the standard projectile at this Mach number."""
    ms, cs = DRAG_TABLES[model]
    if mach <= ms[0]:
        return cs[0]
    if mach >= ms[-1]:
        return cs[-1]
    i = bisect_right(ms, mach)
    f = (mach - ms[i - 1]) / (ms[i] - ms[i - 1])
    return cs[i - 1] + f * (cs[i] - cs[i - 1])


# ---------------------------------------------------------------------------
# Atmosphere
# ---------------------------------------------------------------------------
R_DRY = 287.058    # J/(kg K), dry air
R_VAPOUR = 461.495  # J/(kg K), water vapour
GAMMA_AIR = 1.4


@dataclass
class Atmosphere:
    """Air at the firing position. Defaults are the ICAO standard atmosphere at sea
    level: 15 C, 101325 Pa, dry (0 % RH; the tables the BC conventions come from use dry air).
    Density and sound speed are taken as constant along the path."""
    temperature: float = 15.0   # deg C
    pressure: float = 101325.0  # Pa, station pressure (at the firing altitude)
    humidity: float = 0.0       # % relative humidity

    @classmethod
    def standard(cls, altitude: float = 0.0, humidity: float = 0.0) -> Atmosphere:
        """ICAO standard air at `altitude` m: 6.5 K/km lapse rate in the troposphere."""
        t = 288.15 - 0.0065 * altitude
        p = 101325.0 * (t / 288.15) ** 5.25588
        return cls(t - 273.15, p, humidity)

    @property
    def temperature_k(self) -> float:
        return self.temperature + 273.15

    @property
    def vapour_pressure(self) -> float:
        """Partial pressure of water vapour (Magnus formula for saturation), Pa."""
        t = self.temperature
        saturation = 611.21 * math.exp((18.678 - t / 234.5) * (t / (257.14 + t)))
        return min(self.humidity / 100 * saturation, self.pressure)

    @property
    def gas_constant(self) -> float:
        """Specific gas constant of the (moist) air; water vapour makes air lighter."""
        pv = self.vapour_pressure
        x = pv / self.pressure
        return R_DRY * R_VAPOUR / (x * R_DRY + (1 - x) * R_VAPOUR)

    @property
    def density(self) -> float:
        return self.pressure / (self.gas_constant * self.temperature_k)

    @property
    def speed_of_sound(self) -> float:
        return math.sqrt(GAMMA_AIR * self.gas_constant * self.temperature_k)


# ---------------------------------------------------------------------------
# Ballistic coefficient
# ---------------------------------------------------------------------------
def g7_form_factor(length: float, ogive_length: float, meplat_diameter: float,
                   boat_tail_length: float, diameter: float) -> float:
    """Heuristic G7 form factor i7 from the bullet's shape (all lengths in m).

    Starts from 0.90, the best a very low-drag bullet does, and adds:
      * nose: +0.12 per calibre by which the ogive is shorter than 3 calibres
        (a short, blunt nose makes a strong bow shock);
      * meplat: +0.5 per calibre of flat tip diameter;
      * base: +0.10 for a flat base, tapering to nothing for a boat tail of half
        a calibre or longer (a boat tail cuts base drag, mostly in the subsonic range).
    A 7.62 mm match bullet (2-calibre ogive, 0.13 cal meplat, 0.5 cal boat tail) comes
    out near 1.09, and a flat-based spitzer near 1.17. Clamped to 0.8-1.6. `length` is
    unused by the heuristic (long bullets are covered by the sectional density).
    """
    ogive = ogive_length / diameter
    meplat = meplat_diameter / diameter
    boat_tail = boat_tail_length / diameter
    i7 = 0.90 + 0.12 * max(0.0, 3.0 - ogive) + 0.5 * meplat + 0.10 * (1 - min(boat_tail / 0.5, 1.0))
    return min(max(i7, 0.8), 1.6)


G1_PER_G7 = 2.05  # rough BC_G1 / BC_G7 for modern spitzers (e.g. .243 G7 vs .505 G1 -> 2.08)


def estimate_bc(projectile: Projectile, bore_diameter: float, drag_model: str | None = None) -> float:
    """BC in kg/m^2 from mass, bore diameter and shape: sectional density over form factor.
    For G1 the G7 value is scaled by `G1_PER_G7`, which is only a rough rule of thumb."""
    model = drag_model or projectile.drag_model
    i7 = g7_form_factor(projectile.length, projectile.ogive_length, projectile.meplat_diameter,
                        projectile.boat_tail_length, bore_diameter)
    bc7 = projectile.mass / bore_diameter**2 / i7
    return bc7 * G1_PER_G7 if model == "G1" else bc7


def ballistic_coefficient(gun: Gun) -> float:
    """The projectile's stated BC (kg/m^2), or the estimate from its shape.

    An APFSDS flies as its rod: against the long-rod curve its form factor is 1, so the BC is the
    rod's sectional density; against G1 or G7 the estimate is the rod's sectional density over the
    nose's form factor."""
    p = gun.projectile
    if p.ballistic_coefficient:
        return p.ballistic_coefficient
    if p.type in SUB_CALIBRE:
        density = gun.flight_mass / gun.flight_diameter**2
        if p.drag_model.upper() == "LR":
            return density
        i7 = g7_form_factor(p.length, p.ogive_length, p.meplat_diameter, 0.0, gun.flight_diameter)
        return density / i7 * (G1_PER_G7 if p.drag_model.upper() == "G1" else 1.0)
    if p.drag_model.upper() == "LR":
        return p.mass / gun.barrel.bore_diameter**2
    bc = estimate_bc(p, gun.barrel.bore_diameter)
    if p.cap in ("ballistic", "both"):
        bc *= 1.08   # the windshield's sharp nose over a blunt shot
    if p.type == "finned":
        bc /= FIN_DRAG   # the boom and fins add drag a spun shell doesn't have
    return bc


FIN_DRAG = 1.35          # a finned round's drag over a spun shell's of the same nose
TRACER_BASE_DRAG = 0.05  # share of the drag a burning tracer takes off (its gas fills the wake behind the base)


def tracer_burn(gun: Gun) -> tuple[float, float] | None:
    """(burn time s, mass of composition kg) of the projectile's tracer, or None."""
    from . import projectiles

    p = gun.projectile
    if not p.tracer:
        return None
    length = p.tracer_length or 1.5 * gun.flight_diameter
    mass = sum(pc.mass for pc in projectiles.parts(gun).pieces if pc.role == "tracer")
    return length / projectiles.TRACERS[p.tracer].rate, mass


# ---------------------------------------------------------------------------
# Trajectory
# ---------------------------------------------------------------------------
@dataclass
class Trajectory:
    """Sampled flight path. Arrays share one index; y is the height above the line of sight."""
    time: np.ndarray       # s
    x: np.ndarray          # m downrange
    y: np.ndarray          # m above the line of sight (negative = drop)
    z: np.ndarray          # m drift to the right (wind from the left pushes it positive)
    velocity: np.ndarray   # m/s relative to the ground
    mach: np.ndarray       # relative to the air
    energy: np.ndarray     # J
    launch_angle: float = 0.0   # rad, bore elevation above the line of sight
    ballistic_coefficient: float = 0.0  # kg/m^2
    drag_model: str = "G7"
    sight_height: float = 0.0
    stop_reason: str = "max range"
    spin_drift: np.ndarray | None = None  # m, the part of z that is spin drift
    stability: float = 0.0                # Miller Sg at the muzzle (0 = not rifled)
    tracer_burnout: float | None = None   # s after the muzzle the tracer burns out
    fuze_time: float | None = None        # s: a time fuze's burst, or a self-destruct

    def range_at_time(self, t: float | None) -> float | None:
        """Downrange distance (m) at flight time t, or None if the flight ended first."""
        if t is None or t > self.time[-1]:
            return None
        return float(np.interp(t, self.time, self.x))

    def at(self, rng: float) -> dict[str, float]:
        """Interpolated state at downrange distance `rng` (clamped to the flown range)."""
        f = lambda a: float(np.interp(rng, self.x, a))
        drop, drift = f(self.y), f(self.z)
        return {
            "range": rng, "time": f(self.time),
            "drop": drop, "drop_moa": _angle(drop, rng) / MOA, "drop_mil": _angle(drop, rng) * 1e3,
            "windage": drift, "windage_moa": _angle(drift, rng) / MOA, "windage_mil": _angle(drift, rng) * 1e3,
            "velocity": f(self.velocity), "mach": f(self.mach), "energy": f(self.energy),
            "spin_drift": f(self.spin_drift) if self.spin_drift is not None else 0.0,
        }

    def table(self, step: float = 100.0) -> list[dict[str, float]]:
        """Rows every `step` metres out to the end of the flight (drop and windage in m, MOA and mil)."""
        n = int(self.x[-1] / step + 1e-9)
        return [self.at(step * k) for k in range(1, n + 1)]


def nice_step(max_range: float, rows: int = 12) -> float:
    """A round table spacing (1, 2, 2.5 or 5 x 10^n m) giving at most `rows` rows."""
    for k in range(-1, 7):
        for m in (1, 2, 2.5, 5):
            if m * 10.0**k * rows >= max_range:
                return m * 10.0**k
    return max_range


def _angle(offset: float, rng: float) -> float:
    return math.atan2(offset, rng) if rng > 0 else 0.0


def _mass_share(t: float, tracer: tuple[float, float] | None) -> float:
    """What is left of the launch mass at time t: a tracer burns its composition away over its burn time."""
    if not tracer:
        return 1.0
    burn, lost = tracer
    return 1.0 - lost * min(t / burn, 1.0)


def _integrate(v0: float, bc: float, model: str, atm: Atmosphere, angle: float,
               wind: tuple[float, float, float], max_range: float, min_velocity: float,
               max_time: float, dt: float, tracer: tuple[float, float] | None = None):
    """RK4 flight from the muzzle. Returns lists t, x, y(abs), z, vx, vy, vz and the stop reason.

    tracer: (burn time s, share of the mass it burns away). While it burns the projectile gets lighter (its
    BC falls with its mass) and its drag is TRACER_BASE_DRAG lower."""
    ms, cs = DRAG_TABLES[model]
    rho, c = atm.density, atm.speed_of_sound
    k = math.pi / 8 * rho / bc
    wx, wy, wz = wind

    def accel(t, vx, vy, vz):
        rx, ry, rz = vx - wx, vy - wy, vz - wz
        s = math.sqrt(rx * rx + ry * ry + rz * rz)
        kt = k
        if tracer:
            kt = k / _mass_share(t, tracer) * ((1 - TRACER_BASE_DRAG) if t < tracer[0] else 1.0)
        kd = kt * drag_coefficient(s / c, model) * s
        return -kd * rx, -G - kd * ry, -kd * rz

    t = x = y = z = 0.0
    vx, vy, vz = v0 * math.cos(angle), v0 * math.sin(angle), 0.0
    out = ([t], [x], [y], [z], [vx], [vy], [vz])
    reason = "max time"
    while t < max_time:
        # State s = (x, y, z, vx, vy, vz); derivative = (v, a(t, v)).
        a1 = accel(t, vx, vy, vz)
        a2 = accel(t + 0.5 * dt, vx + 0.5 * dt * a1[0], vy + 0.5 * dt * a1[1], vz + 0.5 * dt * a1[2])
        a3 = accel(t + 0.5 * dt, vx + 0.5 * dt * a2[0], vy + 0.5 * dt * a2[1], vz + 0.5 * dt * a2[2])
        a4 = accel(t + dt, vx + dt * a3[0], vy + dt * a3[1], vz + dt * a3[2])
        nvx = vx + dt / 6 * (a1[0] + 2 * a2[0] + 2 * a3[0] + a4[0])
        nvy = vy + dt / 6 * (a1[1] + 2 * a2[1] + 2 * a3[1] + a4[1])
        nvz = vz + dt / 6 * (a1[2] + 2 * a2[2] + 2 * a3[2] + a4[2])
        # Position: Simpson over the velocities at the four RK stages (a position
        # error of O(dt^5), consistent with the velocity update).
        x += dt * (vx + dt / 6 * (a1[0] + a2[0] + a3[0]))
        y += dt * (vy + dt / 6 * (a1[1] + a2[1] + a3[1]))
        z += dt * (vz + dt / 6 * (a1[2] + a2[2] + a3[2]))
        vx, vy, vz = nvx, nvy, nvz
        t += dt
        for lst, val in zip(out, (t, x, y, z, vx, vy, vz)):
            lst.append(val)
        if x >= max_range:
            reason = "max range"
            break
        if math.sqrt(vx * vx + vy * vy + vz * vz) < min_velocity:
            reason = "minimum velocity"
            break
    return (*out, reason)


def _height_at(v0, bc, model, atm, angle, rng, min_velocity, dt, tracer=None):
    """Bore-relative height of the path at downrange `rng`, or None if it never gets there."""
    t, x, y, z, vx, vy, vz, reason = _integrate(v0, bc, model, atm, angle, (0.0, 0.0, 0.0), rng,
                                               min_velocity, 60.0, dt, tracer)
    if x[-1] < rng:
        return None
    return float(np.interp(rng, x, y))


def zero_angle(v0: float, bc: float, zero_range: float, sight_height: float = 0.04, *,
               drag_model: str = "G7", atmosphere: Atmosphere | None = None,
               min_velocity: float = 50.0, dt: float = 1e-3, tracer: tuple[float, float] | None = None) -> float:
    """Bore elevation (rad above the line of sight) at which the path crosses the LOS
    at `zero_range` m. Solved with the secant method on the height error."""
    if zero_range <= 0:
        raise ValueError("zero range must be positive")
    atm = atmosphere or Atmosphere()

    def error(angle: float) -> float:
        h = _height_at(v0, bc, drag_model, atm, angle, zero_range, min_velocity, dt, tracer)
        if h is None:
            raise ValueError(f"the projectile slows below {min_velocity:.0f} m/s before {zero_range:.0f} m; "
                             "cannot zero at that range")
        return h - sight_height

    a0 = (sight_height + 0.5 * G * (zero_range / v0) ** 2) / zero_range  # vacuum guess
    a1 = a0 * 1.05 + 1e-4
    e0, e1 = error(a0), error(a1)
    for _ in range(30):
        if abs(e1) < 1e-6 or e1 == e0:
            break
        a0, a1, e0 = a1, a1 - e1 * (a1 - a0) / (e1 - e0), e1
        e1 = error(a1)
    return a1


def fly(v0: float, bc: float, mass: float, *, drag_model: str = "G7",
        atmosphere: Atmosphere | None = None, zero_range: float | None = 100.0,
        launch_angle: float | None = None, sight_height: float = 0.04,
        headwind: float = 0.0, crosswind: float = 0.0, max_range: float = 1000.0,
        min_velocity: float = 50.0, max_time: float = 60.0, dt: float = 1e-3,
        tracer: tuple[float, float] | None = None) -> Trajectory:
    """Fly a projectile of muzzle velocity `v0` (m/s), mass (kg) and ballistic coefficient
    `bc` (kg/m^2, for `drag_model`, at the launch mass).

    The bore elevation is `launch_angle` (rad above the line of sight) if given; otherwise
    the gun is zeroed (in still air) at `zero_range` m. Wind (m/s): `headwind` positive
    blows towards the shooter, `crosswind` positive blows from the left to the right (so
    drift is positive). The flight stops at `max_range`, below `min_velocity`, or after
    `max_time`. `tracer` is (burn time s, share of the mass it burns away).
    """
    model = drag_model.upper()
    if model not in DRAG_TABLES:
        raise ValueError(f"unknown drag model {drag_model!r}; use one of {', '.join(DRAG_TABLES)}")
    if v0 <= 0 or bc <= 0 or mass <= 0:
        raise ValueError("muzzle velocity, ballistic coefficient and mass must be positive")
    atm = atmosphere or Atmosphere()
    if launch_angle is None:
        launch_angle = zero_angle(v0, bc, zero_range, sight_height, drag_model=model, atmosphere=atm,
                                  min_velocity=min_velocity, dt=dt, tracer=tracer) if zero_range else 0.0
    t, x, y, z, vx, vy, vz, reason = _integrate(
        v0, bc, model, atm, launch_angle, (-headwind, 0.0, crosswind), max_range, min_velocity, max_time, dt, tracer)
    t, x, y, z = (np.array(a) for a in (t, x, y, z))
    vx, vy, vz = (np.array(a) for a in (vx, vy, vz))
    speed = np.sqrt(vx**2 + vy**2 + vz**2)
    rel = np.sqrt((vx + headwind) ** 2 + vy**2 + (vz - crosswind) ** 2)
    masses = mass * np.array([_mass_share(float(ti), tracer) for ti in t]) if tracer else mass
    traj = Trajectory(
        time=t, x=x, y=y - sight_height, z=z, velocity=speed, mach=rel / atm.speed_of_sound,
        energy=0.5 * masses * speed**2, launch_angle=launch_angle, ballistic_coefficient=bc,
        drag_model=model, sight_height=sight_height, stop_reason=reason)
    if tracer:
        traj.tracer_burnout = tracer[0]
    return traj


def trajectory(gun: Gun, v0: float, *, atmosphere: Atmosphere | None = None, spin: bool = True,
               **kwargs) -> Trajectory:
    """Trajectory of the gun's projectile: BC and drag model from `gun.projectile`
    (estimated from its shape if no BC is set), plus spin drift from the barrel's
    twist unless `spin` is False. An APFSDS's sabot falls away at the muzzle, so
    its rod flies on alone (gun.flight_mass). Other keywords are those of `fly`."""
    p = gun.projectile
    model = p.drag_model.upper()
    burn = tracer_burn(gun)
    tracer = (burn[0], burn[1] / gun.flight_mass) if burn else None
    traj = fly(v0, ballistic_coefficient(gun), gun.flight_mass, drag_model=model, atmosphere=atmosphere,
               tracer=tracer, **kwargs)
    traj.fuze_time = p.fuze_time or None
    if spin and gun.barrel.twist:
        atm = atmosphere or Atmosphere()
        traj.stability = rifling.stability(gun, v0, atm.temperature, atm.pressure)
        traj.spin_drift = rifling.spin_drift(traj.stability, traj.time, gun.barrel.twist)
        traj.z = traj.z + traj.spin_drift
    return traj
