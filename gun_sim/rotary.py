"""Rotary guns: Gatling-type multi-barrel guns and revolver cannon (action.type = "rotary").

The rotor. Everything that cycles turns with one shaft, at angle phi:

* "gatling": a cluster of `barrels` barrels round the rotor's axis, each with its own bolt
  riding a fixed elliptical cam track in the receiver. A barrel's bolt is locked over the
  top of its turn, where it fires, draws the case back down one side, sits open at the
  bottom while the feeder drops the next round in front of it, and rams it along the
  other side, locking again before the top (M61, M134, GAU-8, GSh-6-23, the Slostin).
* "revolver": one barrel, fed from a drum of `chambers` chambers turning behind it; each
  chamber's rammer rides the cam in the same way, ramming its round into the chamber as
  the drum brings it up and drawing the case out after it fires (BK-27).

Either way a station (a barrel, or a chamber) at angle theta from the firing position
fires as it reaches the top (theta = 0 = 2 pi). The bolt's (rammer's) travel is s = S(theta),
a dwell, then a cycloidal stroke back, a dwell open, a cycloidal stroke home and a dwell
locked (cam()), so the rotor, the bolts and the drive are solved together from their
kinetic energy (Lagrange):

    T = (J + J_drive) w^2 / 2 + sum_i m_i (S'(theta_i) w)^2 / 2  =  J_eff(phi) w^2 / 2
    J_eff w' + J_eff'(phi) w^2 / 2 = torque of the drive - friction - damping w - feed load,

with m_i a bolt, plus the round (or case) it carries. Each round is caught by the rotor
from rest as the feeder puts it in its station (angular momentum kept, its energy lost),
rides it as part of J, and its case leaves with its own momentum at the ejection port;
the belt's (or a linkless chute's) pull, and `feed_force` over a link's pitch, are a
torque while it feeds.

Drives (`rotary_drive`):

* "electric": a DC motor, its torque falling linearly with speed from stall to the free
  speed at which the gun would fire `rotary_rate` rounds/min (motor_power is its peak
  power, a quarter of stall torque times free speed). It runs on after the last round to
  clear the gun, then brakes dynamically. (A gas- or recoil-driven gun has a rotor brake, which stops it in
ROTOR_BRAKE_TIME from its top speed once it is clear.)
* "hydraulic": a hydraulic motor fed through a valve that opens over `valve_time`; full
  torque (motor_power at rotary_rate) until the supply's flow runs out at the speed for
  rotary_rate, where it falls away steeply. Closing the valve brakes the rotor hard.
* "gas": the gun drives itself. A starter (a pyrotechnic or pneumatic cartridge,
  `starter_energy`) turns the rotor up to the first shot; then each barrel that has just
  fired bleeds gas from its port into its own cylinder (as action.py's gas system), whose
  piston drives the rotor through a helical cam, `cam_lever` m of piston per radian,
  until it has moved `gas_stroke` and vents. A revolver's gas slide drives the drum the
  same way. The rate settles where the gas's work balances the rotor's losses.
* "recoil": the gun drives itself from its recoil. The barrels (barrel cluster, or a
  revolver's barrel) recoil `recoil_stroke` in the receiver against a spring
  (spring_rate, spring_preload); a helical cam and an overrunning clutch turn the rotor
  `1 / cam_lever` rad per m of that recoil, so the recoiling barrels drive the rotor
  while they move back faster than it turns, and run out free. Started by a starter.

Trigger. The feeder runs from the trigger pull until it has fed the burst (`shots`) or
the belt runs out; then the gun turns on until every station is clear, and the drive
brakes. Times are measured from the first
ignition, so the spin-up comes before 0.

The gun recoils on its mount (or shoulder, or free) under every shot's loads, as in
action.py, with the bolts' cam reactions along the bore.

Approximations: the cam's dwells and strokes are a fixed profile; the bolts move along
the bore only (no lock rotation); a revolver's drum turns steadily instead of indexing
from chamber to chamber; the drive's reaction torque on the gun is not modelled; the
gas cylinder's gas is ideal and keeps its heat; firing is instantaneous as the station
reaches the top.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np

from . import feed as feeding

if TYPE_CHECKING:
    from .config import Gun
    from .results import ShotResult

LAYOUTS = ("gatling", "revolver")
DRIVES = ("electric", "hydraulic", "gas", "recoil")
FEEDS = ("belt", "dual_belt", "linkless")
MAX_BURST = 400
# Cam profile, angles (deg) from the firing position in the rotor's direction. The bolt is locked
# from LOCK_IN before the top to the dwell after it, strokes back to the bottom, dwells open over
# the feed, and rams home.
EXTRACT_END = 180.0
REAR_DWELL = 30.0
LOCK_IN = 30.0
STARTER_LEAD = math.radians(30.0)    # the starter drives on this far past bringing the first round up to fire
FINE_DT, COARSE_DT = 4e-6, 4e-5      # s, steps while a shot's gas acts (or a gas cylinder fills), and otherwise
GAS_WINDOW = 4e-3                    # s after a shot the fine steps last (the port's gas)
OUT_DT = 4e-4                        # s between output samples
MAX_TIME = 10.0                      # s, from the trigger
SPIN_LIMIT = 2.0                     # s the rotor may take to reach its first shot
STOP_SHARE = 0.01                    # the rotor is taken to have stopped below this share of its top speed
SETTLE = 0.3                         # s the mount is followed after the rotor stops, at most
BRAKE = {"electric": 0.35, "hydraulic": 0.8}   # braking torque as a share of the drive's stall (top) torque
ROTOR_BRAKE_TIME = 0.4              # s a self-driven gun's rotor brake takes to stop it from its top speed
HYDRAULIC_KNEE = 0.04               # the flow limit takes the torque away over this share of top speed
STALL_SHARE = 0.03
UNLOCK_PRESSURE_WARNING = 20e6       # Pa
CLUSTER_RESTITUTION = 0.3            # recoil drive: the barrels off their rear stop
AMBIENT = 101325.0
AIR_TEMPERATURE = 300.0
STEEL = 7850.0


def stations(gun: Gun) -> int:
    """Barrels (Gatling) or chambers (revolver): the stations that fire once a turn each."""
    a = gun.action
    return int(a.barrels if a.rotary_layout == "gatling" else a.chambers)


def radius(gun: Gun) -> float:
    """The rotor's axis to the stations' (the bores' or the chambers') axes (m)."""
    a, k = gun.action, stations(gun)
    if a.cluster_radius is not None:
        return a.cluster_radius
    across = (gun.barrel.breech_diameter + 2e-3 if a.rotary_layout == "gatling"
              else gun.case.rim_diameter + 0.35 * gun.case.rim_diameter)
    return across / (2 * math.sin(math.pi / k))


def barrel_mass(gun: Gun) -> float:
    """One barrel (kg): given, or its steel."""
    from .action import barrel_mass as one
    return one(gun)


def drum_mass(gun: Gun) -> float:
    """A revolver's drum (kg): a steel cylinder round its chambers, a case length long, less the chambers."""
    c = gun.case
    outer = radius(gun) + 0.65 * c.rim_diameter
    return STEEL * c.length * math.pi * (outer**2 - stations(gun) * (c.base_diameter / 2) ** 2)


