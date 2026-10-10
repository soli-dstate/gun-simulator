"""Autoloaders: how a tank gun's next round reaches the breech with no loader.

After the shot the sliding wedge opens as the gun runs out (gun_sim/action.py)
and the autoloader takes over. Each autoloader is a sequence of moves, each
made by one of its drives against the masses and loads it has to move:

* "az", the T-72's and T-90's electromechanical carousel (avtomat
  zaryazhaniya). Two-piece rounds lie flat in cassettes round a carousel under
  the turret floor, the projectile in the lower tier and the charge over it.
  The gun is brought to its loading angle and locked while the carousel turns
  the chosen cassette under the lift; the lift raises it behind the breech; the
  chain rammer rams the projectile, the lift raises the charge's tier into
  line, the rammer rams the charge, whose stub's rim trips the extractors so
  the block springs shut; the lift lowers the empty cassette and the gun is
  let go. The stub of the last shot was thrown out of the turret through a
  hatch.
* "mz", the T-64's and T-80's hydraulic carousel (mekhanizm zaryazhaniya). The
  charges stand upright round the outside of a bigger carousel, the
  projectiles lie flat inside them. The same sequence, but the drives are
  hydraulic (a pump running all through the cycle, valves switching each move
  in), the raised cassette's charge tray swings up into line behind the
  projectile, and the stub catcher holds the last shot's stub and drops it
  into the empty cassette before it goes down.
* "bustle", unitary rounds standing nose-forwards in a conveyor in the turret
  bustle behind the gun (the Leclerc's, the Type 90's). The conveyor brings
  the chosen round behind the breech while the gun comes to its loading angle,
  the blast door between the bustle and the crew opens, the rammer pushes the
  round straight from the conveyor into the breech and the door shuts again.
  feed.drive "electric" is the Leclerc's: servo motors, each move in one
  smooth stroke; "electromechanical" the Type 90's: one motor and clutches,
  intermittent gearing and cams, each move clutched in and braked out.
* "oscillating", the AMX-13's and SK-105's: the whole upper turret elevates
  with the gun, so its two revolver drums in the bustle are always in line
  with the breech and it loads at any elevation. The recoil cocks the rammer's
  spring; the extractors throw the case out through the trapdoor in the turret
  rear, the drum turns a round on and drops it onto the loading tray, and the
  spring rams it. The drums are refilled from outside the tank.

Each move: the drive pushes its load with a force falling as power / speed
(capped at what accelerates the load at its `accel` limit), against gravity
and friction, up to the speed the mechanism allows, braking at the same rate
to stop where it should. Electromechanical drives clutch each move in and
brake it out, hydraulic ones switch a valve, so each move has a dead time too.
The rammer lets a piece go short of the chamber and it runs on into the
forcing cone: a projectile has to arrive at SEAT_SPEED or more to wedge its
driving band in, or it slides back out when the gun is elevated. A drive too
weak to start its load stalls the cycle.

The figures for the mechanisms (their masses, travels and speeds) are
illustrative, scaled from the round; the sequences are the real ones.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np

from . import feed as feeding

if TYPE_CHECKING:
    from .action import ActionResult
    from .config import Gun

TYPES = ("az", "mz", "bustle", "oscillating")
DRIVES = ("electric", "electromechanical", "hydraulic", "spring")
AMMUNITION = ("two_piece", "unitary")
LABELS = {"az": "AZ carousel", "mz": "MZ carousel", "bustle": "bustle conveyor", "oscillating": "oscillating turret"}
# Per type: its drive, rounds, whether they are two-piece, the gun's loading angle (None: it loads at any
# elevation), the drives' power (W) and the rammer's top speed (m/s).
DEFAULTS = {
    "az": {"drive": "electromechanical", "capacity": 22, "two_piece": True, "load_angle": 3.0, "power": 1500.0,
           "ram_speed": 2.2},
    "mz": {"drive": "hydraulic", "capacity": 28, "two_piece": True, "load_angle": 3.0, "power": 4000.0,
           "ram_speed": 2.6},
    "bustle": {"drive": "electric", "capacity": 22, "two_piece": False, "load_angle": 0.0, "power": 3000.0,
               "ram_speed": 3.0},
    "oscillating": {"drive": "spring", "capacity": 12, "two_piece": False, "load_angle": None, "power": 0.0,
                    "ram_speed": 3.5},
}
# Per drive: the acceleration it gives its load at most (m/s^2), the dead time before each move (s: a
# clutch, a valve) and after it (braking, a lock pin going in).
DRIVE = {
    "electric": {"accel": 8.0, "engage": 0.03, "settle": 0.05},
    "electromechanical": {"accel": 4.0, "engage": 0.08, "settle": 0.07},
    "hydraulic": {"accel": 6.0, "engage": 0.08, "settle": 0.08},
    "spring": {"accel": 40.0, "engage": 0.02, "settle": 0.03},
}
REF_RIM = 0.16          # m: the mechanisms' figures are for a 120/125 mm round's rim, and scale with it
PITCH = 1.2             # carousel, conveyor and drum positions this many rims apart
LIFT_HEIGHT = 4.5       # rims from the carousel up to the rammer's line
TIER = 1.2              # rims between an AZ cassette's two tiers
DROP = 1.1              # rims an oscillating turret's round falls from its drum onto the tray
RAM_GAP = 0.10          # m: the rammer's head starts this far behind the piece's base...
RUN_ON = 0.12           # ...and lets it go this far short of where it seats
SEAT_SPEED = 1.2        # m/s a projectile needs to wedge its driving band into the forcing cone
FRICTION = 0.15         # a piece sliding on its tray and into the chamber
G = 9.81
V_KNEE = 0.05           # m/s: below this a drive gives its stall force, power / V_KNEE
DT = 1e-3               # s
# Mechanism masses (kg) for the reference round, scaled with the rim squared.
CAROUSEL_PER_POSITION = 6.0    # structure and cassette per position, besides the rounds
LIFT_ARM = 30.0
RAMMER = 8.0
DOOR = 18.0
CONVEYOR_LINK = 5.0
DRUM = 25.0
TRAY = 12.0
# Speed limits of the mechanisms (m/s; elevation in its own deg/s).
V_CAROUSEL = {"electromechanical": 0.45, "hydraulic": 0.6, "electric": 0.6, "spring": 1.5}
V_LIFT = 1.0
V_DOOR = 1.2
V_CONVEYOR = {"electric": 0.9, "electromechanical": 0.5, "hydraulic": 0.6, "spring": 1.5}
ELEVATION_ACCEL = 20.0  # deg/s^2
LOCK = 0.15             # s for the elevation lock (or the drum's pawl) to go in
COCK_SHARE = 0.6        # oscillating turret: the recoil cocks the rammer's spring over this share of the stroke
TRACK_POINTS = 40       # samples per move in the animation tracks


def kind(gun: Gun) -> str | None:
    """The autoloader's type, or None."""
    return gun.feed.type if gun.feed.type in TYPES else None


