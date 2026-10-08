"""Recoil and action cycling: how the gun moves when it fires, and how it reloads.

Loads. The interior-ballistics models record what the shot does to the gun
(ShotResult.loads): the gas pressure on the bolt face, the rest of the push on
the barrel (the chamber shoulder and the projectile's drag on the bore pull it
forwards), and, during blowdown, the reaction of the gas jet. They also record
the gas at a port in the barrel. The forces integrate to the recoil impulse.

Bodies. Everything moves along the bore axis, plus the gun's pitch:

* the gun (receiver, barrel, stock) recoils a distance x and pitches the
  muzzle up by theta, about the shoulder (or about its centre of mass when
  nothing holds it);
* the bolt group (bolt and carrier, or a pistol's slide) slides a distance s
  back inside it against the return spring, from closed (s = 0) to the rear
  stop (s = stroke);
* with a shoulder, the part of the shooter's body that moves with the butt
  is added to the gun, and the shoulder is a spring and damper to the rest of
  the body. The hold resists pitch with a torsional spring and damper.

Actions. Which body the bore forces push depends on the action:

* bolt: locked; the shot pushes the whole gun. The bolt is worked by hand.
* gas: locked until the carrier has moved `unlock_travel`. Gas flows from the
  port into the cylinder through the port as through an orifice (choked or
  subsonic compressible flow, either way), and its pressure drives the piston
  and carrier until the piston has moved `gas_stroke`, when the cylinder
  vents. The reaction pushes the gas block forwards. Once unlocked, any
  pressure left in the chamber pushes the bolt too.
* direct_impingement: locked like gas, but there is no piston: the port feeds
  a long thin gas tube (a volume of its own, with friction setting its
  outlet's discharge coefficient and heat lost to its wall), which empties
  into an expansion chamber between the carrier and the bolt's tail. The
  carrier is the cylinder, the locked bolt the piston: the chamber pushes the
  carrier back and, through the bolt's lugs, the barrel forwards. Once the
  bolt unlocks it rides with the carrier, so the chamber's pressure is
  internal to the bolt group and pushes nothing; it vents through the
  carrier's holes after `gas_stroke`.
* blowback: never locked. The breech pressure pushes the bolt from the
  start, held back only by its inertia and the spring.
* short_recoil: the barrel and slide recoil locked together inside the frame
  until the barrel has moved `unlock_travel`, where it stops against the frame
  and unlocks; the slide carries on. Going forward, the slide picks the barrel
  up and returns it to battery.
* roller_delayed, lever_delayed: delayed blowback with a two-part bolt. The
  breech pressure pushes the light bolt head from the start, but rollers (or a
  lever) bearing on the receiver make the heavy carrier move `delay_ratio`
  times as fast as the head. The head then feels the carrier as a mass of
  m_head + K^2 m_carrier (K = delay_ratio), so it opens slowly, and the
  receiver takes the rest of the push through the rollers. Once the carrier
  has moved `unlock_travel` the rollers are in and the head is pulled along
  (head and carrier share their momentum); from there it is a plain blowback.
  The two are solved as one degree of freedom with the gun from their kinetic
  energy (Lagrange), so momentum is kept exactly.
* gas_delayed: blowback held shut by gas. A port near the chamber feeds a
  cylinder whose piston pushes the slide forwards; opening the slide drives
  the piston into the cylinder and compresses the gas, so the slide stays
  nearly shut until the bore pressure falls and the gas runs back out of the
  port.

Impacts at the rear stop and in battery are instantaneous, with a coefficient
of restitution; the impulse is shared between the bolt and the gun by their
masses (the shoulder is far too soft to take part). The bolt ejects the case
once it has come back a case length (plus 3 mm), can pick up the next round
once it has come back past a whole round, and drags `feed_force` while it
pushes that round into the chamber.

Pitch. The forces act along the bore, `bore_height` above the shoulder, so
every axial force on the gun body turns it: the shot lifts the muzzle, and the
bolt slamming into the rear stop gives it a second kick. Internal forces along
the same line cancel.

Bursts. A self-loading action can fire several shots: each is fired
LOCK_TIME after the bolt is back in battery on the one before, with
everything (the gun's recoil and pitch, the gas cylinder) carried over, so
recoil and muzzle climb build up through the burst. The gas port's discharge
coefficient comes from a 2D solution of the port (devices.py) unless
solver.gas_port_2d is off; a muzzle device's mass is added to the gun.

Approximations: the bolt and carrier move as one mass (a real carrier runs
free for its unlock travel before it picks up the bolt), except in a delayed
blowback, whose delay ratio is constant (real roller and lever angles change
it a little over the stroke) and whose carrier closes its gap at once when
the head reaches battery; no friction except
feeding, no hammer to cock, and the case leaves the chamber freely. The gas in
the cylinder is ideal and keeps its heat. The shooter's body moves rigidly
with the butt, and is linear. Small angles throughout.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from .config import Gun
    from .results import ShotResult

AMBIENT = 101325.0        # Pa
AIR_TEMPERATURE = 300.0   # K
STEEL_DENSITY = 7850.0    # kg/m^3
DURATION = 0.3            # s simulated from ignition
FAST_DT, FAST_UNTIL = 2e-6, 0.02  # fine steps while the gas acts
SLOW_DT = 2e-5
OUT_FAST, OUT_SLOW = 2e-5, 5e-4   # output sampling, before and after FAST_UNTIL
ORIFICE_CD = 0.8          # discharge coefficient of the gas port, unless solved in 2D (devices.py)
LOCK_TIME = 0.003         # s from back in battery to the next ignition in a burst (sear, hammer, primer)
MAX_BURST = 30
REST_SPEED = 0.05         # m/s: slower than this after closing, the bolt stays shut
# Thresholds for the warnings.
REAR_SPEED_WARNING = 8.0        # m/s into the rear stop
UNLOCK_PRESSURE_WARNING = 20e6  # Pa in the chamber when it unlocks
CASE_PRESSURE = 30e6            # Pa: above this the case is pressed hard into the chamber
CASE_SETBACK_WARNING = 1e-3     # m the case may back out while it is
# Delayed blowback: (carrier speed / head speed while delayed, carrier travel until unlocked).
DELAYED = {"roller_delayed": (4.0, 5e-3), "lever_delayed": (6.0, 6e-3)}
GAS_SYSTEMS = ("gas", "direct_impingement", "gas_delayed")
LOCKED_GAS = ("gas", "direct_impingement")   # locked until the carrier has moved unlock_travel
HEAD_SHARE = 0.2                # delayed blowback: bolt head's share of bolt_mass, unless given
# Direct impingement gas tube: Darcy friction factor and the wall's temperature. Heat goes to
# the wall by Dittus-Boelter (Nu = 0.023 Re^0.8 Pr^0.4, at least the laminar 3.66) with the
# propellant gas's viscosity, conductivity and Prandtl number.
TUBE_FRICTION = 0.03
TUBE_WALL = AIR_TEMPERATURE
GAS_VISCOSITY = 6e-5            # Pa s
GAS_CONDUCTIVITY = 0.15         # W/(m K)
GAS_PRANDTL = 0.7


def tube_heat(flow: float, diameter: float) -> float:
    """Heat transfer coefficient (W/(m^2 K)) of gas flowing at `flow` kg/s down a tube."""
    re = 4 * abs(flow) / (math.pi * diameter * GAS_VISCOSITY)
    nu = max(3.66, 0.023 * re**0.8 * GAS_PRANDTL**0.4)
    return nu * GAS_CONDUCTIVITY / diameter


def gas_tube(gun: Gun) -> tuple[float, float]:
    """Direct impingement: gas tube (length, inside diameter) in m. The tube runs from
    the gas block back to the carrier key, over the bolt: about the port's distance from
    the case head, unless given."""
    a = gun.action
    length = a.gas_tube_length if a.gas_tube_length is not None else port_position(gun) + gun.case.length
    return length, a.gas_tube_diameter


def tube_cd(gun: Gun) -> float:
    """Discharge coefficient of the gas tube's outlet: an orifice with the tube's friction losses ahead of it."""
    length, diameter = gas_tube(gun)
    return ORIFICE_CD / math.sqrt(1 + TUBE_FRICTION * length / diameter)


def delay(gun: Gun) -> tuple[float, float]:
    """Delayed blowback: (delay ratio K, bolt head mass in kg)."""
    a = gun.action
    ratio = a.delay_ratio if a.delay_ratio is not None else DELAYED.get(a.type, (1.0, 0.0))[0]
    head = a.bolt_head_mass if a.bolt_head_mass is not None else HEAD_SHARE * a.bolt_mass
    return ratio, head


def head_area(gun: Gun) -> float:
    """Area the breech pressure pushes the bolt with: the largest inside cross-section of the case."""
    from .chamber import ChamberProfile
    try:
        return float(ChamberProfile.from_case(gun).area.max())
    except ValueError:
        return gun.barrel.bore_area


def port_position(gun: Gun) -> float:
    """Projectile travel from its seat to the gas port (m)."""
    position = gun.action.gas_port_position
    if position is not None:
        return position
    # A gas-delayed port sits just ahead of the chamber, where the pressure is.
    return (0.1 if gun.action.type == "gas_delayed" else 0.75) * gun.barrel.travel


def barrel_mass(gun: Gun) -> float:
    """The barrel's mass: given, or its steel (a frustum between the outside diameters, less the bore)."""
    if gun.action.barrel_mass is not None:
        return gun.action.barrel_mass
    bar = gun.barrel
    length = gun.case.length + bar.travel
    d1, d2 = bar.breech_diameter, bar.muzzle_diameter
    return STEEL_DENSITY * (math.pi / 12 * length * (d1 * d1 + d1 * d2 + d2 * d2) - bar.bore_area * length)


