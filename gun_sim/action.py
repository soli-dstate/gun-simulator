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

* chain: a chain gun. A motor drives a chain round a rectangular track, and
  the bolt carrier rides its master link: across the front of the track the
  bolt dwells locked in battery (the shot is fired there), along one side it
  is drawn back, across the back it dwells open while the feeder (driven off
  the same chain) indexes the next round, and along the other side it rams
  that round home. The bolt's travel is s = S(q) for the chain's position q,
  so the gun, the bolt and the drive are solved together from their kinetic
  energy (Lagrange), T = m_r x'^2/2 + m_bolt (x' + S'(q) q')^2/2 + m_drive q'^2/2,
  with the motor's force falling linearly with the chain's speed. The shot
  does not work the action; while the bolt is locked (S' = 0 in the dwell)
  it pushes only the gun, so a hangfire cannot open the breech under
  pressure until the dwell is over.
* sliding_wedge: a cannon's vertical sliding-block breech, locked while the
  gun recoils on its mount. As the gun runs out again, the opening cam on the
  cradle catches the breech crank over the last `cam_travel` before battery
  and drives the block down (s = drop = bolt_travel (cam_travel - x) /
  cam_travel), against its closing spring and helped by its weight; the gun
  carries the block's inertia through the cam. Arriving in battery, the block
  strikes the extractors, which throw the case (or a combustible case's stub)
  out at `extractor_ratio` times its speed and hold it open for the loader.
  If the run-out is too weak to drive the block all the way, the breech stays
  part shut. With an autoloader, its cycle then rams the next round
  (gun_sim/autoloader.py, ActionResult.autoloader).

* rotary: a Gatling's barrel cluster or a revolver cannon's drum, turned by a motor, its
  own gas or its barrels' recoil, every station firing as it passes the top: its own
  model, gun_sim/rotary.py, which returns the same ActionResult.

* revolver: nothing moves under the shot (it pushes the whole gun). Between
  shots the hammer is cocked, by the trigger (double action) or the
  shooter's thumb (single action), over trigger.pull_time; the hand turns the
  cylinder a chamber on over the middle of its swing (revolver.py) and the
  cylinder stop locks it. The hammer then falls on the round now under it, or
  on a fired case if the cylinder has run dry. The spent cases stay in their
  chambers.

Trigger (config.Trigger). In "auto" a self-loading action fires its burst as
the closing carrier trips the auto sear (below). In "semi" each shot has a
pull of its own: once the action is back in battery with a round chambered,
and trigger.split after the last shot, the shooter pulls again. A hammer the
action has cocked just falls (single action, and double action after its
first shot); a double-action-only hammer, which the action does not leave
cocked, is drawn back by the pull over pull_time first. A striker, part-cocked
by the slide, is cocked the rest of the way and let go. A self-loader with
neither fires LOCK_TIME after the pull.

Striker (trigger.type = "striker"). The striker is a mass on a spring in the
slide: let go from striker_travel back, it hits the primer with the spring's
energy, F0 L + k L^2 / 2, after the time the spring takes to drive it there.
As the slide closes, the trigger bar catches the striker's lug the last
striker_precock of its travel from battery, so the slide compresses the
striker spring against it over that distance.

Hands (shooter.stance = "hands"): as a shoulder, a spring and damper to the
body with the hands and forearms moving with the gun; bore_height is then the
bore over the web of the hand, so a handgun's high bore turns more of its
recoil into muzzle flip.

Mount (shooter.stance = "mount", config.Mount). The gun recoils in a cradle
against a spring, a hydropneumatic recuperator, a hydraulic buffer whose
orifice closes down along the stroke (force = rho A^3 v^2 / (2 (Cd a)^2)),
linear damping and friction, up to a hard stop; the recuperator runs it out
again, the last part cushioned by the counter-recoil buffer, until it rests
against its front stop in battery. The elevation gear holds the cradle's
pitch about the trunnions as the shoulder hold does a rifle's.

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

Hammer (action.hammer). A hammer turns on a pivot in the receiver against its
spring. It rests on the firing pin; once the carrier has come back
`hammer_trip_travel`, the carrier's underside cams it down, turning it in
proportion to the carrier's travel until it is past the sear (by
HAMMER_OVERTRAVEL) after `hammer_cock_travel` more. While they touch, the
hammer is part of the carrier's motion: the carrier carries its inertia
(J (dphi/ds)^2) and feels its spring torque through the cam (dphi/ds times
the torque), plus friction on the hammer's face. If the carrier pulls away
faster than the spring can follow (at the rear stop), the hammer flies free.
Going home, the hammer rides the carrier back up to the sear, which holds it.
In a burst the closing carrier trips the auto sear in its last
`hammer_trip_travel`; the hammer falls on its own spring, first swinging any
rate reducer's inertia with it (the AKM's: an inertial lever that delays the
fall so the carrier has settled before the hammer arrives), and the next shot
fires PRIMER_DELAY after it reaches the firing pin, if it still has the
primer's ignition.strike_energy. If the carrier has bounced back out of battery, the
hammer lands on it instead, and rides it home with too little energy to fire.

Bursts. A self-loading action can fire several shots: each is fired when the
hammer falls on the bolt closing on the one before (without a hammer,
LOCK_TIME after the bolt is back in battery), with everything (the gun's
recoil and pitch, the gas cylinder) carried over, so recoil and muzzle climb
build up through the burst. The gas port's discharge coefficient comes from a
2D solution of the port (devices.py) unless solver.gas_port_2d is off; a
muzzle device's mass is added to the gun.