def settings(gun: Gun) -> dict:
    """The autoloader's drive, two_piece, load_angle (None: any), power and ram_speed, filled in for its type."""
    f, d = gun.feed, DEFAULTS[gun.feed.type]
    return {
        "drive": f.drive or d["drive"],
        "two_piece": d["two_piece"] if f.ammunition is None else f.ammunition == "two_piece",
        "load_angle": None if d["load_angle"] is None else (d["load_angle"] if f.load_angle is None else f.load_angle),
        "power": f.drive_power if f.drive_power is not None else d["power"],
        "ram_speed": f.ram_speed if f.ram_speed is not None else d["ram_speed"],
    }


def pieces(gun: Gun, two_piece: bool) -> list[dict]:
    """What is rammed, in order: {name, mass (kg), length (m)}."""
    p, c = gun.projectile, gun.case
    charge = gun.propellant.charge_mass + feeding.case_mass(gun)
    if two_piece:
        return [{"name": "projectile", "mass": p.mass, "length": p.length},
                {"name": "charge", "mass": charge, "length": c.length}]
    return [{"name": "round", "mass": p.mass + charge, "length": c.overall_length}]


def geometry(gun: Gun) -> dict:
    """Sizes of the mechanism (m), for the cycle and the 3D view."""
    t = kind(gun)
    d = gun.case.rim_diameter
    n = feeding.capacity(gun)
    pitch = PITCH * d
    out = {"type": t, "positions": n, "pitch": pitch, "rim": d, "lift": LIFT_HEIGHT * d, "tier": TIER * d,
           "drop": DROP * d, "scale": d / REF_RIM}
    if t in ("az", "mz"):
        out["radius"] = max(n * pitch / (2 * math.pi), 2 * d)
    elif t == "bustle":
        out["loop"] = math.ceil(n / 2) * pitch       # two rows, joined round sprockets at the ends
    elif t == "oscillating":
        per = math.ceil(n / 2)
        out["drums"] = 2
        out["per_drum"] = per
        out["radius"] = max(per * pitch / (2 * math.pi), 0.8 * d)
    return out


