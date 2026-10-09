"""Feeding: the magazine or belt that holds the rounds, and how each one reaches the chamber.

Magazines (single, double and quad stack, and drums) hold their rounds on a
spring. While the bolt is over the top round it holds the stack down; once the
bolt face is back past the round's head the spring lifts it the last
PRESENT rim diameters against the feed lips, into the bolt face's path. The
whole stack moves (a drum's rotor turns every round in its spiral), so the
spring, weaker as the magazine empties, has the follower and every round left
to lift, against gravity and the gun's own muzzle-up swing. If the round has
risen less than CATCH of the way when the bolt comes back, the bolt rides over
it. The spring also presses the round against the bolt's underside, so the bolt
drags `friction` times the spring force while it is over the magazine.

A belt sits in a tray over the bolt. A cam on the bolt group (the carrier, or a
one-piece bolt) swings a feed lever in the top cover that drives a feed slide
across: as the carrier travels from `belt_cam_start` over `belt_cam` it draws
the belt one link along, lifting the hanging belt (`belt_hang` of it) and
accelerating it. The carrier feels the belt as a mass r^2 m and a force r T
through the cam (r = link pitch / cam travel). A carrier that doesn't finish
the cam leaves the next round short of the bolt face. A chain gun's feeder is
driven off its chain instead (action.py). A dual feed has a belt from each side
and feeds from the selected one; a loader ("hand") puts each round in himself,
so nothing in the gun feeds it. A revolver's cylinder ("cylinder") holds each
round in a chamber of its own and is turned to the next (gun_sim/action.py), so
nothing feeds it either.

Cases. A combustible case's body burns with the charge, so a round's metal is
only its stub base (case_mass), which is all the breech extracts.

Feed angle. The lips hold the round tilted, nose towards the bore, by
`feed_angle` (None: aimed so its tip meets the bore axis), with its head
`drop` from the bore. As the bolt pushes it, the tip must find the chamber
mouth or slide up the feed ramp, a slope of `ramp_angle` from the chamber's
edge down to where the top round lies under the bolt. Too steep an angle and
the tip stubs on the barrel face beyond the chamber; too shallow and it dives
under the ramp, or meets it too squarely to slide (more than 90 degrees less the
friction angle from it) and digs in: a nosedive. A round the spring has only
part-lifted is fed lower, so a tired spring nosedives too. A belt feeds from
above, the mirror image.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import Gun

FEED_TYPES = ("single_stack", "double_stack", "quad_stack", "drum", "belt", "dual_belt", "hand", "cylinder")
CAPACITY = {"single_stack": 10, "double_stack": 30, "quad_stack": 60, "drum": 75, "belt": 100, "dual_belt": 100, "hand": 15,
            "cylinder": 6}
# Magazine spring force on the top round, empty and full (N).
SPRING = {"single_stack": (8.0, 30.0), "double_stack": (10.0, 40.0), "quad_stack": (14.0, 60.0), "drum": (15.0, 55.0)}
SPRING_ROUND = 0.013  # kg, the round those springs are for
# Follower mass (kg); a drum's is its rotor, as felt at the feed lips.
FOLLOWER = {"single_stack": 0.008, "double_stack": 0.010, "quad_stack": 0.015, "drum": 0.12, "belt": 0.0,
            "dual_belt": 0.0, "hand": 0.0, "cylinder": 0.0}
# Depth of the stack per round, in rim diameters: a single column, two staggered columns,
# two side by side double stacks (under a double-stack funnel), and a drum's single-file track.
PITCH = {"single_stack": 1.0, "double_stack": 0.6, "quad_stack": 0.3, "drum": 1.0}
STAGGER = 0.4        # a staggered column's rounds sit this many rim diameters either side of centre
FUNNEL = 4           # quad stack: rounds at the top in a double stack
DRUM_TOWER = 4       # drum: rounds in the straight tower above the drum
LINK_PITCH = 1.2     # belt link pitch in rim diameters
BELT_RAISE = 0.5     # a belt's rounds lie this many rim diameters higher than a magazine's top round would
TRAY_ROUNDS = 3     # belt rounds in the feed tray, moved along with the hanging belt
PRESENT = 0.2        # the top round rises this many rim diameters when the bolt clears it
CATCH = 0.5          # the bolt face catches the rim once it has risen this share of that
RAMP_FRICTION = 0.3  # bullet on the feed ramp
BRASS = 8500.0       # kg/m^3
G = 9.81


def capacity(gun: Gun) -> int:
    """Rounds it holds besides the one in the chamber (a revolver's: besides the one under the hammer)."""
    f = gun.feed
    if cylinder(gun):
        return chambers(gun) - 1
    return int(f.capacity) if f.capacity is not None else CAPACITY[f.type]


def chambers(gun: Gun) -> int:
    """A revolver's chambers."""
    f = gun.feed
    return int(f.capacity) if f.capacity is not None else CAPACITY["cylinder"]


def belt(gun: Gun) -> bool:
    return gun.feed.type in ("belt", "dual_belt")


def hand(gun: Gun) -> bool:
    """Loaded by hand, a round at a time: nothing in the gun feeds it."""
    return gun.feed.type == "hand"


def cylinder(gun: Gun) -> bool:
    """A revolver's cylinder: each round has its own chamber, turned in line with the bore."""
    return gun.feed.type == "cylinder"


def case_mass(gun: Gun) -> float:
    """The metal of the case that is left after the shot (kg): the whole case, or a combustible case's stub base."""
    from .config import CASE_MATERIALS
    c = gun.case
    density = CASE_MATERIALS.get(c.material, BRASS)
    head = math.pi / 4 * c.rim_diameter**2 * c.head_thickness * 0.7
    if c.combustible:
        # The stub: the head, and a wall up to stub_length.
        wall = math.pi * c.base_diameter * max(c.stub_length - c.head_thickness, 0.0) * c.body_wall * 1.5
        return density * (head + wall)
    neck_d = gun.barrel.bore_diameter + 2 * c.neck_wall
    body = math.pi * 0.5 * (c.base_diameter + c.shoulder_diameter) * c.shoulder_position * c.body_wall * 1.2
    neck = math.pi * neck_d * max(c.length - c.shoulder_position, 0.0) * c.neck_wall
    return density * (body + neck + head)


def round_mass(gun: Gun) -> float:
    """A loaded round (kg): the projectile, the charge (a combustible case's body counted in it) and the case's metal."""
    return gun.projectile.mass + gun.propellant.charge_mass + case_mass(gun)


def spring(gun: Gun, rounds: int) -> float:
    """Magazine spring force on the top round (N) with `rounds` in the magazine."""
    f = gun.feed
    # A magazine's spring is made for its cartridge: the defaults are for 5.56 mm, stronger for heavier rounds.
    scale = max(1.0, round_mass(gun) / SPRING_ROUND)
    empty, full = (scale * v for v in SPRING.get(f.type, (0.0, 0.0)))
    empty = f.spring_empty if f.spring_empty is not None else empty
    full = f.spring_full if f.spring_full is not None else full
    return empty + (full - empty) * rounds / max(capacity(gun), 1)


def stack_mass(gun: Gun, rounds: int) -> float:
    """What the magazine spring has to lift (kg): the follower and every round left."""
    f = gun.feed
    follower = f.follower_mass if f.follower_mass is not None else FOLLOWER[f.type]
    return follower + rounds * round_mass(gun)


def link_pitch(gun: Gun) -> float:
    return LINK_PITCH * gun.case.rim_diameter


def belt_load(gun: Gun, rounds: int) -> tuple[float, float]:
    """Belt: (tension in N from the hanging belt, mass in kg the feed slide moves)."""
    f = gun.feed
    each = round_mass(gun) + f.link_mass
    hanging = min(rounds, f.belt_hang / link_pitch(gun))
    return hanging * each * G, (hanging + min(rounds, TRAY_ROUNDS)) * each


def belt_cam(gun: Gun, stroke: float) -> tuple[float, float]:
    """Carrier travel (m) where the feed cam starts and stops drawing the belt."""
    f = gun.feed
    start = f.belt_cam_start if f.belt_cam_start is not None else 0.2 * stroke
    length = f.belt_cam if f.belt_cam is not None else 0.35 * stroke
    return start, min(start + length, 0.95 * stroke)


def geometry(gun: Gun) -> dict:
    """Where the next round is presented, and the chamber and ramp it has to find.

    drop: the round's axis at the head from the bore (m, - below); present: how far the
    spring lifts it once the bolt clears it; angle: the feed angle (rad, + nose up).
    """
    c, f = gun.case, gun.feed
    d = c.rim_diameter
    bolt_r = max(d / 2 + 2.2e-3, c.base_diameter / 2 * 1.3)   # as the 3D view draws the bolt
    sign = -1.0 if belt(gun) else 1.0                         # the round comes from below (+1) or above
    loose = hand(gun) or cylinder(gun)
    present = PRESENT * d if not (belt(gun) or loose) else 0.0
    under = bolt_r + d / 2                                    # held against the bolt's side
    if belt(gun):
        drop = under = under + BELT_RAISE * d                 # the tray sits clear over the receiver
    elif loose:
        drop = under = 0.0                                    # rammed (or loaded) straight in along the bore
    else:
        drop, under = -(under - present), -under
    if f.feed_angle is not None:
        angle = sign * math.radians(f.feed_angle)
    else:
        angle = math.asin(min(-drop / c.overall_length, 0.9))
    return {
        "sign": sign, "rim": d, "present": present, "drop": drop, "under": under,
        "angle": angle, "auto_angle": f.feed_angle is None,
        "mouth": c.base_diameter / 2 + 0.05e-3,
        "tip": max(gun.projectile.meplat_diameter / 2, 0.3e-3),
        "ramp": math.radians(f.ramp_angle),
        "face": c.rim_thickness + 0.6e-3,                     # the barrel's rear face, from the bolt face closed
        "oal": c.overall_length,
    }


def check(geo: dict, lift: float = 1.0, feed_at: float | None = None) -> dict:
    """What the round does as the bolt drives it, lifted `lift` (0..1) of the way.

    Returns {"jam": None | "stub" | "nosedive", "detail", "angle", "tip" (m from the bore axis
    as the tip reaches the barrel), "incidence" (rad it meets the ramp at, or None), "travel"
    (m the bolt drives it before a jam)}.
    """
    s, oal = geo["sign"], geo["oal"]
    # Measured towards the feeding side being negative (a belt is mirrored).
    y = s * geo["drop"] - (1 - lift) * geo["present"]
    th = s * geo["angle"]
    tip = y + oal * math.sin(th)
    clear = geo["mouth"] - geo["tip"]
    foot = s * geo["under"]                    # the ramp's foot: where the top round lies under the bolt
    feed_at = oal + 3e-3 if feed_at is None else feed_at
    tip_x = -feed_at + oal * math.cos(th)      # where the tip is as the bolt starts to drive the round
    ramp = geo["ramp"]
    deg = math.degrees(th)
    out = {"jam": None, "detail": "", "angle": geo["angle"], "tip": s * tip, "incidence": None, "travel": 0.0}
    side, other = ("above", "below") if s > 0 else ("below", "above")
    if tip > clear:
        out.update(jam="stub", travel=max(geo["face"] - tip_x, 0.5e-3),
                   detail=f"the bullet's tip stubbed on the barrel face {side} the chamber: "
                          f"a {deg:.1f}° feed angle is too steep")
        return out
    if tip >= -clear:
        return out
    if tip < foot:
        x_foot = geo["face"] - (-clear - foot) / math.tan(ramp)
        out.update(jam="nosedive", travel=max(x_foot - tip_x, 0.5e-3),
                   detail=f"the bullet's nose dived under the feed ramp into the receiver {other} the chamber: "
                          f"fed at {deg:.1f}°{' and only part lifted' if lift < 1 else ''}, it is too low")
        return out
    incidence = ramp - th
    out["incidence"] = incidence
    if incidence > math.pi / 2 - math.atan(RAMP_FRICTION):
        x_c = geo["face"] - (-clear - tip) / math.tan(ramp)
        out.update(jam="nosedive", travel=max(x_c - tip_x, 0.5e-3),
                   detail=f"the bullet's nose dug into the feed ramp: it met the {math.degrees(ramp):.0f}° ramp "
                          f"at {math.degrees(incidence):.0f}°, too square to slide up it")
    return out