Friction. `friction` drags on the bolt group whenever it slides (the rails,
and the tilt a gas piston's off-axis push gives the carrier), as well as the
feeding drag and the hammer's.

Feeding (gun_sim/feed.py). The rounds come from a magazine or a belt holding
`rounds` (full unless given) besides the one chambered. A magazine's spring
presses the top round against the bolt, which drags on it, and lifts it once the
bolt is back past it, against gravity and the gun's muzzle-up swing; the bolt
rides over a round that hasn't risen far enough. A belt is drawn across by a cam
on the carrier, through which the carrier feels the hanging belt. Each round is
then driven at the feed angle into the chamber mouth or up the feed ramp
(meeting the ramp costs the bolt the round's deflection), or jams there, which
stops the bolt where the round wedges. On an empty magazine the bolt catch holds
the bolt open (feed.hold_open), or it closes on an empty chamber; either ends a
burst.

Approximations: the bolt and carrier move as one mass (a real carrier runs
free for its unlock travel before it picks up the bolt), except in a delayed
blowback, whose delay ratio is constant (real roller and lever angles change
it a little over the stroke) and whose carrier closes its gap at once when
the head reaches battery; friction is Coulomb and constant; the hammer's cam
is a straight ramp and the sear holds it from the moment it passes it; and
the case leaves the chamber freely. The gas in the cylinder is ideal and
keeps its heat. The shooter's body moves rigidly with the butt, and is
linear. Small angles throughout.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

from . import autoloader as autoloading
from . import feed as feeding
from . import revolver as cylinder
from . import rotary as rotating

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
LOCK_TIME = 0.003         # s from back in battery to the next ignition in a burst, without a hammer
PRIMER_DELAY = 3e-4       # s from the hammer hitting the firing pin to ignition
HAMMER_OVERTRAVEL = 0.15  # the carrier pushes the hammer this fraction of its angle past the sear
QUIET_DT = 1e-4           # s, step while the action rests between a semi-automatic's or revolver's shots
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
# Mounts: a gun on a recoil system is followed until it has run out again (at most MOUNT_DURATION),
# with coarser steps once the first DURATION is over.
MOUNT_DURATION = 3.0      # s
MOUNT_DT = 1e-4           # s
OUT_LONG = 2e-3           # s, output sampling after DURATION
SETTLE_TIME = 0.05        # s the gun rests in battery, its action done, before the simulation stops
RECUPERATOR_N = 1.3       # polytropic exponent of the recuperator's gas
BUFFER_CD = 0.7           # discharge coefficient of the buffer's orifice
G = 9.81
CHAIN_UNLOCK = 5e-3       # m of bolt travel over which a chain gun's bolt turns out of its locks
STALL_SHARE = 0.05        # the chain is taken to have stalled below this share of its free speed
LOCKED = ("bolt", "sliding_wedge")   # the breech is never unlocked by the shot


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
    """Projectile travel from its seat to the gas port (m): where the solvers record the bore gas.
    Without a gas system that is a bore evacuator's nozzles, if there is one."""
    if gun.barrel.evacuator_position and gun.action.type not in GAS_SYSTEMS:
        return gun.barrel.evacuator_position
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


def hammer_torque(a, angle: float) -> float:
    """The hammer spring's torque (N m) with the hammer `angle` rad back from the firing pin."""
    return a.hammer_spring_torque + a.hammer_spring_rate * angle


def hammer_cam(a, travel: float) -> tuple[float, float]:
    """How far (rad) the carrier, `travel` m back, holds the hammer down, and d(angle)/d(travel)."""
    top = math.radians(a.hammer_angle) * (1 + HAMMER_OVERTRAVEL)
    slope = top / a.hammer_cock_travel
    ramp = travel - a.hammer_trip_travel
    if ramp <= 0:
        return 0.0, 0.0
    if ramp >= a.hammer_cock_travel:
        return top, 0.0
    return slope * ramp, slope


def hammer_inertia(a, angle: float, falling: bool) -> float:
    """The hammer's moment of inertia (kg m^2), with a rate reducer's while it drags one."""
    reducer = falling and angle > math.radians(a.hammer_angle - a.rate_reducer_angle)
    return a.hammer_inertia + (a.rate_reducer_inertia if reducer else 0.0)


def hammer_fall(gun: Gun) -> tuple[float, float]:
    """The hammer's fall from the sear to the firing pin, with nothing in its way:
    (time in s, energy it hits the pin with in J)."""
    a = gun.action
    angle, rate, t, dt = math.radians(a.hammer_angle), 0.0, 0.0, 1e-6
    while angle > 0:
        rate -= hammer_torque(a, angle) / hammer_inertia(a, angle, True) * dt
        angle += rate * dt
        t += dt
    return t, 0.5 * a.hammer_inertia * rate * rate


def striker_fall(gun: Gun) -> tuple[float, float]:
    """A striker let go from fully cocked: (time in s to the primer, energy it hits it with in J)."""
    a = gun.action
    x, rate, t, dt = a.striker_travel, 0.0, 0.0, 1e-7
    while x > 0:
        rate -= (a.striker_spring_preload + a.striker_spring_rate * x) / a.striker_mass * dt
        x += rate * dt
        t += dt
    return t, 0.5 * a.striker_mass * rate * rate


def striker_force(a, compressed: float) -> float:
    """The striker spring's force (N) with the striker held `compressed` m back from forward."""
    return a.striker_spring_preload + a.striker_spring_rate * compressed


def buffer_orifice(m, x: float, v: float) -> float:
    """Open area (m^2) of the recoil buffer's orifice, the gun x m back moving at v (+ rearwards).

    Recoiling, a throttling rod closes it from buffer_orifice to buffer_orifice_end along the
    stroke; running out, the oil returns through counter_orifice, which the counter-recoil
    buffer's spear closes to a tenth over the last counter_buffer before battery.
    """
    if v > 0:
        end = m.buffer_orifice_end if m.buffer_orifice_end is not None else m.buffer_orifice
        return m.buffer_orifice + (end - m.buffer_orifice) * min(max(x / m.stroke, 0.0), 1.0)
    area = m.counter_orifice if m.counter_orifice is not None else m.buffer_orifice
    if m.counter_buffer > 0 and x < m.counter_buffer:
        area *= max(0.1, x / m.counter_buffer)
    return area


def mount_force(m, x: float, v: float) -> float:
    """The recoil system's push on the gun (N, + rearwards, so negative as it holds the gun back), friction aside."""
    f = -(m.spring_preload + m.spring_rate * x) - m.damping * v
    if m.recuperator_pressure > 0:
        gas = m.recuperator_volume - m.recuperator_area * min(max(x, 0.0), m.stroke)
        f -= m.recuperator_pressure * m.recuperator_area * (m.recuperator_volume / gas) ** RECUPERATOR_N
    if m.buffer_area > 0 and v:
        # Oil driven through the orifice at Q = A v: the pressure drop rho (Q / (Cd a))^2 / 2 on the piston.
        k = m.oil_density * m.buffer_area**3 / (2 * (BUFFER_CD * buffer_orifice(m, x, v)) ** 2)
        f -= math.copysign(k * v * v, v)
    return f


def chain_track(gun: Gun, stroke: float) -> dict:
    """A chain gun's track: width and corner radius (m), and its legs from the firing point, in the
    middle of the front dwell. Each leg is (name, length); the bolt's travel along it is track_at's."""
    a = gun.action
    width = a.chain_width if a.chain_width is not None else 0.35 * gun.case.overall_length
    radius = a.sprocket_radius if a.sprocket_radius is not None else width / 4
    radius = min(radius, 0.4 * width, 0.4 * stroke)
    dwell, side, arc = width - 2 * radius, stroke - 2 * radius, math.pi * radius / 2
    legs = [("front", dwell / 2), ("out", arc), ("back", side), ("in_rear", arc), ("rear", dwell),
            ("out_rear", arc), ("forward", side), ("in", arc), ("front", dwell / 2)]
    starts, q = {}, 0.0
    for name, length in legs:
        starts.setdefault(name, q)
        q += length
    return {"width": width, "radius": radius, "stroke": stroke, "perimeter": q, "legs": legs,
            "rear_start": starts["rear"], "rear_length": dwell}


def track_at(track: dict, q: float) -> tuple[float, float, float, str]:
    """The bolt on the chain at q m round the track from the firing point: (travel s, dS/dq, d2S/dq2, leg)."""
    r, L = track["radius"], track["stroke"]
    q %= track["perimeter"]
    for name, length in track["legs"]:
        if q <= length:
            break
        q -= length
    th = q / r if r > 0 else 0.0
    if name == "front":
        return 0.0, 0.0, 0.0, name
    if name == "out":
        return r * (1 - math.cos(th)), math.sin(th), math.cos(th) / r, name
    if name == "back":
        return r + q, 1.0, 0.0, name
    if name == "in_rear":
        return L - r + r * math.sin(th), math.cos(th), -math.sin(th) / r, name
    if name == "rear":
        return L, 0.0, 0.0, name
    if name == "out_rear":
        return L - r * (1 - math.cos(th)), -math.sin(th), -math.cos(th) / r, name
    if name == "forward":
        return L - r - q, -1.0, 0.0, name
    return r - r * math.sin(th), -math.cos(th), math.sin(th) / r, name


def strokes(gun: Gun) -> dict:
    """Bolt travel (m) at which things happen.

    For a delayed blowback the bolt travel is the bolt head's (the bolt face),
    and "unlock" is how far the head has come back when the carrier has moved
    unlock_travel; "carrier_unlock" is that carrier travel.
    """
    a, c = gun.action, gun.case
    eject = c.length + 3e-3          # the case is clear of the chamber and hits the ejector
    feed = c.overall_length + 3e-3   # the bolt face is behind the next round
    if a.type == "rotary":
        stroke = a.bolt_travel if a.bolt_travel is not None else feed + 8e-3
        return {"eject": eject, "feed": feed, "stroke": stroke, "unlock": 0.0,
                "rotary": rotating.geometry(gun, stroke, eject)}
    if a.type == "sliding_wedge":
        # The block drops far enough to clear the rim, with a little to spare.
        stroke = a.bolt_travel if a.bolt_travel is not None else 1.05 * c.rim_diameter + 5e-3
    elif a.type == "revolver":
        stroke = 0.0                 # no bolt: the cylinder turns instead
    else:
        stroke = a.bolt_travel if a.bolt_travel is not None else feed + 8e-3
    defaults = {"gas": 6e-3, "direct_impingement": 7e-3, "short_recoil": 3e-3, "chain": CHAIN_UNLOCK,
                **{k: v[1] for k, v in DELAYED.items()}}
    unlock = a.unlock_travel if a.unlock_travel is not None else defaults.get(a.type, 0.0)
    out = {"eject": eject, "feed": feed, "stroke": stroke, "unlock": min(unlock, stroke)}
    if a.type == "chain":
        track = chain_track(gun, stroke)
        out["chain"] = {k: track[k] for k in ("width", "radius", "perimeter", "rear_start", "rear_length")}
    if a.type == "revolver":
        out["cylinder"] = {"chambers": feeding.chambers(gun), "radius": cylinder.cylinder_radius(gun),
                           "outer_radius": cylinder.cylinder_outer_radius(gun), "length": cylinder.cylinder_length(gun),
                           "gap": gun.barrel.cylinder_gap, "index": [cylinder.INDEX_START, cylinder.INDEX_END]}
    if gun.trigger.type == "striker":
        out["striker"] = {"travel": a.striker_travel, "precock": a.striker_precock}
    if a.type in DELAYED:
        out["carrier_unlock"] = unlock
        out["unlock"] = min(unlock / delay(gun)[0], stroke)
    if a.hammer and a.type not in (*LOCKED, "chain", "revolver"):
        # Carrier travel to cock the hammer (to the bolt's, for a delayed blowback).
        cock = a.hammer_trip_travel + a.hammer_cock_travel / (1 + HAMMER_OVERTRAVEL)
        out["hammer"] = cock / delay(gun)[0] if a.type in DELAYED and cock < unlock else (
            cock - (delay(gun)[0] - 1) * out["unlock"] if a.type in DELAYED else cock)
    if feeding.belt(gun) and a.type != "chain":
        out["belt_cam"] = list(feeding.belt_cam(gun, stroke))
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
    hammer: np.ndarray | None     # rad the hammer is back from the firing pin (None: no hammer)
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
    lock_time: float = LOCK_TIME          # s from tripping the hammer (or back in battery) to ignition
    hammer_energy: float | None = None    # J the hammer hits the firing pin with, falling freely
    # Feeding: magazine lift (share of the way up) or the belt's draw this cycle (share of a link).
    feed: np.ndarray | None = None
    rounds: list = field(default_factory=list)  # in the magazine or belt at each shot's ignition
    rounds_left: int = 0                  # in the magazine or belt at the end
    chambered: bool = False               # a live round in the chamber at the end
    held_open: bool = False               # the bolt catch holds the bolt open on the empty magazine
    jam: dict | None = None               # feed.check() of the round that jammed, with "shot"
    feed_angle: float = 0.0               # rad, nose towards the bore
    capacity: int = 0
    # A mount's recoil system (stance "mount"): when the gun was back in battery after the first
    # shot, how fast it arrived there, and if it struck the hard stop, how fast.
    battery_time: float | None = None     # s from ignition
    battery_speed: float | None = None    # m/s
    stop_speed: float | None = None       # m/s
    # Chain gun: the chain's position round its track (m from the firing point, counting on past a
    # lap), and the motor's peak output.
    drive: np.ndarray | None = None
    motor_peak_power: float | None = None  # W
    # Sliding wedge: when the breech was open (s from ignition) and how fast the case left it.
    open_time: float | None = None
    case_speed: float | None = None       # m/s
    # Revolver: chambers the cylinder has turned (counting on past a turn), how fast it struck the stop
    # and with what energy (the latest lock-up).
    cylinder: np.ndarray | None = None
    cylinder_lock_speed: float | None = None   # rad/s
    cylinder_lock_energy: float | None = None  # J
    # Trigger: its type, the work of the first pull and of the rest (J), and a striker's strike.
    trigger: str = "single_action"
    trigger_work: float | None = None
    follow_up_work: float | None = None
    striker_energy: float | None = None   # J it hits the primer with
    strike_energy: float = 0.15           # J the primer needs
    semi: bool = False                    # each shot has a pull of its own (trigger.mode "semi", or a revolver)
    autoloader: dict | None = None        # a tank gun's autoloader's cycle after the shot (gun_sim/autoloader.py)
    rotary: dict | None = None            # a rotary gun's rotor over the burst (gun_sim/rotary.py)

    @property
    def shots(self) -> int:
        return len(self.shot_times)

    @property
    def cyclic_rate(self) -> float | None:
        """Rounds per minute: from the burst, or from one cycle plus the lock time (an automatic's)."""
        if len(self.shot_times) > 1:
            return 60 * (len(self.shot_times) - 1) / (self.shot_times[-1] - self.shot_times[0])
        return 60 / (self.cycle_time + self.lock_time) if self.cycle_time and not self.semi else None

    def summary(self) -> str:
        lines = [
            f"  recoil impulse       {self.impulse:9.2f} N s; free recoil {self.free_recoil_velocity:.2f} m/s, "
            f"{self.free_recoil_energy:.1f} J",
            f"  with the shooter     {self.max_recoil * 1e3:9.1f} mm back at up to {self.peak_recoil_velocity:.2f} m/s, "
            f"muzzle rise {math.degrees(self.max_pitch):.2f} deg, peak shoulder force {self.peak_shoulder_force:.0f} N"
            if self.stance == "shoulder" else
            f"  in the hands         {self.max_recoil * 1e3:9.1f} mm back at up to {self.peak_recoil_velocity:.2f} m/s, "
            f"muzzle flip {math.degrees(self.max_pitch):.2f} deg, peak force on the hands {self.peak_shoulder_force:.0f} N"
            if self.stance == "hands" else
            f"  on the mount         {self.max_recoil * 1e3:9.1f} mm of recoil at up to {self.peak_recoil_velocity:.2f} m/s, "
            f"peak force {self.peak_shoulder_force / 1e3:.1f} kN, jump {self.max_pitch * 1e3:.2f} mrad, "
            + (f"back in battery after {self.battery_time * 1e3:.0f} ms" if self.battery_time is not None
               else "not back in battery")
            if self.stance == "mount" else
            f"  free recoil          {self.max_recoil * 1e3:9.1f} mm in {self.time[-1] * 1e3:.0f} ms, "
            f"muzzle rise {math.degrees(self.max_pitch):.2f} deg",
        ]
        if self.kind == "sliding_wedge":
            line = f"  sliding wedge        {self.status}"
            if self.open_time is not None:
                line += f" {self.open_time * 1e3:.0f} ms after the shot"
            if self.case_speed is not None:
                line += f", the case thrown out at {self.case_speed:.1f} m/s"
            lines.append(line)
            if self.autoloader is not None:
                lines.append(autoloading.summary(self.autoloader))
        elif self.kind == "rotary":
            lines.append(rotating.summary(self.rotary) + f"; {self.status}")
            lines.append(f"  feed                 {self.rounds[0]:9d} of {self.capacity} rounds in, {self.rounds_left} left")
        elif self.kind == "revolver":
            line = f"  revolver             {self.status}, {self.shots} shot{'s' if self.shots > 1 else ''}"
            if self.cyclic_rate and self.shots > 1:
                line += f" ({self.cyclic_rate:.0f} rounds/min)"
            if self.cylinder_lock_speed is not None:
                line += (f"; the cylinder turns onto its stop at {self.cylinder_lock_speed:.0f} rad/s "
                         f"({self.cylinder_lock_energy * 1e3:.1f} mJ)")
            lines.append(line)
            lines.append(f"  cylinder             {self.rounds[0] + 1:9d} of {self.capacity + 1} chambers loaded, "
                         f"{self.rounds_left} live left to come")
        elif self.kind != "bolt":
            line = f"  {self.kind.replace('_', ' ') + ' action':20s} {self.status}"
            if self.shots > 1:
                line += f", {self.shots} shots"
            elif self.cycle_time:
                line += f" in {self.cycle_time * 1e3:.1f} ms"
            if self.cyclic_rate:
                line += f" ({self.cyclic_rate:.0f} rounds/min)"
            if self.rear_speed is not None:
                line += f", bolt at {self.rear_speed:.1f} m/s into the rear stop"
            if self.motor_peak_power is not None:
                line += f", motor peaking at {self.motor_peak_power:.0f} W"
            lines.append(line)
            if self.port_cd is not None:
                lines.append(f"  gas port Cd          {self.port_cd:9.2f}" + (" (2D)" if self.port_cd_2d else ""))
            if self.rounds:
                lines.append(f"  feed                 {self.rounds[0]:9d} of {self.capacity} rounds in, {self.rounds_left} left; "
                             f"fed at {math.degrees(abs(self.feed_angle)):.1f}°")
        if self.hammer_energy is not None and self.kind != "bolt":
            lines.append(f"  hammer               {self.lock_time * 1e3:9.1f} ms from the sear to ignition, "
                         f"hits the firing pin with {self.hammer_energy:.2f} J")
        if self.striker_energy is not None:
            lines.append(f"  striker              {self.lock_time * 1e3:9.1f} ms from release to ignition, "
                         f"hits the primer with {self.striker_energy:.3f} J (it needs {self.strike_energy:.3f} J)")
        if self.trigger_work is not None:
            line = f"  trigger              {self.trigger.replace('_', ' ')}, first pull {self.trigger_work * 1e3:.0f} mJ"
            if self.follow_up_work is not None and self.follow_up_work != self.trigger_work:
                line += f", then {self.follow_up_work * 1e3:.0f} mJ"
            lines.append(line)
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


def simulate(gun: Gun, shot: ShotResult, shots: int = 1, rounds: int | None = None) -> ActionResult:
    """Recoil of the gun and the cycle of its action, from a shot's loads.

    shots > 1 fires a burst (self-loading actions only): each shot is fired
    when the hammer the closing bolt trips reaches the firing pin (without a
    hammer, LOCK_TIME after the bolt is back in battery; a chain gun, as its
    master link reaches the firing point again), with the gun's motion
    carried over, so recoil and muzzle climb build up. With trigger.mode
    "semi" (and always for a revolver) each shot is a pull of its own instead,
    trigger.split after the last once the action is ready. The burst stops
    early if a cycle fails or the magazine (or cylinder) runs dry. A bolt or a
    sliding wedge fires one.

    rounds: in the magazine (or belt) besides the chambered one; None = full.
    """
    from . import devices
    if gun.action.type == "rotary":
        return rotating.simulate(gun, shot, shots, rounds)
    loads = shot.loads
    if loads is None or len(loads.t) < 2:
        raise ValueError("this shot has no recorded loads on the gun")
    a, sh = gun.action, gun.shooter
    kind = a.type
    shots = requested = 1 if kind in LOCKED else int(min(max(shots, 1), MAX_BURST))
    geo = strokes(gun)
    stroke, unlock, eject_at, feed_at = geo["stroke"], geo["unlock"], geo["eject"], geo["feed"]
    m_bolt = a.bolt_mass
    m_bar = barrel_mass(gun) if kind == "short_recoil" else 0.0
    gun_mass = a.gun_mass + devices.device_mass(gun)
    if m_bolt + m_bar >= gun_mass:
        raise ValueError(f"short recoil: the slide and barrel ({(m_bolt + m_bar):.2f} kg) "
                         f"must be lighter than the gun ({gun_mass:.2f} kg)")
    shoulder = sh.stance in ("shoulder", "hands")
    mounted = sh.stance == "mount"
    mt = gun.mount
    m_body = sh.body_mass if shoulder else 0.0
    k_sh, c_sh = (sh.shoulder_stiffness, sh.shoulder_damping) if shoulder else (0.0, 0.0)
    if shoulder:
        k_th, c_th = sh.hold_stiffness, sh.hold_damping
    elif mounted:
        k_th, c_th = mt.elevation_stiffness, mt.elevation_damping
    else:
        k_th = c_th = 0.0
    arm = a.cg_distance if shoulder or mounted else 0.0
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
    follow = MOUNT_DURATION if mounted else DURATION

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
    cyc = {}                  # this shot's cycle: ejected, can_feed, feeding, battery, s_max, cocked
    next_shot = None
    out = {k: [] for k in ("t", "x", "v", "th", "s", "u", "force", "shoulder", "gas", "hammer", "feed", "q", "cyl")}
    next_out = 0.0
    # Hammer: angle back from the firing pin and its rate; "down" (on the pin, or riding the
    # carrier short of the sear), "cocked" (on the sear, or held past it by the carrier) or "falling".
    # A revolver's hammer is cocked by the trigger or the thumb, "cocking" over the pull.
    revolving = kind == "revolver"
    hammer = (a.hammer and kind not in (*LOCKED, "chain")) or revolving
    ph = om = 0.0
    hammer_state = "down"
    sear = math.radians(a.hammer_angle)
    rub_arm = math.radians(a.hammer_angle) * (1 + HAMMER_OVERTRAVEL) / a.hammer_cock_travel  # 1 / hammer length
    rel = 0.0
    on_carrier = False
    light_strike = None
    strike = gun.ignition.strike_energy

    # Trigger: each shot of a semi-automatic (or revolver) has a pull of its own, `split` after the last.
    tr = gun.trigger
    semi = revolving or tr.mode == "semi"
    double = tr.type in ("double_action", "double_action_only")
    cock_from = None          # when the pull (or the thumb) started drawing the hammer back
    striker = tr.type == "striker" and kind not in (*LOCKED, "chain", "revolver")
    striker_time, striker_energy = striker_fall(gun) if striker else (0.0, None)
    catch = a.striker_precock * a.striker_travel   # slide travel from battery over which it cocks the striker
    # Revolver: chambers turned, whether the hand has finished this turn, whether a live round is under the hammer.
    turned, index_from, indexed, live, dry = 0.0, 0, True, True, False
    lock_speed = lock_energy = None
    n_chambers = feeding.chambers(gun) if revolving else 0

    # Feeding: rounds left, the top round's rise once the bolt is past it (m, m/s), the belt's draw.
    fd = gun.feed
    belted = feeding.belt(gun)
    by_hand = feeding.hand(gun) or feeding.autoloader(gun)   # nothing in the gun feeds it
    loose = by_hand or revolving     # no magazine spring presses a round on the bolt
    cap = feeding.capacity(gun)
    mag = cap if rounds is None else int(min(max(rounds, 0), cap))
    counts = [mag]
    fgeo = feeding.geometry(gun)
    present = fgeo["present"]
    m_round = feeding.round_mass(gun)
    lift = lift_v = 0.0
    released = False          # the bolt is back past the top round: the spring may lift it
    belt_adv = 0.0            # share of a link the belt has been drawn this cycle
    on_cam = False
    cam0, cam1 = geo.get("belt_cam", (0.0, 0.0))
    cam_ratio = feeding.link_pitch(gun) / (cam1 - cam0) if belted and "belt_cam" in geo else 0.0
    frozen = False            # the bolt is stopped: held open, or a round has jammed
    held_open = False
    jam = None
    jam_at = None             # bolt travel at which the round being fed wedges
    alpha = 0.0               # the gun's pitch acceleration (rad/s^2)

    # Chain gun: the chain's position q (m round the track from the firing point) and speed.
    chain = kind == "chain"
    if chain:
        track = chain_track(gun, stroke)
        perimeter = track["perimeter"]
        v_free = perimeter * a.chain_rate / 60
        f_stall = 4 * a.motor_power / v_free
        feed_ratio = feeding.link_pitch(gun) / max(track["rear_length"], 1e-6)   # belt per chain, in the rear dwell
        q, qd, laps, running, stalled = 0.0, v_free, 1, True, False
        motor_peak, chain_cycle, leg = 0.0, None, "front"
    # Sliding wedge: the block's drop and speed, and where it is in opening.
    wedge = kind == "sliding_wedge"
    bs = bu = 0.0
    block = "shut"            # shut, cam (the cam drives it), free (on its way down), open, reshut
    recoiled = False
    cam_gear = stroke / a.cam_travel if wedge else 0.0
    open_time = case_speed = None
    # Mount: when the gun is back in battery, and whether it hit the stop.
    battery_time = battery_speed = stop_speed = None
    settled_at = None

    def event(t, name, detail="", speed=None, **extra):
        events.append({"time": t, "name": name, "detail": detail, "shot": len(shot_times), "speed": speed, **extra})

    def new_cycle():
        cyc.update(ejected=False, can_feed=False, feeding=False, battery=None, s_max=0.0, cocked=False,
                   empty=False, misfeed=None, back=False, peaked=False, home=False, past_catch=False)

    def release_striker(t_rel):
        """Let the cocked striker go: the round fires when it reaches the primer, if it hits hard enough."""
        nonlocal next_shot, light_strike, shots
        event(t_rel, "striker released", f"{striker_energy:.3f} J at the primer")
        if striker_energy >= strike:
            next_shot = t_rel + striker_time + PRIMER_DELAY
        else:
            event(t_rel + striker_time, "light strike", f"{striker_energy:.3f} J")
            light_strike = light_strike or (len(shot_times) + 1, striker_energy)
            shots = len(shot_times)

    def stop_bolt():
        # The bolt stops dead against whatever holds it (this step's share and m_r); the gun takes its momentum.
        nonlocal u, v, w
        dv = u * share
        v += dv
        w += h * m_r * dv / inertia
        u = 0.0

    def masses():
        m_g = m_bolt + (m_bar if carry else 0.0)
        return m_g, gun_mass - m_g + m_body

    def feed_round(t_end):
        """The bolt, coming forward past the next round, strips it, misses it, or finds none."""
        nonlocal mag, lift, lift_v, belt_adv, released, on_cam, jam, jam_at, u, frozen, held_open
        if mag == 0:
            cyc["empty"] = True
            if not belted and fd.hold_open:
                # The follower has lifted the bolt catch into the bolt's way.
                speed = -u
                stop_bolt()
                frozen = held_open = True
                event(t_end, "bolt held open", "on the empty magazine", speed)
            else:
                event(t_end, "belt runs out" if belted else "magazine empty", "nothing to feed")
        elif belted and belt_adv < 0.999:
            where = ("the feeder drew it only {:.0f} % of a link in the rear dwell" if chain else
                     "the feed cam drew the belt only {:.0f} % of a link; the carrier has to come back "
                     f"{cam1 * 1e3:.0f} mm to draw it all").format(belt_adv * 100)
            cyc["misfeed"] = where
            event(t_end, "misses the next round", cyc["misfeed"])
        elif not belted and lift < feeding.CATCH * present:
            cyc["misfeed"] = (f"the bolt rode over the next round: the magazine spring had lifted it "
                              f"{lift * 1e3:.1f} of the {present * 1e3:.1f} mm it needed. A stronger spring "
                              f"(or a slower cycle) would let it rise in time")
            event(t_end, "bolt rides over the next round", cyc["misfeed"])
        else:
            verdict = feeding.check(fgeo, lift / present if present else 1.0, feed_at)
            mag -= 1
            cyc["feeding"] = True
            lift = lift_v = belt_adv = 0.0
            released = on_cam = False
            event(t_end, "strips the next round", f"{mag} left", rounds=mag, angle=verdict["angle"])
            if verdict["jam"]:
                jam = {**verdict, "shot": len(shot_times)}
                jam_at = max(s - verdict["travel"], 1e-3)
            elif verdict["incidence"] is not None:
                # The ramp turns the round's nose up, at the bolt's expense.
                u *= m_g / (m_g + m_round * math.tan(min(verdict["incidence"], 1.2)) ** 2)

    new_cycle()
    event(0.0, "fires")
    t = 0.0
    end = follow
    while t < end:
        since = t - shot_times[-1]
        fast = since < fast_for
        # Between a semi-automatic's (or revolver's) shots, with the action at rest, coarser steps do.
        quiet = (semi and not mounted and not chain and since > 2 * FAST_UNTIL and s <= 0 and u == 0
                 and hammer_state != "falling" and next_shot is None)
        dt = (FAST_DT if fast else QUIET_DT if quiet else SLOW_DT if since < DURATION or not mounted
              else MOUNT_DT)
        fb, fr, pp, tp = table.at(shot_times, t + 0.5 * dt)
        m_g, m_r = masses()
        f_sh = mount_force(mt, x, v) if mounted else -(k_sh * x + c_sh * v)
        f_piston = 0.0
        if chain:
            # Gun (x) and chain (q) from T = m_r x'^2/2 + m_bolt (x' + S' q')^2/2 + m_drive q'^2/2. The motor
            # drives the chain against the bolt's friction, the ramming and, in the rear dwell, the belt.
            s_q, ds, dds, leg = track_at(track, q)
            if running:
                f_motor = f_stall * (1 - qd / v_free)
                motor_peak = max(motor_peak, f_motor * qd)
                m_drive, f_q = a.drive_mass, f_motor
                if qd:
                    f_q -= a.friction * abs(ds) * math.copysign(1.0, qd)
                if leg == "rear" and on_cam:
                    tension, m_belt = feeding.belt_load(gun, mag)
                    f_q -= tension * feed_ratio
                    m_drive += m_belt * feed_ratio**2
                if cyc["feeding"] and ds < 0 and s_q < feed_at:
                    f_q -= a.feed_force * abs(ds)
                if unlocked:
                    f_q += fb * ds        # pressure left in the chamber pushes the opening bolt
                m11, m12, m22 = m_r + m_bolt, m_bolt * ds, m_bolt * ds * ds + m_drive
                b1 = fb + fr + f_sh - m_bolt * dds * qd * qd
                b2 = f_q - m_bolt * ds * dds * qd * qd
                det = m11 * m22 - m12 * m12
                acc_r, acc_q = (b1 * m22 - m12 * b2) / det, (m11 * b2 - m12 * b1) / det
                axial = m_r * acc_r - f_sh
            else:
                acc_r, acc_q = (fb + fr + f_sh) / (m_r + m_bolt), 0.0
                axial = fb + fr
            held = not running
        else:
            # Bore forces on the bolt group and on the gun body.
            if kind in LOCKED or revolving:
                g_ext, r_ext = 0.0, fb + fr
            elif kind == "short_recoil":
                g_ext, r_ext = (fb + fr, 0.0) if carry else (fb, fr)
            elif unlocked:
                g_ext, r_ext = fb, fr
            else:
                g_ext, r_ext = 0.0, fb + fr

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
            gear = ratio if delayed else 1.0      # carrier speed over bolt speed
            slide = math.copysign(1.0, u) if u else 0.0
            f_spring = a.spring_preload + a.spring_rate * carrier + a.friction * slide
            if hammer:
                cam, slope = hammer_cam(a, carrier)
                if ph <= cam + 1e-9:
                    # The carrier holds the hammer down: its spring through the cam and its inertia
                    # (from the last step's acceleration), unless the carrier is pulling away from it.
                    torque = hammer_torque(a, ph)
                    f_spring += max(0.0, slope * (torque + a.hammer_inertia * slope * gear * rel))
                    f_spring += a.hammer_friction * torque * rub_arm * slide
            if striker and cyc["past_catch"] and carrier < catch:
                # The trigger bar holds the striker's lug while the slide closes on, compressing its spring.
                f_spring -= striker_force(a, catch - carrier)
            if kind not in LOCKED and not revolving and not frozen:
                if belted:
                    # The feed cam: the carrier draws the belt across, lifting the hanging belt.
                    if u > 0 and cam0 <= carrier < cam1 and belt_adv < 1 and mag > 0:
                        tension, m_belt = feeding.belt_load(gun, mag)
                        r = cam_ratio * gear
                        f_spring += cam_ratio * tension + m_belt * cam_ratio * r * rel
                elif mag > 0 and s < feed_at and not loose:
                    # The top round pressed against the bolt's underside by the magazine spring.
                    f_spring += fd.friction * feeding.spring(gun, mag) * slide
            f_int = f_piston - f_spring
            if cyc["feeding"] and u < 0 and s < feed_at:
                f_int += a.feed_force
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
            held = kind in LOCKED or revolving or frozen or (s <= 0 and u <= 0 and rel <= 0)
            if held:  # the bolt is shut (or stuck open) and stays there: one body
                m_all, f_all = m_g + m_r, g_ext + r_ext + f_sh
                if wedge and block == "cam":
                    # The opening cam drives the block down through the crank: the gun carries its
                    # inertia and its closing spring and friction, less its weight.
                    f_all += cam_gear * (a.spring_preload + a.spring_rate * bs + a.friction - m_bolt * G)
                    m_all += m_bolt * cam_gear**2
                acc_r = f_all / m_all
                axial = g_ext + r_ext
                if not frozen:
                    s = 0.0
                u = rel = 0.0
            else:
                axial = m_r * acc_r - f_sh   # what acts on the gun body (the shooter's share aside)
        v += acc_r * dt
        if mounted and mt.friction:
            # The cradle's slides and seals: Coulomb friction, which holds the gun once it has stopped.
            m_eff = m_g + m_r if held else m_r
            v -= math.copysign(min(abs(v), mt.friction * dt / m_eff), v)
        x += v * dt
        alpha = (h * axial - k_th * th - c_th * w) / inertia
        w += alpha * dt
        th += w * dt
        t_end = t + dt

        if wedge:
            if x > a.cam_travel:
                recoiled = True
            if block == "shut" and recoiled and v < 0 and x < a.cam_travel:
                # The cam picks up the crank: the gun shares its momentum with the block.
                m_all = m_g + m_r
                speed = -v
                v *= m_all / (m_all + m_bolt * cam_gear**2)
                block = "cam"
                event(t_end, "the opening cam turns the crank", f"the gun running out at {speed:.2f} m/s", speed)
            if block == "cam":
                if x >= a.cam_travel:
                    block, bs, bu = "shut", 0.0, 0.0   # pushed back off the cam: the spring shuts the block
                else:
                    bs = min(max(stroke * (a.cam_travel - x) / a.cam_travel, 0.0), stroke)
                    bu = -cam_gear * v
                    if x <= 0:
                        block = "free"
            elif block == "free":
                load = a.spring_preload + a.spring_rate * bs + math.copysign(a.friction, bu)
                bu += (G - load / m_bolt) * dt
                bs += bu * dt
                if bs >= stroke and bu > 0:
                    case_speed = a.extractor_ratio * bu
                    open_time = t_end
                    event(t_end, "block strikes the extractors", f"{bu:.2f} m/s", bu)
                    event(t_end, "case ejected", f"the extractors throw it out at {case_speed:.1f} m/s", case_speed)
                    event(t_end, "breech held open", "on the extractors, for the loader")
                    block, bs, bu = "open", stroke, 0.0
                elif bs <= 0 and bu <= 0:
                    block, bs, bu = "reshut", 0.0, 0.0
                    event(t_end, "the block springs shut again", "it never reached the extractors")

        if mounted:
            if x >= mt.stroke and v > 0:
                stop_speed = stop_speed or v
                event(t_end, "gun hits the recoil stop", f"{v:.2f} m/s", v)
                x, v = mt.stroke, -mt.stop_restitution * v
            if x > 1e-3:
                cyc["back"] = True
            if cyc["back"] and not cyc["peaked"] and v <= 0:
                cyc["peaked"] = True
                event(t_end, "gun at full recoil", f"{x * 1e3:.0f} mm back")
            if x < 0:
                x = 0.0
                if v < 0:
                    if cyc["back"] and not cyc["home"]:
                        cyc["home"] = True
                        if battery_time is None:
                            battery_time, battery_speed = t_end, -v
                        event(t_end, "gun runs out into battery", f"{-v:.2f} m/s", -v)
                    v = 0.0

        if chain:
            if running:
                qd += acc_q * dt
                q += qd * dt
                if qd < STALL_SHARE * v_free:
                    running, stalled, qd = False, True, 0.0
                    event(t_end, "the drive stalls", f"{s_q * 1e3:.0f} mm back")
            last_leg = leg
            s_new, ds, _, leg = track_at(track, q)
            u = ds * qd if running else 0.0
            s = s_new
            s_max = max(s_max, s)
            cyc["s_max"] = max(cyc["s_max"], s)
            if not unlocked and s >= unlock and u > 0:
                unlocked = True
                p_unlock = fb / loads.head_area + AMBIENT
                unlock_pressure = unlock_pressure or p_unlock
                event(t_end, "bolt unlocks", f"{p_unlock / 1e6:.1f} MPa in the chamber")
            elif unlocked and s < unlock and u < 0:
                unlocked = False
            if not cyc["ejected"] and s >= eject_at:
                cyc["ejected"] = True
                event(t_end, "case ejected", f"bolt at {u:.1f} m/s", u)
            if not cyc["can_feed"] and s >= feed_at:
                cyc["can_feed"] = True
            if belted and leg == "rear" and mag > 0 and belt_adv < 1:
                if not on_cam:
                    # The feeder picks the belt up: it shares the drive's momentum (the bolt is still).
                    on_cam = True
                    m_belt = feeding.belt_load(gun, mag)[1]
                    qd *= a.drive_mass / (a.drive_mass + m_belt * feed_ratio**2)
                into = q % perimeter - track["rear_start"]
                belt_adv = min(1.0, max(belt_adv, into / max(track["rear_length"], 1e-9)))
            elif on_cam and last_leg == "rear":
                belt_adv = 1.0        # the feeder has finished its index as the chain leaves the rear dwell
            if (cyc["can_feed"] and not (cyc["feeding"] or cyc["empty"] or cyc["misfeed"])
                    and u < 0 and s < feed_at):
                feed_round(t_end)
            if jam_at is not None and not frozen and s <= jam_at:
                frozen, running, qd = True, False, 0.0
                jam["travel_at"] = s
                event(t_end, "jams", jam["detail"], 0.0, kind=jam["jam"], angle=jam["angle"])
            if last_leg == "in" and leg == "front" and cyc["battery"] is None:
                if cyc["feeding"]:
                    cyc["battery"] = t_end
                    first_battery = first_battery or t_end
                    event(t_end, "back in battery", "the bolt turns into its locks")
                elif cyc["ejected"]:
                    cyc["battery"] = -1.0
                    event(t_end, "closes on an empty chamber")
            if running and q >= laps * perimeter:
                # The master link is at the firing point again: fire the next round, or stop the drive.
                laps += 1
                chain_cycle = chain_cycle or t_end
                if len(shot_times) < shots and cyc["feeding"] and (cyc["battery"] or -1) >= 0 and jam is None:
                    next_shot = t_end
                else:
                    running, qd = False, 0.0
                    event(t_end, "the drive stops", "at the firing point")
        elif not held:
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
                    if len(shot_times) < shots and not hammer and not semi:
                        # Automatic fire: the auto sear lets the striker go (or, with neither, the shot comes).
                        if striker:
                            release_striker(t_end)
                        else:
                            next_shot = t_end + LOCK_TIME
                elif cyc["ejected"] and cyc["battery"] is None and (not cyc["can_feed"] or cyc["empty"] or cyc["misfeed"]):
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
            carrier = ratio * s if delayed else s + carrier_gap
            gear = ratio if delayed else 1.0
            if striker and not cyc["past_catch"] and carrier >= catch:
                cyc["past_catch"] = True   # the striker's lug is back past the trigger bar, which rises behind it
            if belted:
                if mag > 0 and u > 0 and carrier > cam0 and belt_adv < 1:
                    if not on_cam:
                        # The feed slide picks the belt up: they share the carrier's momentum through the cam.
                        on_cam = True
                        u *= m_g / (m_g + feeding.belt_load(gun, mag)[1] * (cam_ratio * gear) ** 2)
                    belt_adv = min(1.0, max(belt_adv, (carrier - cam0) / (cam1 - cam0)))
            else:
                if not released and s >= feed_at:
                    released = True
                if released and mag > 0 and lift < present:
                    # The spring lifts the stack, against gravity and the gun swinging the magazine up.
                    acc = feeding.spring(gun, mag) / feeding.stack_mass(gun, mag) - feeding.G - alpha * arm
                    lift_v += acc * dt
                    lift += lift_v * dt
                    if lift <= 0:
                        lift, lift_v = 0.0, max(lift_v, 0.0)
                    elif lift >= present:
                        lift, lift_v = present, 0.0

            if (cyc["can_feed"] and not (cyc["feeding"] or cyc["empty"] or cyc["misfeed"])
                    and u < 0 and s < feed_at):
                feed_round(t_end)
            if jam_at is not None and not frozen and s <= jam_at:
                speed = -u
                stop_bolt()
                frozen = True
                jam["travel_at"] = s
                event(t_end, "jams", jam["detail"], speed, kind=jam["jam"], angle=jam["angle"])

            # How far the case has backed out of the chamber while still pressed into it.
            free = s - unlock if kind in (*LOCKED_GAS, "short_recoil") else s
            if (unlocked or (kind == "short_recoil" and not carry)) and fb / loads.head_area > CASE_PRESSURE:
                setback = max(setback, free)

        if hammer:
            carrier = ratio * s if delayed else s + carrier_gap
            gear = ratio if delayed else 1.0
            cam, slope = hammer_cam(a, carrier) if not revolving else (0.0, 0.0)
            driven = slope * gear * u           # the hammer's rate while the carrier holds it
            if hammer_state == "cocking":
                # The trigger (or the thumb) draws the hammer back to the sear, then lets it go; a
                # revolver's hand turns the cylinder on over the middle of the swing.
                f = min((t_end - cock_from) / tr.pull_time, 1.0)
                ph, om = sear * f, sear / tr.pull_time
                if revolving:
                    span = cylinder.INDEX_END - cylinder.INDEX_START
                    if not indexed:
                        turned = index_from + min(max((f - cylinder.INDEX_START) / span, 0.0), 1.0)
                    if not indexed and f >= cylinder.INDEX_END:
                        indexed, turned = True, index_from + 1
                        # The cylinder arrives at its stop at the hand's speed, and the stop takes its spin.
                        lock_speed = 2 * math.pi / n_chambers / (span * tr.pull_time)
                        held_in = cylinder.cylinder_inertia(gun, mag) \
                            + len(shot_times) * feeding.case_mass(gun) * cylinder.cylinder_radius(gun) ** 2
                        lock_energy = 0.5 * held_in * lock_speed**2
                        event(t_end, "cylinder locks", f"{lock_speed:.0f} rad/s, {lock_energy * 1e3:.1f} mJ",
                              lock_speed, energy=lock_energy)
                        live = mag > 0
                        if live:
                            mag -= 1
                if f >= 1.0:
                    hammer_state, om = "falling", 0.0
                    event(t_end, "hammer released", "at the end of the double-action pull" if double
                          else "the trigger lets the cocked hammer go")
            elif hammer_state == "cocked":
                ph, om = (cam, driven) if cam > sear else (sear, 0.0)
                if (not semi and len(shot_times) < shots and next_shot is None and cyc["feeding"]
                        and carrier <= a.hammer_trip_travel):
                    hammer_state = "falling"
                    event(t_end, "hammer released", "the closing carrier trips the auto sear")
            else:
                falling = hammer_state == "falling"
                om -= hammer_torque(a, ph) / hammer_inertia(a, ph, falling) * dt
                ph += om * dt
                if ph <= 0 and cam <= 0:
                    # On the firing pin.
                    energy = 0.5 * a.hammer_inertia * om * om
                    ph = om = 0.0
                    if falling:
                        hammer_state = "down"
                        if revolving and not live:
                            event(t_end, "the hammer falls on a fired case", "the cylinder is empty")
                            dry, shots = True, len(shot_times)
                        elif energy >= strike:
                            event(t_end, "hammer strikes the firing pin", f"{energy:.2f} J")
                            next_shot = t_end + PRIMER_DELAY
                        else:
                            event(t_end, "light strike", f"{energy:.2f} J")
                            light_strike = light_strike or (len(shot_times) + 1, energy)
                            shots = len(shot_times)
                elif ph <= cam:
                    # Caught by the carrier (or, falling, landing on it out of battery).
                    if not on_carrier and not falling and om < driven:
                        u *= m_g / (m_g + a.hammer_inertia * (slope * gear) ** 2)  # it kicks the hammer along
                        driven = slope * gear * u
                    ph, om = cam, driven
                if hammer_state == "down" and ph >= sear and tr.type != "double_action_only":
                    # (A double-action-only hammer has no single-action notch: it rides the slide back down.)
                    hammer_state = "cocked"
                    cyc["cocked"] = True
                    event(t_end, "hammer cocked", "past the sear")
            on_carrier = ph <= cam + 1e-9 and cam > 0

        if semi and not chain and not wedge and len(shot_times) < shots and next_shot is None:
            # The shooter pulls again `split` after the last shot, once the action is back in battery on a
            # round (the disconnector holds the trigger off until then).
            pull_at = shot_times[-1] + tr.split
            end = max(end, pull_at + 0.02)
            ready = revolving or (cyc["feeding"] and (cyc["battery"] or -1) >= 0 and jam is None and not frozen)
            if ready and hammer:
                cockable = revolving or double
                if hammer_state == "down" and cockable and ph <= 0 and t_end >= pull_at - tr.pull_time:
                    hammer_state, cock_from = "cocking", t_end
                    index_from, indexed = round(turned), not revolving
                    event(t_end, "trigger pulled" if double or not revolving else "hammer cocked by the thumb",
                          "double action: the pull cocks the hammer" if double else "the thumb draws the hammer back")
                elif hammer_state == "cocked" and t_end >= pull_at:
                    hammer_state = "falling"
                    event(t_end, "trigger pulled", "single action: the hammer falls")
            elif ready and t_end >= pull_at:
                event(t_end, "trigger pulled")
                if striker:
                    release_striker(t_end)
                else:
                    next_shot = t_end + LOCK_TIME

        if t >= next_out:
            next_out += OUT_FAST if fast else OUT_SLOW if since < DURATION else OUT_LONG
            out["t"].append(t_end)
            out["x"].append(x)
            out["v"].append(v)
            out["th"].append(th)
            out["s"].append(bs if wedge else s)
            out["u"].append(bu if wedge else u)
            out["force"].append(fb + fr)
            out["shoulder"].append(-f_sh)
            out["gas"].append(p_c)
            out["hammer"].append(ph)
            out["feed"].append(belt_adv if belted else (lift / present if present else 0.0))
            out["q"].append(q if chain else 0.0)
            out["cyl"].append(turned)
        t = t_end

        # Back in battery: fire the next shot of the burst.
        if next_shot is not None and t >= next_shot:
            next_shot = None
            shot_times.append(t)
            counts.append(mag)
            new_cycle()
            event(t, "fires")
            end = t + follow
            settled_at = None
        elif mounted and since > fast_for and next_shot is None:
            # A mounted gun is followed until it rests in battery with its action done.
            done = (not running if chain else block != "cam" and block != "free" if wedge
                    else kind in LOCKED or since > DURATION)
            if x == 0 and v == 0 and cyc["home"] and done:
                settled_at = settled_at if settled_at is not None else t
                if t - settled_at > SETTLE_TIME:
                    break
            else:
                settled_at = None

    if kind in LOCKED:
        status = "manual"
        if not by_hand:
            check = feeding.check(fgeo, 1.0, feed_at)
            if check["jam"]:
                warnings.append(f"feeding: {check['detail']}")
    elif revolving:
        n = len(shot_times)
        status = "empty" if dry else "fired"
        if light_strike:
            status = "light strike"
            shot_no, energy = light_strike
            warnings.append(f"light strike on shot {shot_no}: the hammer hit the firing pin with {energy:.2f} J "
                            f"(the primer needs {strike:.2f} J); a stronger mainspring would fix it")
        if dry and n < requested:
            warnings.append(f"the cylinder ran dry after {n} of {requested} shots: the hammer fell on a fired case")
    else:
        status = "cycled"
        n = len(shot_times)
        which = f" on shot {n}" if requested > 1 else ""
        if chain and stalled:
            status = "the drive stalled"
            warnings.append(f"the chain drive stalled{which}: its motor ({a.motor_power:.0f} W) could not keep the "
                            f"bolt and the belt moving; a stronger motor or a lighter bolt would keep it running")
        elif not cyc["ejected"]:
            status = "failed to eject"
            warnings.append(f"short stroke{which}: the bolt only came back {cyc['s_max'] * 1e3:.0f} mm, "
                            f"and it needs {eject_at * 1e3:.0f} mm to eject the case")
        elif not cyc["can_feed"]:
            status = "failed to feed"
            warnings.append(f"short stroke{which}: the bolt came back {cyc['s_max'] * 1e3:.0f} mm, ejecting "
                            f"the case, but it needs {feed_at * 1e3:.0f} mm to pick up the next round")
        elif jam is not None:
            status = f"jammed: {jam['jam']}"
            warnings.append(f"jam{which}: {jam['detail']}")
        elif cyc["misfeed"]:
            status = "failed to feed"
            warnings.append(f"failed to feed{which}: {cyc['misfeed']}")
        elif cyc["empty"]:
            status = "empty, bolt held open" if held_open else "empty"
        elif cyc["battery"] is None or cyc["battery"] < 0:
            status = "did not return to battery"
            warnings.append(f"the return spring did not close the bolt on the new round{which}")
        elif hammer and not cyc["cocked"] and tr.type != "double_action_only" and not (semi and double):
            status = "hammer not cocked"
            warnings.append(f"short stroke{which}: the carrier came back {cyc['s_max'] * 1e3:.0f} mm, and it needs "
                            f"{geo['hammer'] * 1e3:.0f} mm to cock the hammer")
        elif light_strike and striker:
            status = "light strike"
            shot_no, energy = light_strike
            warnings.append(f"light strike on shot {shot_no}: the striker hit the primer with {energy:.3f} J (it needs "
                            f"{strike:.3f} J); a stronger striker spring, a heavier striker or more travel would fix it")
        elif light_strike:
            status = "light strike"
            shot_no, energy = light_strike
            why = ("it fell on the carrier while the carrier had bounced out of battery, and rode it home; "
                   "a rate reducer or a softer return would let the carrier settle first"
                   if energy < 0.5 * hammer_fall(gun)[1] else "a stronger hammer spring would fix it")
            warnings.append(f"light strike on shot {shot_no}: the hammer hit the firing pin with {energy:.2f} J "
                            f"(a primer needs {strike:.2f} J); {why}")
        if status not in ("cycled", "empty", "empty, bolt held open") and n < requested:
            warnings.append(f"the burst stopped after {n} of {requested} shots")
    if wedge:
        if block == "open":
            status = "breech opened"
        elif block in ("cam", "free"):
            status = "breech part open"
            warnings.append(f"the gun ran out too weakly to drive the breech block open: it stopped "
                            f"{x * 1e3:.0f} mm short of battery with the block {bs * 1e3:.0f} of {stroke * 1e3:.0f} mm "
                            f"down. A stronger recuperator, or a lighter block or closing spring, would open it; "
                            f"the loader opens it by hand")
        elif block == "reshut":
            status = "breech did not open"
            warnings.append("the block left the cam too slowly to reach the extractors and sprang shut again; "
                            "the loader opens it by hand")
        else:
            status = "breech did not open"
            warnings.append(f"the gun never ran out onto the opening cam (it is still {x * 1e3:.0f} mm back); "
                            "the loader opens the breech by hand")
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
        if chain:
            warnings.append(f"the bolt unlocks with {unlock_pressure / 1e6:.0f} MPa still in the chamber: the dwell in "
                            "battery is too short for the bore to blow down (a wider track or a slower chain)")
        else:
            warnings.append(f"it unlocks with {unlock_pressure / 1e6:.0f} MPa still in the chamber, "
                            "so the case is pulled while pressed into the chamber walls" + flutes)
    if setback > CASE_SETBACK_WARNING:
        warnings.append(f"the case backs {setback * 1e3:.1f} mm out of the chamber while the chamber is still "
                        f"above {CASE_PRESSURE / 1e6:.0f} MPa: its unsupported head may rupture" + flutes)
    if mounted:
        if stop_speed is not None:
            warnings.append(f"the gun hits its recoil stop at {stop_speed:.2f} m/s: the buffer is too weak for this "
                            f"shot (a smaller orifice, a stiffer spring or a longer stroke than {mt.stroke * 1e3:.0f} mm)")
        if battery_time is None:
            warnings.append(f"the gun did not run out into battery (it is still {x * 1e3:.0f} mm back): the "
                            "recuperator or spring is too weak for the friction and the counter-recoil buffer")

    impulse = loads.impulse
    fall = hammer_fall(gun) if hammer else None
    arr = {k: np.array(val) for k, val in out.items()}
    shoulder_force = arr["shoulder"] if shoulder or mounted else np.zeros_like(arr["t"])
    # The trigger's work: a double-action pull cocks the hammer too.
    sa_work, da_work = tr.pull * tr.travel, tr.da_pull * tr.da_travel
    told = semi or tr.type != "single_action"
    first_work = (da_work if double else sa_work) if told else None
    again_work = (da_work if tr.type == "double_action_only" or (revolving and double) else sa_work) if told else None
    lock_time = (0.0 if chain else striker_time + PRIMER_DELAY if striker else fall[0] + PRIMER_DELAY if hammer
                 else LOCK_TIME)
    result = ActionResult(
        kind=kind, stance=sh.stance, time=arr["t"],
        recoil=arr["x"], recoil_velocity=arr["v"], pitch=arr["th"],
        bolt=arr["s"], bolt_velocity=arr["u"], force=arr["force"],
        shoulder_force=shoulder_force, gas_pressure=arr["gas"],
        hammer=arr["hammer"] if hammer else None,
        impulse=impulse,
        free_recoil_velocity=impulse / gun_mass,
        free_recoil_energy=impulse**2 / (2 * gun_mass),
        max_recoil=float(arr["x"].max()),
        peak_recoil_velocity=float(arr["v"].max()),
        peak_shoulder_force=float(shoulder_force.max()),
        max_pitch=float(arr["th"].max()),
        bolt_max_travel=float(arr["s"].max()) if wedge else s_max,
        strokes=geo,
        status=status,
        gun_mass=gun_mass,
        events=events,
        warnings=warnings,
        shot_times=shot_times,
        rear_speed=rear_speed,
        cycle_time=chain_cycle if chain else None if wedge else first_battery,
        unlock_pressure=unlock_pressure,
        gas_peak_pressure=gas_peak if kind in GAS_SYSTEMS else None,
        port_cd=port_cd,
        port_cd_2d=port_2d,
        lock_time=lock_time,
        hammer_energy=fall[1] if hammer else None,
        feed=arr["feed"],
        rounds=counts,
        rounds_left=mag,
        chambered=(mag > 0 if revolving else
                   kind not in LOCKED and cyc["feeding"] and jam is None and (cyc["battery"] or -1) >= 0),
        held_open=held_open,
        jam=jam,
        feed_angle=fgeo["angle"],
        capacity=cap,
        battery_time=battery_time,
        battery_speed=battery_speed,
        stop_speed=stop_speed,
        drive=arr["q"] if chain else None,
        motor_peak_power=motor_peak if chain else None,
        open_time=open_time,
        case_speed=case_speed,
        cylinder=arr["cyl"] if revolving else None,
        cylinder_lock_speed=lock_speed,
        cylinder_lock_energy=lock_energy,
        trigger=tr.type,
        trigger_work=first_work,
        follow_up_work=again_work,
        striker_energy=striker_energy,
        strike_energy=strike,
        semi=semi,
    )
    if feeding.autoloader(gun):
        # The autoloader rams the next round once the breech is open.
        al = result.autoloader = autoloading.simulate(gun, result, mag)
        result.warnings += [f"autoloader: {w}" for w in al["warnings"]]
        if al["loaded"]:
            result.rounds_left, result.chambered = al["rounds_after"], True
    return result