def rotor_inertia(gun: Gun) -> float:
    """The rotor's moment of inertia about its axis (kg m^2), empty: given, or estimated.

    Gatling: the barrels at the cluster radius, with their clamps, rotor and bolt carrier half
    as much again. Revolver: the drum as a solid steel cylinder (less its chambers).
    """
    a = gun.action
    if a.rotor_inertia is not None:
        return a.rotor_inertia
    r = radius(gun)
    if a.rotary_layout == "gatling":
        return 1.5 * stations(gun) * barrel_mass(gun) * r * r
    outer = r + 0.65 * gun.case.rim_diameter
    return 0.5 * drum_mass(gun) * outer * outer


def free_speed(gun: Gun) -> float:
    """The rotor's speed (rad/s) at the drive's rated rate, gun.action.rotary_rate rounds/min."""
    return gun.action.rotary_rate / 60 / stations(gun) * 2 * math.pi


def cam_angles(gun: Gun) -> dict:
    """The cam's legs (rad from the firing position)."""
    dwell = math.radians(gun.action.dwell_angle)
    extract = math.radians(EXTRACT_END)
    rear = extract + math.radians(REAR_DWELL)
    lock = 2 * math.pi - math.radians(LOCK_IN)
    return {"dwell": dwell, "extract": extract, "rear": rear, "lock": lock, "feed": (extract + rear) / 2}


def cam(theta: float, angles: dict, stroke: float) -> tuple[float, float, float]:
    """A bolt's travel back from battery (m) at theta rad from the firing position, and dS/dtheta, d2S/dtheta2."""
    theta %= 2 * math.pi
    a, e, r, l = angles["dwell"], angles["extract"], angles["rear"], angles["lock"]
    if theta < a or theta >= l:
        return 0.0, 0.0, 0.0
    if theta < e:
        span, b, sign = e - a, (theta - a) / (e - a), 1.0
    elif theta < r:
        return stroke, 0.0, 0.0
    else:
        span, b, sign = l - r, (theta - r) / (l - r), -1.0
    two = 2 * math.pi * b
    v = stroke / span * (1 - math.cos(two))
    acc = stroke / span**2 * 2 * math.pi * math.sin(two)
    s = stroke * (b - math.sin(two) / (2 * math.pi))
    return (s, v, acc) if sign > 0 else (stroke - s, -v, -acc)