def strokes(gun: Gun) -> dict:
    """Bolt travel (m) at which things happen.

    For a delayed blowback the bolt travel is the bolt head's (the bolt face),
    and "unlock" is how far the head has come back when the carrier has moved
    unlock_travel; "carrier_unlock" is that carrier travel.
    """
    a, c = gun.action, gun.case
    eject = c.length + 3e-3          # the case is clear of the chamber and hits the ejector
    feed = c.overall_length + 3e-3   # the bolt face is behind the next round
    stroke = a.bolt_travel if a.bolt_travel is not None else feed + 8e-3
    defaults = {"gas": 6e-3, "direct_impingement": 7e-3, "short_recoil": 3e-3, **{k: v[1] for k, v in DELAYED.items()}}
    unlock = a.unlock_travel if a.unlock_travel is not None else defaults.get(a.type, 0.0)
    out = {"eject": eject, "feed": feed, "stroke": stroke, "unlock": min(unlock, stroke)}
    if a.type in DELAYED:
        out["carrier_unlock"] = unlock
        out["unlock"] = min(unlock / delay(gun)[0], stroke)
    return out


def _orifice(area: float, p_up: float, t_up: float, p_down: float, gamma: float, r_gas: float,
             cd: float = ORIFICE_CD) -> float:
    """Mass flow (kg/s) of an ideal gas through an orifice from p_up to p_down."""
    if p_up <= p_down:
        return 0.0
    ratio = p_down / p_up
    k = cd * area * p_up / math.sqrt(r_gas * t_up)
    if ratio <= (2 / (gamma + 1)) ** (gamma / (gamma - 1)):  # choked
        return k * math.sqrt(gamma) * (2 / (gamma + 1)) ** ((gamma + 1) / (2 * (gamma - 1)))
    return k * math.sqrt(2 * gamma / (gamma - 1) * (ratio ** (2 / gamma) - ratio ** ((gamma + 1) / gamma)))


