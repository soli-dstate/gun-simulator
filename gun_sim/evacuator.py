"""Bore evacuator (fume extractor): a reservoir round the barrel that clears the fumes out of the bore.

A tank gun's breech opens into the turret, so the propellant gas left in the
bore would come back at the crew. The evacuator is a canister round the
barrel, joined to the bore by a ring of small nozzles that lean forwards, by
`barrel.evacuator_angle`, towards the muzzle.

* Charging. Once the projectile has passed the nozzles, the bore gas flows in
  through them (an orifice, choked or subsonic either way, with the gas the
  solvers record there: the bore gas at `evacuator_position`) and fills the
  reservoir.
* Blowing. When the bore has blown down below the reservoir's pressure, the
  reservoir empties back through the same nozzles, as jets pointing up the
  bore. Their forward momentum flux J = mdot v_jet cos(angle) drives the gas in
  the bore out of the muzzle like an ejector pump. With the breech shut it
  only pushes out the gas ahead of the nozzles.
* Scavenging. Once the breech opens, air comes in at the breech and the jets
  draw it up the bore at the speed U at which they balance the flow's
  momentum and losses, J = rho_air A U^2 (1 + K_in + f L / D): the entry
  loss at the open breech and the bore's friction. The bore behind the
  nozzles (the breech end, where the fumes would come back) is swept in its
  length over U. If the evacuator has stopped blowing by the time the breech
  opens, the fumes come back into the turret.

The reservoir's gas is ideal (the propellant's gamma and R) and keeps its
heat, the bore is at ambient pressure once the solved blowdown is over, and
the gas the evacuator takes from the bore while the projectile is in it does
not change the shot (it is a few per cent of the charge, taken behind the
projectile late in its travel).
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np

from .action import AIR_TEMPERATURE, AMBIENT, ORIFICE_CD, _exchange

if TYPE_CHECKING:
    from .config import Gun
    from .results import ShotResult

AIR_DENSITY = 1.2       # kg/m^3
ENTRY_LOSS = 0.5        # loss coefficient of air coming in at the open breech
BORE_FRICTION = 0.02    # Darcy friction factor of the (smooth) bore, for the induced flow
DURATION = 4.0          # s after the shot that the reservoir is followed for
SLOW_DT = 1e-3          # s, steps after the solved blowdown
MIN_FLOW = 0.5          # m/s: the induced flow is taken to have stopped below this
OUTPUT_POINTS = 400


def fitted(gun: Gun) -> bool:
    return bool(gun.barrel.evacuator_position)


def nozzle_area(gun: Gun) -> float:
    b = gun.barrel
    return int(b.evacuator_nozzles) * math.pi / 4 * b.evacuator_nozzle_diameter**2


def _jet_speed(p_up: float, t_up: float, p_down: float, gamma: float, r_gas: float) -> float:
    """Speed of the gas leaving a nozzle (m/s): sonic if choked, else from the isentropic expansion."""
    ratio = p_down / p_up
    critical = (2 / (gamma + 1)) ** (gamma / (gamma - 1))
    if ratio <= critical:
        return math.sqrt(gamma * r_gas * t_up * 2 / (gamma + 1))
    return math.sqrt(max(2 * gamma / (gamma - 1) * r_gas * t_up * (1 - ratio ** ((gamma - 1) / gamma)), 0.0))


def induced_flow(gun: Gun, thrust: float) -> float:
    """Speed (m/s) at which jets of forward momentum flux `thrust` (N) draw air up the bore with the breech open."""
    if thrust <= 0:
        return 0.0
    b = gun.barrel
    length = gun.case.length + b.travel
    losses = 1 + ENTRY_LOSS + BORE_FRICTION * length / b.bore_diameter
    return math.sqrt(thrust / (AIR_DENSITY * b.bore_area * losses))


def simulate(gun: Gun, shot: ShotResult, open_time: float | None = None) -> dict | None:
    """The evacuator through a shot and after it. open_time: s from ignition the breech opens (None: it stays shut).

    Returns None without an evacuator, else: time (s), pressure (Pa) in the reservoir, flow (m/s, the
    bore flow the jets draw with the breech open), the peak pressure and the gas taken in (kg), how long
    it blows (s from ignition, while the flow it could draw is above MIN_FLOW), and, if the breech opens,
    the flow then, how long the breech end of the bore takes to sweep clear, and whether it is clear.
    """
    if not fitted(gun) or shot.loads is None:
        return None
    b, loads = gun.barrel, shot.loads
    gamma, r_gas = gun.propellant.gamma, gun.propellant.gas_constant
    cv = r_gas / (gamma - 1)
    area, volume = nozzle_area(gun), b.evacuator_volume
    lean = math.cos(math.radians(b.evacuator_angle))
    m = AMBIENT * volume / (r_gas * AIR_TEMPERATURE)
    e = m * cv * AIR_TEMPERATURE
    t_solved = float(loads.t[-1])
    # The bore gas at the nozzles while it was solved, then still air at the bore's last temperature.
    times = list(loads.t)
    t, k = float(loads.t[0]), 0
    t_end = DURATION
    peak, taken = AMBIENT, 0.0
    out_t, out_p, out_u = [], [], []
    blow_end = None
    while t < t_end:
        if k + 1 < len(times):
            dt = times[k + 1] - times[k]
            pb, tb = float(loads.port_pressure[k]), float(loads.port_temperature[k])
            k += 1
        else:
            dt = SLOW_DT
            pb, tb = AMBIENT, float(loads.port_temperature[-1])
        dt = max(dt, 1e-9)
        p = (gamma - 1) * e / volume
        temp = p * volume / (m * r_gas)
        flow, enthalpy = _exchange(area, ORIFICE_CD, pb, tb, p, temp, gamma, r_gas)   # + into the reservoir
        m = max(m + flow * dt, 1e-12)
        e = max(e + flow * enthalpy * dt, 1e-9)
        if flow > 0:
            taken += flow * dt
        peak = max(peak, p)
        # Blowing out: the jets' forward momentum, and the bore flow it would draw with the breech open.
        thrust = -flow * _jet_speed(p, temp, pb, gamma, r_gas) * lean if flow < 0 else 0.0
        drawn = induced_flow(gun, thrust)
        if t > t_solved and drawn < MIN_FLOW and blow_end is None:
            blow_end = t
            t_end = min(t_end, t + 0.2)
        out_t.append(t)
        out_p.append(p)
        out_u.append(drawn)
        t += dt
    out_t, out_p, out_u = np.array(out_t), np.array(out_p), np.array(out_u)
    idx = np.unique(np.searchsorted(out_t, np.linspace(out_t[0], out_t[-1], OUTPUT_POINTS)).clip(0, len(out_t) - 1))
    result = {
        "time": out_t[idx], "pressure": out_p[idx], "flow": out_u[idx],
        "peak_pressure": peak, "charge": taken, "blow_end": blow_end if blow_end is not None else float(out_t[-1]),
        "open_time": open_time, "open_flow": None, "sweep_time": None, "clear": None,
    }
    if open_time is not None:
        u_open = float(np.interp(open_time, out_t, out_u))
        behind = gun.case.length + b.evacuator_position    # the breech face to the nozzles
        result["open_flow"] = u_open
        if u_open > MIN_FLOW:
            # Integrate the drawn flow from the opening until it has swept the breech end of the bore.
            after = out_t >= open_time
            swept = np.concatenate(([0.0], np.cumsum(out_u[after][1:] * np.diff(out_t[after]))))
            reach = np.searchsorted(swept, behind)
            if reach < len(swept):
                result["sweep_time"] = float(out_t[after][reach] - open_time)
        result["clear"] = result["sweep_time"] is not None
    return result


def summary(ev: dict) -> str:
    line = (f"  bore evacuator       charged to {ev['peak_pressure'] / 1e6:.2f} MPa with {ev['charge'] * 1e3:.0f} g of gas, "
            f"blowing until {ev['blow_end']:.2f} s")
    if ev["open_time"] is not None:
        if ev["clear"]:
            line += (f"; the breech opens at {ev['open_time']:.2f} s and the jets draw air up the bore at "
                     f"{ev['open_flow']:.1f} m/s, sweeping its breech end clear in {ev['sweep_time']:.2f} s")
        else:
            line += f"; the breech opens at {ev['open_time']:.2f} s with too little flow left: fumes come back in"
    return line


def to_json(ev: dict | None) -> dict | None:
    if ev is None:
        return None
    return {k: (v.tolist() if isinstance(v, np.ndarray) else v) for k, v in ev.items()}