def _move(distance: float, mass: float, power: float | None, v_cap: float, accel: float, resist: float = 0.0,
          brake: bool = True) -> dict | None:
    """Drive `mass` `distance` against a steady `resist` (N), up to v_cap, its force power / speed at most
    (power None: no limit) and never more than accelerates it at `accel`. brake: slow at `accel` to stop at
    the end; else it is let go at speed there. Returns {t, x, v} from 0, or None if the drive stalls."""
    if distance <= 0:
        return {"t": np.array([0.0]), "x": np.array([0.0]), "v": np.array([0.0])}
    peak = mass * accel + resist
    if power is not None:
        peak = min(peak, power / V_KNEE)
    if peak <= resist * 1.0001:
        return None
    t = x = v = 0.0
    ts, xs, vs = [0.0], [0.0], [0.0]
    while x < distance:
        left = distance - x
        if brake and v > 0 and v * v / (2 * accel) >= left:
            a = -accel
        else:
            force = peak if power is None else min(peak, power / max(v, V_KNEE))
            a = min((force - resist) / mass, accel) if v < v_cap else 0.0
        v_new = max(v + a * DT, 0.0)
        if v_new > v_cap:
            v_new = v_cap
        step = 0.5 * (v + v_new) * DT
        if step <= 0 and v_new <= 0:
            # Braked to a stop a hair short: creep in.
            step, v_new = left, 0.0
        x = min(x + step, distance)
        v = v_new
        t += DT
        ts.append(t)
        xs.append(x)
        vs.append(v)
        if t > 120:
            return None
    if brake:
        vs[-1] = 0.0
    return {"t": np.array(ts), "x": np.array(xs), "v": np.array(vs)}


def block_closing(gun: Gun) -> dict | None:
    """The block springing shut once the round's rim has tripped the extractors: {time, speed}, or None
    if its closing spring cannot lift it."""
    from .action import strokes
    a = gun.action
    m, y, v, t = a.bolt_mass, strokes(gun)["stroke"], 0.0, 0.0
    while y > 0:
        f = a.spring_preload + a.spring_rate * y - m * G - a.friction
        if f <= 0 and v <= 0:
            return None
        v += f / m * DT
        y -= v * DT
        t += DT
        if t > 10:
            return None
    return {"time": t, "speed": v}