def _exchange(area: float, cd: float, p1: float, t1: float, p2: float, t2: float,
              gamma: float, r_gas: float) -> tuple[float, float]:
    """Flow (kg/s, + from 1 to 2) through an orifice between two gases, and the
    specific enthalpy it carries (J/kg)."""
    cp = gamma * r_gas / (gamma - 1)
    if p1 > p2:
        return _orifice(area, p1, t1, p2, gamma, r_gas, cd), cp * t1
    return -_orifice(area, p2, t2, p1, gamma, r_gas, cd), cp * t2


@dataclass
class ActionResult:
    kind: str                     # action type
    stance: str                   # shooter stance
    time: np.ndarray              # s from the first ignition
    recoil: np.ndarray            # m the gun has moved back
    recoil_velocity: np.ndarray   # m/s, + rearwards
    pitch: np.ndarray             # rad, + muzzle up
    bolt: np.ndarray              # m the bolt has moved back inside the gun
    bolt_velocity: np.ndarray     # m/s relative to the gun, + rearwards
    force: np.ndarray             # N, the shots' force on the gun (+ rearwards)
    shoulder_force: np.ndarray    # N, the gun pushing on the shooter
    gas_pressure: np.ndarray      # Pa, in the gas cylinder (gas action)
    impulse: float                # N s, recoil impulse of one shot
    free_recoil_velocity: float   # m/s, of the gun alone, one shot
    free_recoil_energy: float     # J
    max_recoil: float             # m
    peak_recoil_velocity: float   # m/s
    peak_shoulder_force: float    # N
    max_pitch: float              # rad
    bolt_max_travel: float        # m
    strokes: dict                 # see strokes()
    status: str                   # "manual", "cycled", or what went wrong
    gun_mass: float = 0.0         # kg, with any muzzle device
    events: list = field(default_factory=list)    # {"time", "name", "detail", "shot"}
    warnings: list = field(default_factory=list)
    shot_times: list = field(default_factory=list)  # s, ignition of each shot of a burst
    rear_speed: float | None = None       # m/s, bolt into the rear stop (first shot)
    cycle_time: float | None = None       # s, ignition to back in battery (first shot)
    unlock_pressure: float | None = None  # Pa in the chamber when the bolt unlocks (first shot)
    gas_peak_pressure: float | None = None  # Pa
    port_cd: float | None = None          # discharge coefficient of the gas port used
    port_cd_2d: bool = False              # True if it came from the 2D solution of the port

    @property
    def shots(self) -> int:
        return len(self.shot_times)

    @property
    def cyclic_rate(self) -> float | None:
        """Rounds per minute: from the burst, or from one cycle plus the lock time."""
        if len(self.shot_times) > 1:
            return 60 * (len(self.shot_times) - 1) / (self.shot_times[-1] - self.shot_times[0])
        return 60 / (self.cycle_time + LOCK_TIME) if self.cycle_time else None

    def summary(self) -> str:
        lines = [
            f"  recoil impulse       {self.impulse:9.2f} N s; free recoil {self.free_recoil_velocity:.2f} m/s, "
            f"{self.free_recoil_energy:.1f} J",
            f"  with the shooter     {self.max_recoil * 1e3:9.1f} mm back at up to {self.peak_recoil_velocity:.2f} m/s, "
            f"muzzle rise {math.degrees(self.max_pitch):.2f} deg, peak shoulder force {self.peak_shoulder_force:.0f} N"
            if self.stance == "shoulder" else
            f"  free recoil          {self.max_recoil * 1e3:9.1f} mm in {self.time[-1] * 1e3:.0f} ms, "
            f"muzzle rise {math.degrees(self.max_pitch):.2f} deg",
        ]
        if self.kind != "bolt":
            line = f"  {self.kind.replace('_', ' ') + ' action':20s} {self.status}"
            if self.shots > 1:
                line += f", {self.shots} shots"
            elif self.cycle_time:
                line += f" in {self.cycle_time * 1e3:.1f} ms"
            if self.cyclic_rate:
                line += f" ({self.cyclic_rate:.0f} rounds/min)"
            if self.rear_speed is not None:
                line += f", bolt at {self.rear_speed:.1f} m/s into the rear stop"
            lines.append(line)
            if self.port_cd is not None:
                lines.append(f"  gas port Cd          {self.port_cd:9.2f}" + (" (2D)" if self.port_cd_2d else ""))
        lines += [f"  warning: {w}" for w in self.warnings]
        return "\n".join(lines)