def eject_angle(angles: dict, stroke: float, eject: float) -> float:
    """Where on the stroke back the case clears the chamber and is thrown out (rad)."""
    lo, hi = angles["dwell"], angles["extract"]
    for _ in range(50):
        mid = 0.5 * (lo + hi)
        if cam(mid, angles, stroke)[0] < eject:
            lo = mid
        else:
            hi = mid
    return hi


def geometry(gun: Gun, stroke: float, eject: float) -> dict:
    """What the 3D view and the sound need of the rotor."""
    a = gun.action
    ang = cam_angles(gun)
    return {"layout": a.rotary_layout, "drive": a.rotary_drive, "stations": stations(gun), "radius": radius(gun),
            "stroke": stroke, "inertia": rotor_inertia(gun), "rate": a.rotary_rate,
            "dwell": ang["dwell"], "extract": ang["extract"], "rear": ang["rear"], "lock": ang["lock"],
            "feed": ang["feed"], "eject": eject_angle(ang, stroke, eject),
            "recoil_stroke": a.recoil_stroke if a.rotary_drive == "recoil" else 0.0,
            "cam_lever": a.cam_lever}


class _Table:
    """A shot's loads as running integrals on a fine grid, so a step can take their mean over itself."""

    def __init__(self, loads, dt: float = 2e-6):
        self.end = float(loads.t[-1])
        self.dt = dt
        n = int(self.end / dt) + 2
        tau = np.arange(n) * dt
        fb = np.interp(tau, loads.t, loads.breech_force, left=0.0, right=0.0)
        fr = np.interp(tau, loads.t, loads.barrel_force, left=0.0, right=0.0)
        self.cb = np.concatenate(([0.0], np.cumsum(fb) * dt))
        self.cr = np.concatenate(([0.0], np.cumsum(fr) * dt))
        self.fb = fb
        self.p = np.interp(tau, loads.t, loads.port_pressure, left=AMBIENT, right=AMBIENT)
        self.T = np.interp(tau, loads.t, loads.port_temperature, left=AIR_TEMPERATURE, right=AIR_TEMPERATURE)
        self.n = n

    def mean(self, t0: float, t1: float) -> tuple[float, float]:
        """Mean breech and barrel force (N) of a shot fired at 0 over [t0, t1]."""
        i0 = min(max(int(round(t0 / self.dt)), 0), self.n)
        i1 = min(max(int(round(t1 / self.dt)), 0), self.n)
        if i1 <= i0:
            return 0.0, 0.0
        span = t1 - t0
        return (self.cb[i1] - self.cb[i0]) / span, (self.cr[i1] - self.cr[i0]) / span

    def port(self, t: float) -> tuple[float, float]:
        i = int(t / self.dt)
        if 0 <= i < self.n:
            return float(self.p[i]), float(self.T[i])
        return AMBIENT, AIR_TEMPERATURE

    def breech(self, t: float) -> float:
        i = int(t / self.dt)
        return float(self.fb[i]) if 0 <= i < self.n else 0.0