class _Cycle:
    """The cycle being built: moves on a clock, the parts' tracks, events and warnings."""

    def __init__(self, gun: Gun, s: dict):
        self.gun, self.s = gun, s
        self.drv = DRIVE[s["drive"]]
        self.stages, self.events, self.warnings = [], [], []
        self.tracks: dict[str, list] = {}
        self.drives: list[dict] = []      # powered moves, for the sound: {t0, t, v, v_cap, power, drive}
        self.norm: dict[str, float] = {}  # tracks given in m, shown as a share of this (or in positions)
        self.stalled = None

    def at(self, part: str, t: float, x: float) -> None:
        tr = self.tracks.setdefault(part, [[], []])
        if tr[0] and t < tr[0][-1]:
            t = tr[0][-1]
        tr[0].append(float(t))
        tr[1].append(float(x))

    def value(self, part: str, default: float = 0.0) -> float:
        tr = self.tracks.get(part)
        return tr[1][-1] if tr and tr[1] else default

    def event(self, t: float, name: str, detail: str = "", energy: float = 0.0, mass: float = 0.0, where: str = "turret"):
        self.events.append({"time": float(t), "name": name, "detail": detail, "energy": float(energy),
                            "mass": float(mass), "where": where})

    def move(self, start: float, name: str, part: str, distance: float, mass: float, v_cap: float,
             resist: float = 0.0, sign: float = 1.0, brake: bool = True, piece: str | None = None,
             power: float | None | bool = True, detail: str = "") -> dict | None:
        """A move of `part` from where it is by sign * distance, starting at `start`: its stage, or None if it
        stalled. power: True for the autoloader's drive, False for none to speak of (a spring, the gun's own
        elevation drive)."""
        if self.stalled is not None:
            return None
        pw = self.s["power"] if power is True else (None if power is False else power)
        laying = part == "elevation"
        engage, settle = (0.0, 0.0) if laying else (self.drv["engage"], self.drv["settle"])
        accel = ELEVATION_ACCEL if laying else self.drv["accel"]
        prof = _move(abs(distance), mass, pw, v_cap, accel, resist, brake)
        if prof is None:
            self.stalled = name
            self.warnings.append(f"the autoloader stalled: its drive ({pw:.0f} W) could not {name} "
                                 f"({mass:.0f} kg against {resist:.0f} N); a stronger drive would")
            self.event(start, "the drive stalls", name)
            return None
        t0 = start + engage
        x0 = self.value(part)
        k = max(1, len(prof["t"]) // TRACK_POINTS)
        idx = list(range(0, len(prof["t"]), k)) + [len(prof["t"]) - 1]
        self.at(part, start, x0)
        for i in idx:
            self.at(part, t0 + prof["t"][i], x0 + sign * prof["x"][i])
        end = t0 + float(prof["t"][-1])
        peak = float(prof["v"].max())
        st = {"name": name, "part": part, "start": float(start), "end": float(end + settle), "piece": piece,
              "detail": detail or f"{abs(distance) * (1 if part == 'elevation' else 1e3):.0f} "
                                  f"{'deg' if part == 'elevation' else 'mm'}, up to "
                                  f"{peak:.2f} {'deg/s' if part == 'elevation' else 'm/s'}",
              "speed": peak, "exit_speed": float(prof["v"][-1])}
        self.stages.append(st)
        if pw is not None and not laying and self.s["drive"] != "spring":
            self.drives.append({"t0": t0, "t": prof["t"], "v": prof["v"], "v_cap": v_cap, "mass": mass,
                                "resist": resist, "power": pw, "drive": self.s["drive"], "part": part})
        if self.s["drive"] == "electromechanical" and pw is not None and not laying:
            self.event(start, "clutch engages", name, energy=0.02 * self.s["power"] / 100, mass=2.0)
        elif self.s["drive"] == "hydraulic" and pw is not None and not laying:
            self.event(start, "valve switches", name, energy=0.3, mass=1.5)
        if brake and not laying:
            # It comes to rest on its stop, the last of its speed into a latch or the stop.
            self.event(end, f"{part} stops", name, energy=0.5 * mass * (0.15 * peak) ** 2 + 0.05, mass=mass)
        return st


def simulate(gun: Gun, act: ActionResult, rounds: int) -> dict | None:
    """The autoloader's cycle after a shot, from the action simulation of it. rounds: in the autoloader
    when the shot was fired (besides the one in the breech). None if the gun has no autoloader."""
    t = kind(gun)
    if t is None:
        return None
    s = settings(gun)
    geo = geometry(gun)
    k2 = geo["scale"] ** 2
    cy = _Cycle(gun, s)
    f = gun.feed
    load = s["load_angle"]
    out = {"type": t, "label": LABELS[t], **s, "geometry": geo, "rounds_before": rounds, "rounds_after": rounds,
           "loaded": False, "ready_time": None, "rate": None, "status": "", "seat_speed": None,
           "block_speed": None}
    opened = act.open_time is not None and act.status == "breech opened"
    if not opened:
        out["status"] = "breech not open"
        cy.warnings.append("the breech did not open, so the autoloader could not load: the crew opens it by hand")
        return _finish(out, cy)
    if rounds <= 0:
        out["status"] = "empty"
        cy.warnings.append("the autoloader is empty: the breech is left open")
        return _finish(out, cy)
    start = max(act.open_time, act.battery_time or act.open_time)
    ps = pieces(gun, s["two_piece"])
    rammer_m = RAMMER * k2
    steps = min(f.index_steps, max(geo["positions"] - f.index_steps, 0)) if t != "oscillating" else 1
    mass_rounds = sum(p["mass"] for p in ps)
    angle = math.radians(load if load is not None else f.gun_elevation)

    cy.at("block", 0.0, 1.0)
    for part in ("rammer", "lift", "door", "tray", "carousel", "conveyor", "drum"):
        cy.at(part, 0.0, 0.0)
    cy.at("elevation", 0.0, f.gun_elevation)

    # ---- the gun to its loading angle, and the chosen round brought round, together ----
    ready = [start]
    elevated = start
    if load is not None and abs(load - f.gun_elevation) > 1e-6:
        st = cy.move(start, "bring the gun to its loading angle", "elevation", load - f.gun_elevation, 1.0,
                     f.elevation_rate, sign=math.copysign(1.0, load - f.gun_elevation), power=False)
        if st:
            cy.event(st["end"], "the gun locks at the loading angle", f"{load:.1f}°", energy=40.0 * k2, mass=200.0)
            elevated = st["end"] + LOCK
    ready.append(elevated)
    indexed = start
    if t in ("az", "mz") and steps:
        carry = geo["positions"] * CAROUSEL_PER_POSITION * k2 + rounds * mass_rounds
        st = cy.move(start, f"turn the carousel {steps} position{'s' if steps > 1 else ''}", "carousel",
                     steps * geo["pitch"], carry, V_CAROUSEL[s["drive"]], resist=FRICTION * 0.2 * carry * G,
                     detail=f"{steps} of {geo['positions']} positions, {carry:.0f} kg")
        if st:
            cy.event(st["end"], "the carousel's lock pin drops in", "", energy=3.0 * k2, mass=3.0)
            indexed = st["end"]
    elif t == "bustle" and steps:
        carry = geo["positions"] * CONVEYOR_LINK * k2 + rounds * mass_rounds
        st = cy.move(start, f"run the conveyor {steps} position{'s' if steps > 1 else ''}", "conveyor",
                     steps * geo["pitch"], carry, V_CONVEYOR[s["drive"]], resist=FRICTION * carry * G,
                     detail=f"{steps} of {geo['positions']} positions, {carry:.0f} kg")
        if st:
            indexed = st["end"]
    ready.append(indexed)
    if t == "bustle":
        # The blast door between the bustle and the crew opens meanwhile.
        st = cy.move(start, "open the blast door", "door", 1.4 * geo["rim"], DOOR * k2, V_DOOR,
                     resist=DOOR * k2 * G)
        if st:
            ready.append(st["end"])
    now = max(ready)

    if t == "az":
        cy.event(start + 0.25, "the stub is thrown out through the turret's hatch", "", energy=20.0 * k2, mass=5.0)
    elif t == "mz":
        cy.event(start + 0.05, "the stub catcher takes the stub", "", energy=8.0 * k2, mass=feeding.case_mass(gun))

    # ---- bring the round up behind the breech ----
    cassette = 0.35 * mass_rounds
    if t in ("az", "mz"):
        lifted = LIFT_ARM * k2 + cassette + mass_rounds
        st = cy.move(now, "raise the cassette behind the breech", "lift", geo["lift"], lifted, V_LIFT,
                     resist=lifted * G)
        now = st["end"] if st else now
        if t == "mz" and st:
            # The charge's tray swings up from upright into line behind the projectile.
            arc = 0.5 * math.pi * 0.5 * ps[1]["length"]
            sw = cy.move(now, "swing the charge tray into line", "tray", arc, TRAY * k2 + ps[1]["mass"], V_LIFT,
                         resist=ps[1]["mass"] * G * 0.5)
            if sw:
                cy.norm["tray"] = arc
                now = sw["end"]
    elif t == "bustle":
        # The round is pushed down out of its conveyor cell onto the rammer's tray, in line with the breech.
        st = cy.move(now, "transfer the round onto the ramming tray", "tray", geo["drop"],
                     TRAY * k2 + mass_rounds, V_LIFT, resist=FRICTION * (TRAY * k2 + mass_rounds) * G)
        if st:
            cy.event(st["end"], "the round drops onto the ramming tray", "", energy=0.5 * mass_rounds * 0.3**2,
                     mass=mass_rounds)
            now = st["end"]
    elif t == "oscillating":
        cock = COCK_SHARE * gun.mount.stroke
        if act.max_recoil < cock:
            cy.warnings.append(f"the gun recoiled only {act.max_recoil * 1e3:.0f} mm, short of the "
                               f"{cock * 1e3:.0f} mm that cocks the rammer's spring: the crew rams the round by hand")
            out["status"] = "rammer not cocked"
            return _finish(out, cy)
        cy.event(start + 0.08, "the case bangs out through the rear trapdoor", "", energy=30.0 * k2, mass=12.0)
        cy.event(start + 0.4, "the trapdoor swings shut", "", energy=25.0 * k2, mass=12.0)
        st = cy.move(start, "turn the drum a round on", "drum", geo["pitch"],
                     DRUM * k2 + geo["per_drum"] * mass_rounds, V_CAROUSEL["spring"], power=False)
        if st:
            cy.event(st["end"], "the drum's pawl clicks in", "", energy=2.0 * k2, mass=2.0)
            now = max(now, st["end"])
            fall = math.sqrt(2 * geo["drop"] / G)
            cy.at("tray", now, 0.0)
            for i in range(1, 11):
                cy.at("tray", now + fall * i / 10, geo["drop"] * (i / 10) ** 2)
            now += fall
            cy.event(now, "the round drops onto the loading tray", f"{geo['drop'] * 1e3:.0f} mm",
                     energy=mass_rounds * G * geo["drop"], mass=mass_rounds)
            now += 0.1

    # ---- ram each piece ----
    slope = G * (math.sin(angle) + FRICTION * math.cos(angle))
    for i, p in enumerate(ps):
        if cy.stalled:
            break
        if i and t == "az":
            # The lift brings the charge's tier into line.
            lifted = LIFT_ARM * k2 + cassette + p["mass"]
            st = cy.move(now, "raise the charge's tier into line", "lift", geo["tier"], lifted, V_LIFT,
                         resist=lifted * G)
            now = st["end"] if st else now
        stroke = p["length"] + RAM_GAP
        m = p["mass"] + rammer_m
        v_cap = s["ram_speed"]
        if t == "oscillating":
            # The spring is let go: it drives the rammer and the round with what the recoil stored in it.
            st = cy.move(now, f"ram the {p['name']}", "rammer", stroke - RUN_ON, m, v_cap, resist=m * slope,
                         brake=False, piece=p["name"], power=False)
            cy.event(now, "the rammer's spring is let go", "", energy=0.5 * m * v_cap**2 * 0.05, mass=1.0)
        else:
            st = cy.move(now, f"ram the {p['name']}", "rammer", stroke - RUN_ON, m, v_cap, resist=m * slope,
                         brake=False, piece=p["name"])
        if not st:
            break
        v_rel = st["exit_speed"]
        # Let go short of the chamber, the piece runs on against friction and gravity into its seat.
        run = v_rel * v_rel - 2 * slope * RUN_ON
        v_seat = math.sqrt(run) if run > 0 else 0.0
        now = st["end"]
        cy.at("rammer", now + RUN_ON / max(v_rel, 0.1), stroke)
        t_seat = now + RUN_ON / max(0.5 * (v_rel + v_seat), 0.1)
        if p["name"] in ("projectile", "round"):
            out["seat_speed"] = v_seat
            if v_seat < SEAT_SPEED:
                cy.warnings.append(f"the {p['name']} reached the forcing cone at {v_seat:.2f} m/s, short of the "
                                   f"{SEAT_SPEED:.1f} m/s that wedges its driving band in: at the "
                                   f"{math.degrees(angle):.0f}° loading angle it can slide back out "
                                   "(a faster rammer would seat it)")
            cy.event(t_seat, f"the {p['name']} seats in the forcing cone", f"{v_seat:.2f} m/s",
                     energy=0.5 * p["mass"] * v_seat**2, mass=p["mass"])
        else:
            cy.event(t_seat, "the charge is rammed home", f"{v_seat:.2f} m/s",
                     energy=0.5 * p["mass"] * v_seat**2, mass=p["mass"])
        # The rammer brakes and draws back.
        back = cy.move(t_seat, "draw the rammer back", "rammer", stroke, rammer_m, s["ram_speed"] * 1.3,
                       sign=-1.0, power=None if t == "oscillating" else True)
        if i < len(ps) - 1:
            now = back["end"] if back else t_seat
        else:
            closed_at = t_seat
            retracted = back["end"] if back else t_seat

    if cy.stalled:
        out["status"] = "stalled"
        return _finish(out, cy)

    # ---- the last rim trips the extractors: the block springs shut ----
    close = block_closing(gun)
    if close is None:
        cy.warnings.append("the closing spring cannot lift the block shut: the crew closes it by hand")
        out["status"] = "block did not close"
        return _finish(out, cy)
    shut = closed_at + close["time"]
    cy.at("block", closed_at, 1.0)
    for i in range(1, 11):
        cy.at("block", closed_at + close["time"] * i / 10, 1.0 - (i / 10) ** 2)
    cy.event(shut, "the block springs shut", f"{close['speed']:.2f} m/s",
             energy=0.5 * gun.action.bolt_mass * close["speed"] ** 2, mass=gun.action.bolt_mass)
    out["block_speed"] = close["speed"]
    released = max(shut, retracted)

    # ---- put everything away and let the gun go, together: it fires once both are done ----
    now = released
    if t in ("az", "mz"):
        if t == "mz":
            cy.event(released, "the stub catcher drops the stub into the empty cassette", "", energy=4.0 * k2,
                     mass=feeding.case_mass(gun))
            cy.move(released, "swing the charge tray back", "tray", cy.value("tray"), TRAY * k2, V_LIFT, sign=-1.0)
        lowered = cy.move(released, "lower the empty cassette", "lift", cy.value("lift"),
                          LIFT_ARM * k2 + cassette, V_LIFT, sign=-1.0, resist=0.0)
        now = lowered["end"] if lowered else now
    elif t == "bustle":
        cy.move(released, "return the ramming tray", "tray", cy.value("tray"), TRAY * k2, V_LIFT, sign=-1.0)
        st = cy.move(released, "shut the blast door", "door", 1.4 * geo["rim"], DOOR * k2, V_DOOR, sign=-1.0,
                     resist=0.0)
        if st:
            cy.event(st["end"], "the blast door shuts", "", energy=0.5 * DOOR * k2 * (0.3 * V_DOOR) ** 2 + 2,
                     mass=DOOR * k2)
            now = st["end"]
    elif t == "oscillating":
        cy.at("tray", released, 0.0)
    if load is not None and abs(load - f.gun_elevation) > 1e-6:
        cy.event(released, "the gun is let go", "", energy=10.0 * k2, mass=50.0)
        st = cy.move(released, "lay the gun again", "elevation", load - f.gun_elevation, 1.0, f.elevation_rate,
                     sign=-math.copysign(1.0, load - f.gun_elevation), power=False)
        now = max(now, st["end"]) if st else now

    out["loaded"] = True
    out["rounds_after"] = rounds - 1
    out["ready_time"] = now
    out["rate"] = 60.0 / now
    out["status"] = "loaded"
    return _finish(out, cy)


def _finish(out: dict, cy: _Cycle) -> dict:
    end = max([st["end"] for st in cy.stages] + [e["time"] for e in cy.events] + [0.0])
    geo = out["geometry"]
    norm = {"carousel": geo["pitch"], "conveyor": geo["pitch"], "drum": geo["pitch"], "door": 1.4 * geo["rim"],
            "tray": geo["drop"], **cy.norm}
    for part, (ts, xs) in cy.tracks.items():
        if ts and ts[-1] < end:
            ts.append(end)
            xs.append(xs[-1])
        if part in norm:
            xs[:] = [x / norm[part] for x in xs]
    out.update(stages=cy.stages, events=sorted(cy.events, key=lambda e: e["time"]), warnings=cy.warnings,
               tracks={k: {"t": v[0], "x": v[1]} for k, v in cy.tracks.items()}, drives=cy.drives, end=end)
    return out


def to_json(al: dict | None) -> dict | None:
    """The cycle for the UI: everything but the drives' raw speed profiles."""
    if al is None:
        return None
    return {k: v for k, v in al.items() if k != "drives"}


def summary(al: dict) -> str:
    if al["loaded"]:
        line = (f"  autoloader           {al['label']} ({al['drive']}): loaded, ready to fire "
                f"{al['ready_time']:.1f} s after the shot ({al['rate']:.1f} rounds/min); "
                f"{al['rounds_after']} rounds left")
    else:
        line = f"  autoloader           {al['label']} ({al['drive']}): {al['status']}"
    return line