class _Loads:
    """A shot's loads on a fine uniform grid, so a burst can look them up by index."""

    def __init__(self, loads):
        self.end = float(loads.t[-1])
        n = int(self.end / FAST_DT) + 1
        tau = (np.arange(n) + 0.5) * FAST_DT
        self.breech = np.interp(tau, loads.t, loads.breech_force, left=0.0, right=0.0)
        self.barrel = np.interp(tau, loads.t, loads.barrel_force, left=0.0, right=0.0)
        self.p = np.interp(tau, loads.t, loads.port_pressure, left=AMBIENT, right=AMBIENT)
        self.T = np.interp(tau, loads.t, loads.port_temperature, left=AIR_TEMPERATURE, right=AIR_TEMPERATURE)
        self.n = n

    def at(self, shot_times, t):
        """Breech and barrel force (all shots), and the port gas of the newest shot under way."""
        fb = fr = 0.0
        p, T = AMBIENT, AIR_TEMPERATURE
        for t0 in shot_times:
            i = int((t - t0) / FAST_DT)
            if 0 <= i < self.n:
                fb += self.breech[i]
                fr += self.barrel[i]
                if self.p[i] > p:
                    p, T = self.p[i], self.T[i]
        return fb, fr, p, T


def simulate(gun: Gun, shot: ShotResult, shots: int = 1) -> ActionResult:
    """Recoil of the gun and the cycle of its action, from a shot's loads.

    shots > 1 fires a burst (self-loading actions only): each shot is fired
    LOCK_TIME after the bolt is back in battery on the previous one, with the
    gun's motion carried over, so recoil and muzzle climb build up. The burst
    stops early if a cycle fails.
    """
    from . import devices
    loads = shot.loads
    if loads is None or len(loads.t) < 2:
        raise ValueError("this shot has no recorded loads on the gun")
    a, sh = gun.action, gun.shooter
    kind = a.type
    shots = 1 if kind == "bolt" else int(min(max(shots, 1), MAX_BURST))
    geo = strokes(gun)
    stroke, unlock, eject_at, feed_at = geo["stroke"], geo["unlock"], geo["eject"], geo["feed"]
    m_bolt = a.bolt_mass
    m_bar = barrel_mass(gun) if kind == "short_recoil" else 0.0
    gun_mass = a.gun_mass + devices.device_mass(gun)
    if m_bolt + m_bar >= gun_mass:
        raise ValueError(f"short recoil: the slide and barrel ({(m_bolt + m_bar):.2f} kg) "
                         f"must be lighter than the gun ({gun_mass:.2f} kg)")
    shoulder = sh.stance == "shoulder"
    m_body = sh.body_mass if shoulder else 0.0
    k_sh, c_sh = (sh.shoulder_stiffness, sh.shoulder_damping) if shoulder else (0.0, 0.0)
    k_th, c_th = (sh.hold_stiffness, sh.hold_damping) if shoulder else (0.0, 0.0)
    arm = a.cg_distance if shoulder else 0.0
    inertia = gun_mass * (a.radius_of_gyration**2 + arm**2)
    h = a.bore_height
    gamma, r_gas = gun.propellant.gamma, gun.propellant.gas_constant
    cv = r_gas / (gamma - 1)
    port_area = math.pi / 4 * a.gas_port_diameter**2
    piston_area = math.pi / 4 * a.piston_diameter**2

    # Delayed blowback: head and carrier, and the carrier's speed over the head's while delayed.
    ratio, m_head = delay(gun) if kind in DELAYED else (1.0, m_bolt)
    m_carrier = m_bolt - m_head
    carrier_gap = (ratio - 1) * unlock   # how far the carrier is ahead of the head once unlocked
    # The gas cylinder grows as a gas piston is driven back, and shrinks as a gas-delayed slide opens.
    swept = -1.0 if kind == "gas_delayed" else 1.0

    port_cd, port_2d = None, False
    if kind in GAS_SYSTEMS:
        port_cd = ORIFICE_CD
        if gun.solver.gas_port_2d:
            port = devices.port_discharge(gun, loads)
            if port is not None:
                port_cd, port_2d = port["cd"], True

    table = _Loads(loads)
    fast_for = max(FAST_UNTIL, table.end + 1e-3)   # fine steps while a shot's gas acts

    x = v = th = w = 0.0      # gun: recoil, velocity, pitch, pitch rate
    s = u = 0.0               # bolt: travel and velocity in the gun
    carry = kind == "short_recoil"   # barrel still moving with the slide
    unlocked = kind in ("blowback", "gas_delayed", *DELAYED)   # the breech pressure pushes the bolt
    delayed = kind in DELAYED        # rollers (lever) out: the carrier runs `ratio` times the head's speed
    sealed = True             # gas cylinder closed (the piston hasn't reached the vent)
    m_c = AMBIENT * a.gas_volume / (r_gas * AIR_TEMPERATURE)  # cylinder starts full of air
    e_c = m_c * cv * AIR_TEMPERATURE
    # Direct impingement: the gas tube between the port and the expansion chamber, also full of air.
    impinge = kind == "direct_impingement"
    if impinge:
        tube_len, tube_d = gas_tube(gun)
        tube_area, tube_k = math.pi / 4 * tube_d**2, tube_cd(gun)
        v_tube, tube_wall = tube_area * tube_len, math.pi * tube_d * tube_len
        m_t = AMBIENT * v_tube / (r_gas * AIR_TEMPERATURE)
        e_t = m_t * cv * AIR_TEMPERATURE
    p_c = gas_peak = AMBIENT
    rear_speed = unlock_pressure = first_battery = None
    s_max = setback = 0.0
    events, warnings = [], []
    shot_times = [0.0]
    cyc = {}                  # this shot's cycle: ejected, can_feed, feeding, battery, s_max
    next_shot = None
    out = {k: [] for k in ("t", "x", "v", "th", "s", "u", "force", "shoulder", "gas")}
    next_out = 0.0

    def event(t, name, detail="", speed=None):
        events.append({"time": t, "name": name, "detail": detail, "shot": len(shot_times), "speed": speed})

    def new_cycle():
        cyc.update(ejected=False, can_feed=False, feeding=False, battery=None, s_max=0.0)

    def masses():
        m_g = m_bolt + (m_bar if carry else 0.0)
        return m_g, gun_mass - m_g + m_body

    new_cycle()
    event(0.0, "fires")
    t = 0.0
    end = DURATION
    while t < end:
        fast = t - shot_times[-1] < fast_for
        dt = FAST_DT if fast else SLOW_DT
        fb, fr, pp, tp = table.at(shot_times, t + 0.5 * dt)
        m_g, m_r = masses()
        # Bore forces on the bolt group and on the gun body.
        if kind == "bolt":
            g_ext, r_ext = 0.0, fb + fr
        elif kind == "short_recoil":
            g_ext, r_ext = (fb + fr, 0.0) if carry else (fb, fr)
        elif unlocked:
            g_ext, r_ext = fb, fr
        else:
            g_ext, r_ext = 0.0, fb + fr

        f_piston = 0.0
        if kind in GAS_SYSTEMS:
            # A direct impingement chamber only grows while the bolt is locked; then it rides along.
            grows = min(s, unlock) if impinge else s
            if sealed:
                vol = a.gas_volume + swept * piston_area * grows
                p_c = (gamma - 1) * e_c / vol
                t_c = p_c * vol / (m_c * r_gas)
            else:
                p_c, t_c = AMBIENT, AIR_TEMPERATURE
            if impinge:
                # Port -> tube -> expansion chamber (or out of the carrier's vents).
                p_t = (gamma - 1) * e_t / v_tube
                t_t = p_t * v_tube / (m_t * r_gas)
                f_in, h_in = _exchange(port_area, port_cd, pp, tp, p_t, t_t, gamma, r_gas)
                flow, enthalpy = _exchange(tube_area, tube_k, p_t, t_t, p_c, t_c, gamma, r_gas)
                cooling = tube_heat(max(abs(f_in), abs(flow)), tube_d) * tube_wall * (t_t - TUBE_WALL)
                m_t = max(m_t + (f_in - flow) * dt, 1e-12)
                e_t = max(e_t + (f_in * h_in - flow * enthalpy - cooling) * dt, 1e-9)
            else:
                flow, enthalpy = _exchange(port_area, port_cd, pp, tp, p_c, t_c, gamma, r_gas)
            if sealed:
                du = 0.0 if impinge and s >= unlock else u
                m_c = max(m_c + flow * dt, 1e-12)
                e_c = max(e_c + (flow * enthalpy - p_c * swept * piston_area * du) * dt, 1e-9)
                # Once a direct impingement bolt unlocks, the chamber is inside the moving bolt group.
                if not (impinge and unlocked):
                    f_piston = swept * (p_c - AMBIENT) * piston_area
                gas_peak = max(gas_peak, p_c)

        # Forces between the bolt group and the gun (+ pushes the bolt back). The spring
        # bears on the carrier, which a delayed blowback's head drives `ratio` times as far.
        carrier = ratio * s if delayed else s + carrier_gap
        f_spring = a.spring_preload + a.spring_rate * carrier
        f_int = f_piston - f_spring
        if cyc["feeding"] and u < 0 and s < feed_at:
            f_int += a.feed_force
        f_sh = -(k_sh * x + c_sh * v)
        if delayed:
            # Gun (x) and head (s) from T = m_r x'^2/2 + m_head (x' + s')^2/2 + m_carrier (x' + K s')^2/2:
            # the bore pushes the head, the spring the carrier through the rollers.
            m11, m12, m22 = m_g + m_r, m_head + ratio * m_carrier, m_head + ratio**2 * m_carrier
            q1, q2 = g_ext + r_ext + f_sh, g_ext - ratio * f_spring
            det = m11 * m22 - m12 * m12
            acc_r, rel = (q1 * m22 - q2 * m12) / det, (m11 * q2 - m12 * q1) / det
        else:
            acc_g = (g_ext + f_int) / m_g
            acc_r = (r_ext - f_int + f_sh) / m_r
            rel = acc_g - acc_r
        held = kind == "bolt" or (s <= 0 and u <= 0 and rel <= 0)
        if held:  # the bolt is shut and stays shut: one body
            acc_r = (g_ext + r_ext + f_sh) / (m_g + m_r)
            axial = g_ext + r_ext
            s = u = 0.0
        else:
            axial = m_r * acc_r - f_sh   # what acts on the gun body (the shooter's share aside)
        v += acc_r * dt
        x += v * dt
        w += (h * axial - k_th * th - c_th * w) / inertia * dt
        th += w * dt
        t_end = t + dt

        if not held:
            u += rel * dt
            s += u * dt
            if delayed and s >= unlock and u > 0:
                # The rollers are in: the carrier pulls the head along, and they move on as one.
                delayed = False
                u *= (m_head + ratio * m_carrier) / m_g
                p_unlock = fb / loads.head_area + AMBIENT
                unlock_pressure = unlock_pressure or p_unlock
                event(t_end, "bolt unlocks", f"{p_unlock / 1e6:.1f} MPa in the chamber")
            # An impact that changes the bolt's speed in the gun by du changes the gun's by
            # -du m12 / m11 (from the mass matrix above: m12 = m_g for a one-piece bolt).
            share = (m_head + ratio * m_carrier if delayed else m_g) / (m_g + m_r)
            if s >= stroke and u > 0:  # into the rear stop
                if rear_speed is None:
                    rear_speed = u
                event(t_end, "bolt hits the rear stop", f"{u:.1f} m/s", u)
                dv = (1 + a.rear_restitution) * u * share
                v += dv
                w += h * m_r * dv / inertia
                s, u = stroke, -a.rear_restitution * u
            elif s <= 0 and u < 0:  # closes
                dv = (1 + a.battery_restitution) * u * share
                v += dv
                w += h * m_r * dv / inertia
                speed = -u
                s, u = 0.0, -a.battery_restitution * u
                if u < REST_SPEED:
                    u = 0.0
                if kind in DELAYED:
                    # The carrier closes its gap and cams the rollers out again; any rebound keeps its momentum.
                    delayed = True
                    u *= m_g / (m_head + ratio * m_carrier)
                if cyc["feeding"] and cyc["battery"] is None:
                    cyc["battery"] = t_end
                    first_battery = first_battery or t_end
                    event(t_end, "back in battery", f"{speed:.1f} m/s", speed)
                    if len(shot_times) < shots:
                        next_shot = t_end + LOCK_TIME
                elif cyc["ejected"] and not cyc["can_feed"] and cyc["battery"] is None:
                    cyc["battery"] = -1.0
                    event(t_end, "closes on an empty chamber", f"{speed:.1f} m/s", speed)
            s_max = max(s_max, s)
            cyc["s_max"] = max(cyc["s_max"], s)

            if kind in LOCKED_GAS:
                if not unlocked and s >= unlock:
                    unlocked = True
                    p_unlock = fb / loads.head_area + AMBIENT
                    unlock_pressure = unlock_pressure or p_unlock
                    event(t_end, "bolt unlocks", f"{p_unlock / 1e6:.1f} MPa in the chamber")
                elif unlocked and s < unlock and u < 0:
                    unlocked = False  # locks again on the way home
            if kind in GAS_SYSTEMS:
                if sealed and s >= a.gas_stroke:
                    sealed = False
                    event(t_end, "gas cylinder vents")
                elif not sealed and s < a.gas_stroke and u < 0:
                    sealed = True  # the piston closes the cylinder again, on air
                    m_c = AMBIENT * (a.gas_volume + swept * piston_area * (min(s, unlock) if impinge else s)) / (r_gas * AIR_TEMPERATURE)
                    e_c = m_c * cv * AIR_TEMPERATURE
            elif kind == "short_recoil":
                if carry and s >= unlock and u > 0:  # the barrel stops against the frame
                    m_r2 = m_r + m_bar
                    v2 = (m_r * v + m_bar * (v + u)) / m_r2
                    w += h * m_r * (v2 - v) / inertia
                    u, v, carry = v + u - v2, v2, False
                    p_unlock = fb / loads.head_area + AMBIENT
                    unlock_pressure = unlock_pressure or p_unlock
                    event(t_end, "barrel stops and unlocks", f"{p_unlock / 1e6:.1f} MPa in the chamber")
                elif not carry and s < unlock and u < 0:  # the slide picks the barrel up
                    u = (m_bolt * (v + u) + m_bar * v) / (m_bolt + m_bar) - v
                    carry = True

            if not cyc["ejected"] and s >= eject_at:
                cyc["ejected"] = True
                event(t_end, "case ejected", f"bolt at {u:.1f} m/s", u)
            if not cyc["can_feed"] and s >= feed_at:
                cyc["can_feed"] = True
            if cyc["can_feed"] and not cyc["feeding"] and u < 0 and s < feed_at:
                cyc["feeding"] = True
                event(t_end, "strips the next round")

            # How far the case has backed out of the chamber while still pressed into it.
            free = s - unlock if kind in (*LOCKED_GAS, "short_recoil") else s
            if (unlocked or (kind == "short_recoil" and not carry)) and fb / loads.head_area > CASE_PRESSURE:
                setback = max(setback, free)

        if t >= next_out:
            next_out += OUT_FAST if fast else OUT_SLOW
            out["t"].append(t_end)
            out["x"].append(x)
            out["v"].append(v)
            out["th"].append(th)
            out["s"].append(s)
            out["u"].append(u)
            out["force"].append(fb + fr)
            out["shoulder"].append(-f_sh)
            out["gas"].append(p_c)
        t = t_end

        # Back in battery: fire the next shot of the burst.
        if next_shot is not None and t >= next_shot:
            next_shot = None
            shot_times.append(t)
            new_cycle()
            event(t, "fires")
            end = t + DURATION

    status = "manual" if kind == "bolt" else "cycled"
    if kind != "bolt":
        n = len(shot_times)
        which = f" on shot {n}" if shots > 1 else ""
        if not cyc["ejected"]:
            status = "failed to eject"
            warnings.append(f"short stroke{which}: the bolt only came back {cyc['s_max'] * 1e3:.0f} mm, "
                            f"and it needs {eject_at * 1e3:.0f} mm to eject the case")
        elif not cyc["can_feed"]:
            status = "failed to feed"
            warnings.append(f"short stroke{which}: the bolt came back {cyc['s_max'] * 1e3:.0f} mm, ejecting "
                            f"the case, but it needs {feed_at * 1e3:.0f} mm to pick up the next round")
        elif cyc["battery"] is None or cyc["battery"] < 0:
            status = "did not return to battery"
            warnings.append(f"the return spring did not close the bolt on the new round{which}")
        if status != "cycled" and n < shots:
            warnings.append(f"the burst stopped after {n} of {shots} shots")
    if rear_speed is not None and rear_speed > REAR_SPEED_WARNING:
        cure = {"gas": "over-gassed; a smaller gas port, a heavier carrier or a stiffer spring would ease it",
                "direct_impingement": "over-gassed; a smaller gas port, a heavier carrier or buffer, or a stiffer spring would ease it",
                "blowback": "a heavier bolt or a stiffer spring would slow it",
                "short_recoil": "a heavier slide or a stiffer spring would slow it",
                "gas_delayed": "a bigger piston or a port nearer the chamber would hold it back longer",
                }.get(kind, "a higher delay ratio, a heavier carrier or a stiffer spring would slow it")
        warnings.append(f"the bolt hits the rear stop at {rear_speed:.1f} m/s, battering the gun: {cure}")
    flutes = " (delayed blowbacks use a fluted chamber so the case can slide)" if kind in DELAYED else ""
    if unlock_pressure is not None and unlock_pressure > UNLOCK_PRESSURE_WARNING:
        warnings.append(f"it unlocks with {unlock_pressure / 1e6:.0f} MPa still in the chamber, "
                        "so the case is pulled while pressed into the chamber walls" + flutes)
    if setback > CASE_SETBACK_WARNING:
        warnings.append(f"the case backs {setback * 1e3:.1f} mm out of the chamber while the chamber is still "
                        f"above {CASE_PRESSURE / 1e6:.0f} MPa: its unsupported head may rupture" + flutes)

    impulse = loads.impulse
    arr = {k: np.array(val) for k, val in out.items()}
    shoulder_force = arr["shoulder"] if shoulder else np.zeros_like(arr["t"])
    return ActionResult(
        kind=kind, stance=sh.stance, time=arr["t"],
        recoil=arr["x"], recoil_velocity=arr["v"], pitch=arr["th"],
        bolt=arr["s"], bolt_velocity=arr["u"], force=arr["force"],
        shoulder_force=shoulder_force, gas_pressure=arr["gas"],
        impulse=impulse,
        free_recoil_velocity=impulse / gun_mass,
        free_recoil_energy=impulse**2 / (2 * gun_mass),
        max_recoil=float(arr["x"].max()),
        peak_recoil_velocity=float(arr["v"].max()),
        peak_shoulder_force=float(shoulder_force.max()),
        max_pitch=float(arr["th"].max()),
        bolt_max_travel=s_max,
        strokes=geo,
        status=status,
        gun_mass=gun_mass,
        events=events,
        warnings=warnings,
        shot_times=shot_times,
        rear_speed=rear_speed,
        cycle_time=first_battery,
        unlock_pressure=unlock_pressure,
        gas_peak_pressure=gas_peak if kind in GAS_SYSTEMS else None,
        port_cd=port_cd,
        port_cd_2d=port_2d,
    )