def simulate(gun: Gun, shot: ShotResult, shots: int = 1, rounds: int | None = None):
    """A rotary gun's burst: spin-up, the shots, the clearing turn and the spin-down (an action.ActionResult)."""
    from . import devices
    from .action import ActionResult, _exchange, head_area, mount_force, port_position

    loads = shot.loads
    if loads is None or len(loads.t) < 2:
        raise ValueError("this shot has no recorded loads on the gun")
    a, sh, mt = gun.action, gun.shooter, gun.mount
    drive = a.rotary_drive
    shots = int(min(max(shots, 1), MAX_BURST))
    k = stations(gun)
    pitch = 2 * math.pi / k
    r = radius(gun)
    ang = cam_angles(gun)
    c = gun.case
    eject = c.length + 3e-3
    stroke = a.bolt_travel if a.bolt_travel is not None else c.overall_length + 11e-3
    geo = geometry(gun, stroke, eject)
    eject_at, feed_at = geo["eject"], ang["feed"]
    m_round = feeding.round_mass(gun)
    m_case = feeding.case_mass(gun)
    m_bolt = a.bolt_mass
    ram_speed = 2 * stroke / (ang["lock"] - ang["rear"])   # the bolt's top speed ramming, per rad/s of the rotor
    j_rotor = rotor_inertia(gun) + a.drive_mass * r * r
    w_rated = free_speed(gun)

    # The gun body (its recoil x, pitch th), held as action.py holds it.
    gun_mass = a.gun_mass + devices.device_mass(gun)
    recoil_drive = drive == "recoil"
    m_cluster = (stations(gun) * barrel_mass(gun) if a.rotary_layout == "gatling" else barrel_mass(gun)) \
        if recoil_drive else 0.0
    if recoil_drive:
        m_cluster += rotor_inertia(gun) / (r * r) * 0.5 if a.rotary_layout == "gatling" else drum_mass(gun)
        if m_cluster >= gun_mass:
            raise ValueError(f"recoil drive: the recoiling barrels and rotor ({m_cluster:.1f} kg) must be lighter "
                             f"than the gun ({gun_mass:.1f} kg)")
    shoulder = sh.stance in ("shoulder", "hands")
    mounted = sh.stance == "mount"
    m_body = sh.body_mass if shoulder else 0.0
    m_gun = gun_mass - m_cluster + m_body       # what the gun body's equation moves
    k_sh, c_sh = (sh.shoulder_stiffness, sh.shoulder_damping) if shoulder else (0.0, 0.0)
    k_th, c_th = ((sh.hold_stiffness, sh.hold_damping) if shoulder else
                  (mt.elevation_stiffness, mt.elevation_damping) if mounted else (0.0, 0.0))
    arm = a.cg_distance if shoulder or mounted else 0.0
    inertia = gun_mass * (a.radius_of_gyration**2 + arm**2)
    h = a.bore_height

    # The drive.
    if drive == "electric":
        tau_top = 4 * a.motor_power / w_rated          # stall torque
    elif drive == "hydraulic":
        tau_top = a.motor_power / w_rated              # full torque, up to the flow limit
    else:
        tau_top = 0.0
    # The starter drives the rotor until the first round fed has been carried up to the top.
    starter_angle = 2 * math.pi - ang["feed"] + STARTER_LEAD
    tau_start = a.starter_energy / starter_angle if drive in ("gas", "recoil") else 0.0
    tau_fric = a.friction * r

    # Feed.
    fd = gun.feed
    cap = feeding.capacity(gun)
    mag = cap if rounds is None else int(min(max(rounds, 0), cap))
    counts = [mag]
    link = feeding.link_pitch(gun)
    # Work to draw a round in (J): the hanging belt (or chute) lifted a pitch, and the feeder's drag over it.
    def feed_work(n: int) -> float:
        tension = feeding.belt_load(gun, n)[0] if n > 0 else 0.0
        return (tension + a.feed_force) * link

    # The loads, and the gas system.
    table = _Table(loads)
    hd_area = head_area(gun)
    gamma, r_gas = gun.propellant.gamma, gun.propellant.gas_constant
    cv = r_gas / (gamma - 1)
    gas_drive = drive == "gas"
    port_area = math.pi / 4 * a.gas_port_diameter**2
    piston = math.pi / 4 * a.piston_diameter**2
    port_cd = 0.8
    if gas_drive and gun.solver.gas_port_2d:
        port = devices.port_discharge(gun, loads)
        if port is not None:
            port_cd = port["cd"]
    lever = a.cam_lever

    # State.
    t = 0.0
    phi = w = 0.0
    x = v = th = om = 0.0              # gun body: recoil, its speed, pitch, pitch rate
    xc = uc = 0.0                      # recoil drive: the barrels' recoil in the receiver, and its speed
    engaged = False
    state = ["empty"] * k              # each station: "empty", "live" or "case"
    fired_at = [None] * k              # its shot's ignition time, while that shot's gas might still matter
    unlocked = [True] * k
    cylinders = {}                     # gas drive: station -> {"t0", "phi0", "m", "e"}
    shot_times, events, warnings = [], [], []
    fed = 0
    feeding_on = True
    clearing = braking = stalled = False
    stopped = None                     # when the rotor stopped
    unlock_pressure = None
    w_peak = 0.0
    power_peak = 0.0
    first_shot = None
    out = {key: [] for key in ("t", "x", "v", "th", "phi", "w", "force", "shoulder", "gas", "s0", "power", "xc")}
    next_out = 0.0
    gas_p = AMBIENT

    def event(name, detail="", speed=None, shot=None, **extra):
        events.append({"time": t, "name": name, "detail": detail, "shot": len(shot_times) if shot is None else shot,
                       "speed": speed, **extra})

    def angle_of(i: int) -> float:
        return phi + i * pitch

    def j_eff() -> tuple[float, float, list]:
        """J_eff, dJ_eff/dphi / 2, and each station's (s, S', S'') and moving mass."""
        total, half_slope, cams = j_rotor, 0.0, []
        for i in range(k):
            s, d1, d2 = cam(angle_of(i), ang, stroke)
            m = m_bolt + (m_round if state[i] == "live" else m_case if state[i] == "case" else 0.0)
            cams.append((s, d1, d2, m))
            total += m * d1 * d1
            half_slope += m * d1 * d2
            if state[i] != "empty":
                total += (m_round if state[i] == "live" else m_case) * r * r
        return total, half_slope, cams

    event("trigger pulled", {"electric": "the motor starts", "hydraulic": "the drive valve opens",
                             "gas": "the starter fires", "recoil": "the starter fires"}[drive], shot=0)
    while t < MAX_TIME:
        active = [t0 for t0 in shot_times[-12:] if t - t0 < table.end]
        fine = any(t - t0 < GAS_WINDOW for t0 in active) or (gas_drive and cylinders)
        dt = FINE_DT if fine else COARSE_DT
        if w > 0:
            dt = min(dt, 0.02 * pitch / w)      # a station moves at most 1/50 of its spacing in a step

        # Bore forces of every shot still acting (mean over the step), on the gun or the recoiling barrels.
        fb = fr = 0.0
        for t0 in active:
            b, rr = table.mean(t - t0, t + dt - t0)
            fb += b
            fr += rr
        f_bore = fb + fr

        # Drive torque.
        if drive == "electric":
            tau_d = -BRAKE[drive] * tau_top if braking else tau_top * max(1 - w / w_rated, 0.0)
        elif drive == "hydraulic":
            if braking:
                tau_d = -BRAKE[drive] * tau_top
            else:
                ramp = min(t / a.valve_time, 1.0) if a.valve_time > 0 else 1.0
                tau_d = tau_top * ramp * min(max((w_rated - w) / (HYDRAULIC_KNEE * w_rated), 0.0), 1.0)
        elif braking:
            tau_d = -j_rotor * w_peak / ROTOR_BRAKE_TIME    # the rotor brake
        else:
            tau_d = tau_start if phi < starter_angle else 0.0
        if braking and w <= 0:
            tau_d = 0.0
        # Gas cylinders: each pushes its piston, and through the cam the rotor.
        tau_gas = 0.0
        gas_p = AMBIENT
        for i, cyl in list(cylinders.items()):
            travel = lever * (phi - cyl["phi0"])
            if travel >= a.gas_stroke:
                del cylinders[i]
                continue
            vol = a.gas_volume + piston * travel
            p_c = (gamma - 1) * cyl["e"] / vol
            t_c = p_c * vol / (cyl["m"] * r_gas)
            pp, tp = table.port(t - cyl["t0"])
            flow, enthalpy = _exchange(port_area, port_cd, pp, tp, p_c, t_c, gamma, r_gas)
            cyl["m"] = max(cyl["m"] + flow * dt, 1e-12)
            cyl["e"] = max(cyl["e"] + (flow * enthalpy - p_c * piston * lever * w) * dt, 1e-9)
            tau_gas += (p_c - AMBIENT) * piston * lever
            gas_p = max(gas_p, p_c)
        tau_d += tau_gas
        drawing = feeding_on and fed < shots and mag > 0
        tau_load = (tau_fric if w > 0 else 0.0) + a.rotor_damping * w + \
            (feed_work(mag) / pitch if drawing and w > 0 else 0.0)

        jt, half, cams = j_eff()
        # The bolts' cam reactions on the gun (+ rearwards): the cam drives each bolt with m a.
        tau_net = tau_d - tau_load - half * w * w
        if recoil_drive:
            f_spring = a.spring_preload + a.spring_rate * xc
            f_cam = 0.0
            if engaged:
                # Barrels and rotor as one, through the cam: (m_c + J / L^2) u' = F - spring + tau / L.
                acc_c = (f_bore - f_spring + tau_net / lever) / (m_cluster + jt / (lever * lever))
                f_cam = f_bore - f_spring - m_cluster * acc_c
                if f_cam < 0 or uc <= 0:
                    engaged, f_cam = False, 0.0
            if not engaged:
                acc_c = (f_bore - f_spring) / m_cluster
            if not engaged and xc <= 0 and uc <= 0 and acc_c <= 0:
                acc_c, on_gun = 0.0, f_bore     # in battery, bearing on the front stop
            else:
                # The barrels push the receiver through their spring, and the cam's track in it.
                on_gun = f_spring + f_cam
        else:
            on_gun = f_bore
        acc_w = (acc_c / lever) if (recoil_drive and engaged) else tau_net / jt
        if w <= 0 and acc_w < 0 and not engaged:
            acc_w = 0.0
        bolt_force = sum(m * (d2 * w * w + d1 * acc_w) for _, d1, d2, m in cams)
        f_sh = mount_force(mt, x, v) if mounted else -(k_sh * x + c_sh * v)
        axial = on_gun - bolt_force
        acc_r = (axial + f_sh) / m_gun
        v += acc_r * dt
        if mounted and mt.friction:
            v -= math.copysign(min(abs(v), mt.friction * dt / m_gun), v)
        x += v * dt
        alpha = (h * axial - k_th * th - c_th * om) / inertia
        om += alpha * dt
        th += om * dt
        if mounted:
            if x >= mt.stroke and v > 0:
                event("gun hits the recoil stop", f"{v:.2f} m/s", v)
                x, v = mt.stroke, -mt.stop_restitution * v
            if x < 0:
                x, v = 0.0, max(v, 0.0)

        # The rotor (and with the recoil drive, the barrels).
        last_phi = phi
        if recoil_drive:
            uc += acc_c * dt
            xc += uc * dt
            if engaged:
                w = uc / lever
            else:
                w = max(w + acc_w * dt, 0.0)
                if uc > 0 and uc / lever > w:
                    # The clutch bites: barrels and rotor share their momentum through the cam.
                    m_eq = m_cluster + jt / (lever * lever)
                    uc = (m_cluster * uc + jt * w / lever) / m_eq
                    w, engaged = uc / lever, True
            if xc >= a.recoil_stroke and uc > 0:
                if len(shot_times) <= 1:
                    event("barrels hit their rear stop", f"{uc:.2f} m/s", uc, mass=m_cluster,
                          energy=0.5 * m_cluster * uc * uc * (1 - CLUSTER_RESTITUTION**2))
                v += (1 + CLUSTER_RESTITUTION) * uc * m_cluster / m_gun
                xc, uc = a.recoil_stroke, -CLUSTER_RESTITUTION * uc
                engaged = False
            elif xc <= 0 and uc < 0:
                if len(shot_times) <= 1:
                    event("barrels run out into battery", f"{-uc:.2f} m/s", -uc, mass=m_cluster,
                          energy=0.5 * m_cluster * uc * uc)
                v += uc * m_cluster / m_gun
                xc, uc = 0.0, 0.0
        else:
            w = max(w + acc_w * dt, 0.0)
        phi += w * dt
        w_peak = max(w_peak, w)
        t_end = t + dt
        power = abs(tau_d) * w
        if not braking:
            power_peak = max(power_peak, power)

        # Stations passing the feeder, the top and the ejection port.
        for i in range(k):
            before, after = last_phi + i * pitch, phi + i * pitch
            def crossed(at: float) -> bool:
                return math.floor((after - at) / (2 * math.pi)) > math.floor((before - at) / (2 * math.pi))
            if crossed(feed_at) and state[i] == "empty" and feeding_on and fed < shots:
                if mag > 0:
                    # The round is caught from rest by its station: the rotor shares its momentum with it.
                    w *= jt / (jt + m_round * r * r)
                    if recoil_drive and engaged:
                        uc = w * lever
                    state[i] = "live"
                    mag -= 1
                    fed += 1
                    if fed == 1:
                        event("first round fed", f"the rotor at {w / w_rated * 100:.0f} % of its rated speed", shot=0)
                elif feeding_on:
                    event("belt runs out", "nothing to feed")
                    feeding_on = False
            if crossed(ang["lock"]) and state[i] == "live" and not shot_times:
                # The bolt's roller turns into the locking cam, the round chambered (at the ram's top speed).
                event("bolt locks", "", ram_speed * w, shot=1, station=i)
            if crossed(0.0) and state[i] == "live":
                state[i] = "case"
                shot_times.append(t_end)
                fired_at[i] = t_end
                counts.append(mag)
                unlocked[i] = False
                if first_shot is None:
                    first_shot = t_end
                event("fires", f"barrel {i + 1}" if a.rotary_layout == "gatling" else f"chamber {i + 1}", w * r,
                      station=i)
                if gas_drive:
                    m0 = AMBIENT * a.gas_volume / (r_gas * AIR_TEMPERATURE)
                    cylinders[i] = {"t0": t_end, "phi0": phi, "m": m0, "e": m0 * cv * AIR_TEMPERATURE}
            if crossed(ang["dwell"]) and fired_at[i] is not None and not unlocked[i]:
                unlocked[i] = True
                p_unlock = table.breech(t_end - fired_at[i]) / hd_area + AMBIENT
                if unlock_pressure is None or p_unlock > unlock_pressure:
                    unlock_pressure = p_unlock
                if len(shot_times) <= 1:
                    event("bolt unlocks", f"{p_unlock / 1e6:.1f} MPa in the chamber", shot=1, station=i)
            if crossed(eject_at) and state[i] == "case":
                state[i] = "empty"
                fired_at[i] = None
                event("case ejected", f"thrown out at {w * r:.1f} m/s", w * r,
                      shot=len(shot_times) - sum(1 for s in state if s == "case"), station=i)

        if feeding_on and (fed >= shots or mag == 0) and not clearing:
            feeding_on = False
        if not feeding_on and not clearing and all(s != "live" for s in state):
            clearing = True
            event("trigger released", "the feeder stops; the gun turns on to clear its last cases")
        if clearing and not braking and all(s == "empty" for s in state):
            braking = True
            event("drive brakes" if drive in BRAKE else "rotor brake on", "every station clear")
        # A powered drive that can't turn the gun, or a self-driven one that has run down with rounds aboard.
        if not stalled and not braking and t_end > 0.3 and w < STALL_SHARE * max(w_peak, w_rated * 0.2):
            if any(s == "live" for s in state) or (feeding_on and mag > 0):
                stalled = True
                event("the gun stops", "the rotor has run down with rounds in it")
                braking = clearing = True
                feeding_on = False
        if t_end > SPIN_LIMIT and not shot_times:
            stalled = True
        if braking and w < STOP_SHARE * max(w_peak, 1e-9) and not (recoil_drive and xc > 0):
            if stopped is None:
                stopped = t_end
                event("rotor stops")
            if abs(v) < 1e-3 and x <= 1e-4 or not mounted or t_end - stopped > SETTLE:
                break
        if stalled and not shot_times and t_end > SPIN_LIMIT:
            break

        if t_end >= next_out:
            next_out = t_end + OUT_DT
            out["t"].append(t_end)
            out["x"].append(x)
            out["v"].append(v)
            out["th"].append(th)
            out["phi"].append(phi)
            out["w"].append(w)
            out["force"].append(f_bore)
            out["shoulder"].append(-f_sh)
            out["gas"].append(gas_p)
            out["s0"].append(cams[0][0])
            out["power"].append(power)
            out["xc"].append(xc)
        t = t_end

    # Times from the first ignition.
    t_shift = first_shot if first_shot is not None else 0.0
    shot_times = [s - t_shift for s in shot_times]
    for e in events:
        e["time"] -= t_shift
    arr = {key: np.array(val) for key, val in out.items()}
    arr["t"] = arr["t"] - t_shift
    n = len(shot_times)

    # Steady rate: over the second half of the burst, once the drive is up to speed.
    steady = None
    if n >= 4:
        half = shot_times[n // 2:]
        steady = 60 * (len(half) - 1) / (half[-1] - half[0]) if half[-1] > half[0] else None
    status = "fired" if n else "did not fire"
    if stalled:
        status = "the gun stopped" if n else "did not reach the first shot"
        why = {"electric": f"its motor ({a.motor_power / 1e3:.1f} kW) could not turn the gun against its load; "
                           "a stronger motor or a lighter rotor would",
               "hydraulic": f"its hydraulic motor ({a.motor_power / 1e3:.1f} kW) could not turn the gun against "
                            "its load; more pressure (power) or a lighter rotor would",
               "gas": "the gas did not do enough work to keep the rotor turning against its load and the feed; "
                      "a bigger gas port or piston, a longer gas stroke or a stronger starter would",
               "recoil": "the barrels' recoil did not turn the rotor fast enough against its load; a longer "
                         "recoil stroke, a lighter rotor or a stronger starter would"}[drive]
        warnings.append(f"the rotor ran down{f' after {n} shots' if n else ' before the first shot'}: {why}")
    elif n < shots and mag == 0:
        status = "empty"
    if unlock_pressure is not None and unlock_pressure > UNLOCK_PRESSURE_WARNING:
        warnings.append(f"a bolt unlocks with {unlock_pressure / 1e6:.0f} MPa still in its chamber: the gun turns too "
                        "fast for its dwell (a longer dwell angle, or a lower rate)")
    sustained = steady or (60 * (n - 1) / (shot_times[-1] - shot_times[0]) if n > 1 else None)
    if drive in ("gas", "recoil") and sustained and sustained > 1.3 * a.rotary_rate:
        warnings.append(f"the rotor runs away to {sustained:.0f} rounds/min, past its rated "
                        f"{a.rotary_rate:.0f}: a smaller gas port (or a shorter stroke) or more drag would hold it back")
    spin_up = None
    if n and drive in ("electric", "hydraulic"):
        # How long the drive took to bring the rotor to 90 % of the speed it fires at.
        target = 0.9 * (steady / 60 / k * 2 * math.pi if steady else w_rated)
        idx = np.nonzero(arr["w"] >= target)[0]
        spin_up = float(arr["t"][idx[0]] + t_shift) if idx.size else None

    rot = {
        **geo,
        "drive": drive,
        "shots": n,
        "steady_rate": steady,
        "peak_rate": w_peak / pitch * 60,
        "spin_up": spin_up,
        "first_shot": first_shot,
        "peak_power": power_peak,
        "torque": tau_top if drive in ("electric", "hydraulic") else None,
        "unlock_pressure": unlock_pressure,
        "time": arr["t"], "phi": arr["phi"], "speed": arr["w"], "power": arr["power"], "cluster": arr["xc"],
        "motor_rpm": a.motor_rpm, "pinion_teeth": a.pinion_teeth, "rated_speed": w_rated,
        "motor_power": a.motor_power, "starter_energy": a.starter_energy,
        "end": float(arr["t"][-1]) if arr["t"].size else 0.0,
    }
    shoulder_force = arr["shoulder"] if shoulder or mounted else np.zeros_like(arr["t"])
    impulse = loads.impulse
    # A mount: back in battery once the burst is over and the gun has run out again.
    battery_time = battery_speed = None
    if mounted and n:
        home = np.nonzero((arr["t"] > shot_times[-1]) & (arr["x"] <= 1e-4))[0]
        if home.size:
            battery_time = float(arr["t"][home[0]])
            battery_speed = float(max(-arr["v"][max(home[0] - 1, 0)], 0.0))
    result = ActionResult(
        kind="rotary", stance=sh.stance, time=arr["t"], recoil=arr["x"], recoil_velocity=arr["v"], pitch=arr["th"],
        bolt=arr["s0"], bolt_velocity=np.gradient(arr["s0"], arr["t"]) if arr["t"].size > 1 else arr["s0"] * 0,
        force=arr["force"], shoulder_force=shoulder_force, gas_pressure=arr["gas"], hammer=None,
        impulse=impulse, free_recoil_velocity=impulse / gun_mass, free_recoil_energy=impulse**2 / (2 * gun_mass),
        max_recoil=float(arr["x"].max()) if arr["x"].size else 0.0,
        peak_recoil_velocity=float(arr["v"].max()) if arr["v"].size else 0.0,
        peak_shoulder_force=float(shoulder_force.max()) if shoulder_force.size else 0.0,
        max_pitch=float(arr["th"].max()) if arr["th"].size else 0.0,
        bolt_max_travel=stroke, strokes={"eject": eject, "feed": c.overall_length + 3e-3, "stroke": stroke,
                                         "unlock": 0.0, "rotary": geo},
        status=status, gun_mass=gun_mass, events=events, warnings=warnings, shot_times=shot_times,
        cycle_time=None, unlock_pressure=unlock_pressure, gas_peak_pressure=float(arr["gas"].max()) if gas_drive else None,
        port_cd=port_cd if gas_drive else None, port_cd_2d=gas_drive and gun.solver.gas_port_2d,
        lock_time=0.0, feed=None, rounds=counts, rounds_left=mag, chambered=False, held_open=False,
        feed_angle=0.0, capacity=cap, motor_peak_power=power_peak if drive in ("electric", "hydraulic") else None,
        battery_time=battery_time, battery_speed=battery_speed,
        trigger=gun.trigger.type, semi=False,
    )
    result.rotary = rot
    return result


def summary(rot: dict) -> str:
    """One line for ActionResult.summary()."""
    line = f"  rotary ({rot['layout']}, {rot['drive']})"
    line = f"{line:22s} {rot['shots']} shots"
    if rot["steady_rate"]:
        line += f" at {rot['steady_rate']:.0f} rounds/min"
    if rot["spin_up"] is not None:
        line += f", up to speed in {rot['spin_up'] * 1e3:.0f} ms"
    if rot["first_shot"] is not None:
        line += f", first shot {rot['first_shot'] * 1e3:.0f} ms after the trigger"
    if rot["peak_power"] and rot["drive"] in ("electric", "hydraulic"):
        line += f", drive peaking at {rot['peak_power'] / 1e3:.1f} kW"
    return line


def to_json(rot: dict | None, points: int = 4000) -> dict | None:
    """The rotor for the UI: its angle, speed and drive power over time, and its geometry."""
    if rot is None:
        return None
    t = rot["time"]
    idx = np.unique(np.linspace(0, len(t) - 1, min(len(t), points)).astype(int)) if len(t) else np.array([], int)

    def floats(key):
        return [float(f"{v:.6g}") for v in np.asarray(rot[key])[idx]]

    skip = {"time", "phi", "speed", "power", "cluster"}
    out = {k: (float(v) if isinstance(v, (int, float, np.floating)) and not isinstance(v, bool) else v)
           for k, v in rot.items() if k not in skip}
    out.update(time=floats("time"), phi=floats("phi"), speed=floats("speed"), power=floats("power"),
               cluster=floats("cluster"))
    return out
