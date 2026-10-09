"""Muzzle flash and smoke: the gas that leaves the muzzle, solved in 2D out into the air.

The bore's blowdown (fluid.py) says what leaves the muzzle, moment by moment.
That gas is fed into an axisymmetric grid (axisym.py) holding the end of the
barrel, the muzzle device if there is one (drawn as devices.py draws it), and
the air out to tens of bores around it. What the flash and smoke look like then
follows from the flow:

* Primary flash: the gas leaving the muzzle is still hot (it was at the flame
  temperature a millisecond ago). It glows as it bursts out, then dims as it
  expands in the jet.
* Intermediate flash: the under-expanded jet ends in a Mach disk, where the
  gas is shocked back up nearly to its stagnation temperature.
* Secondary flash: the propellant gas is fuel-rich (CO, H2; see
  propellants.PRODUCTS). Where it mixes with air and is still hot enough, it
  reignites and burns, and the fireball can outshine everything else. The
  burning is axisym.Afterburn's one-step reaction, so nothing decides whether
  it happens except temperature and mixing, and a flash suppressant in the
  propellant, whose potassium slows the reaction where the gas carries it.
* A brake turns the jet out of its vents; a suppressor holds the gas in its
  chambers, cools it on the baffles, and burns away the oxygen of the air
  inside (the first-round pop), so what comes out is late, slow, cool and
  short of oxygen.
* Smoke: what's visible of it is carried by the propellant gas (particles from
  the primer and the grains, and water that condenses as it cools), so it
  goes where the propellant gas goes. A flash suppressant's salt adds to the
  particles (PlumeResult.smoke).

The grid is fine round the muzzle and the device and grows by GROWTH per cell
away from them, so it can reach the fireball at little cost. It is solved
for solver.plume_time after exit. Frames of the temperature and the
propellant gas's density are kept for the 3D view, densely at first, when
the flash changes fastest.

After the window, the cloud is a puff: a blob of gas with the momentum the
jet gave it, slowing as it takes in air. A momentum puff's size grows as
t^(1/4) (Richards 1965), so the view carries the last frame on by scaling it
up about the exit at the rate it was growing when the window closed, thinning
it as it grows; its warmth lifts it. Gas still in the bore or the device then
seeps out of the exit and rises (the trickle).
"""

from __future__ import annotations

import base64
import json
import math
import threading
from dataclasses import asdict, dataclass

import numpy as np

from . import devices, fluid
from .axisym import Afterburn, Axisymmetric
from .propellants import combustibles, inhibition, smokiness

GROWTH = 1.07        # each cell this much bigger than the last, away from the fine region
COARSEST = 8         # cells grow to at most this many fine cells across
FRAMES = 48          # snapshots of the field over the window
AMBIENT_TEMPERATURE = 288.15
WIEN = 0.014388 / 600e-9   # K, hc / (lambda k) for orange light: glow ~ exp(-WIEN / T)
GLOW_REFERENCE = 2500.0    # K, where the glow factor is 1
CLOUD_SHARE = 0.01         # propellant-gas mass fraction that counts as part of the cloud


def glow(T):
    """Visible emission per kg of propellant gas, relative to gas at GLOW_REFERENCE (Wien's law)."""
    return np.exp(-WIEN * (1 / np.maximum(T, 1.0) - 1 / GLOW_REFERENCE))


def edges(lo: float, a: float, b: float, hi: float, h: float) -> np.ndarray:
    """Face positions: cells of h over [a, b], growing by GROWTH outwards until past lo and hi."""
    fine = np.arange(round(a / h), round(b / h) + 1) * h

    def grow(start, limit, sign):
        out, x, size = [], start, h
        while (limit - x) * sign > 1e-12:
            size = min(size * GROWTH, COARSEST * h)
            x += sign * size
            out.append(x)
        return out

    return np.concatenate((grow(fine[0], lo, -1)[::-1], fine, grow(fine[-1], hi, 1)))


@dataclass
class PlumeGrid:
    h: float
    x_edges: np.ndarray
    r_edges: np.ndarray
    solid: np.ndarray
    open_x: np.ndarray
    open_r: np.ndarray
    inside: np.ndarray       # gas cells inside the device
    bore: np.ndarray         # gas cells inside the barrel
    inlet: np.ndarray        # bore cells held at the bore's exit state
    dims: dict


def plume_grid(gun) -> PlumeGrid:
    """The end of the barrel, the device, and the air out to where the flash and smoke reach."""
    bore = gun.barrel.bore_diameter
    rb = bore / 2
    h = rb / max(1, round(gun.solver.plume_resolution / 2))
    dims = devices.dimensions(gun)
    kind = dims["type"]
    r_muzzle = max(gun.barrel.muzzle_diameter / 2, rb + 2 * h)
    L = dims["length"] if kind != "none" else 0.0
    R = dims["outer_radius"] if kind != "none" else r_muzzle
    # Fine cells over the device and a few bores round it; a brake's jets also turn back.
    a = -(0.3 * L if kind == "brake" else 0.0) - 2 * bore
    b = L + 6 * bore
    xe = edges(a - 12 * bore, math.floor(a / h) * h, math.ceil(b / h) * h, L + 85 * bore, h)
    re = edges(0.0, 0.0, math.ceil((R + 1.5 * bore) / h) * h, R + (50 if kind == "brake" else 32) * bore, h)
    xc, rc = 0.5 * (xe[:-1] + xe[1:]), 0.5 * (re[:-1] + re[1:])
    X, Rr = np.meshgrid(xc, rc, indexing="ij")
    solid, open_x, open_r, _, inside, r_muzzle = devices.draw(gun, X, Rr, h)
    in_bore = (X < 0) & (Rr < rb)
    inlet = in_bore & (X < -2 * h)    # the bore up to two cells from the muzzle holds the bore's exit state
    # Where the gas comes out: the muzzle, a suppressor's or flash hider's front, or the middle of a brake's vents.
    origin = {"brake": 0.5 * L, "suppressor": L, "flash_hider": L}.get(kind, 0.0)
    dims.update(h=h, r_muzzle=r_muzzle, exit=L, origin=origin, nx=len(xc), nr=len(rc))
    return PlumeGrid(h, xe, re, solid, open_x, open_r, inside, in_bore, inlet, dims)


@dataclass
class PlumeResult:
    grid: PlumeGrid
    times: np.ndarray        # s after exit, of each frame
    temperature: np.ndarray  # K, (frames, nx, nr)
    propellant: np.ndarray   # kg/m^3 of propellant gas, (frames, nx, nr)
    glow: np.ndarray         # visible emission per frame, kg of propellant gas at GLOW_REFERENCE
    glow_x: np.ndarray       # m, emission-weighted distance from the muzzle per frame
    extent: np.ndarray       # m, (frames, 3): x from, x to, radius of what is hot or smoky
    cloud: dict              # the puff the view carries on after the window
    trickle: dict            # gas that seeps out of the exit afterwards
    afterburn: float         # J released by burning in the air
    heat: float              # J taken by the steel
    escaped: float           # share of the propellant gas that left the grid within the window
    peak_temperature: float  # K, hottest gas outside the bore and device
    steps: int
    seconds: float           # wall-clock time of the solve
    smoke: float = 1.0       # smoke per kg of propellant gas, relative to a propellant without suppressant
    burnt: np.ndarray | None = None  # J released by burning in the air by each frame's time (the sound's afterburn)


def simulate(gun, shot, ambient_pressure: float = fluid.ATMOSPHERE,
             ambient_temperature: float = AMBIENT_TEMPERATURE) -> PlumeResult:
    """Solve the plume of a shot from the fluid model with blowdown (shot.muzzle_flow)."""
    import time
    mf = shot.muzzle_flow
    if mf is None:
        raise ValueError("the plume needs the fluid model's blowdown (the projectile must leave the muzzle)")
    start = time.perf_counter()
    g = plume_grid(gun)
    prop = gun.propellant
    additive, share = prop.flash_suppressant, prop.suppressant_fraction
    fuel, heat, oxygen = combustibles(prop.composition, additive, share)
    s = Axisymmetric(g.h, 0.0, g.solid, g.open_x, g.open_r, prop.gas_constant, prop.gamma,
                     ambient_pressure, ambient_temperature, x_edges=g.x_edges, r_edges=g.r_edges,
                     afterburn=Afterburn(fuel, heat, oxygen, inhibition(additive, share)))

    # The bore's exit state over time, from the moment of exit. The axisymmetric gas is ideal: give it
    # the bore gas's internal energy, so it has the bore gas's temperature.
    t_in = np.concatenate(([0.0], mf.t - mf.exit_time))
    rho_in = np.concatenate(([mf.exit_density], mf.rho_exit))
    u_in = np.concatenate(([mf.exit_gas_velocity], mf.u_exit))
    p_in = np.concatenate(([mf.exit_pressure], mf.p_exit))
    e_in = p_in * (1 - prop.covolume * rho_in) / ((prop.gamma - 1) * rho_in)

    window = gun.solver.plume_time
    times = window * (np.arange(FRAMES) / (FRAMES - 1)) ** 1.5
    temps, props, sizes, burnt = [], [], [], []
    hidden = g.solid | g.bore
    # Light from inside a suppressor doesn't get out; a brake's chambers and a flash hider's bore
    # show through the slots.
    through = {"suppressor": 0.0, "brake": g.dims["vent_fraction"],
               "flash_hider": g.dims["vent_fraction"]}.get(g.dims["type"], 1.0)
    seen = np.where(hidden, 0.0, np.where(g.inside, through, 1.0)) * s.volume
    xc = s.xc[:, None] * np.ones_like(seen)
    reach = np.hypot(s.xc[:, None] - g.dims["origin"], s.rc[None, :])

    def snapshot():
        rho, u, v, p, Y, cv, rg = s.primitives()
        T = np.where(g.solid, ambient_temperature, p / (rho * rg))
        rp = np.where(hidden, 0.0, rho * Y)
        temps.append(T.astype(np.float32))
        props.append(rp.astype(np.float32))
        # The cloud's size: mean distance of its propellant gas from where it came out.
        m = rp * s.volume * ~g.inside
        sizes.append(float((m * reach).sum() / max(m.sum(), 1e-30)))
        burnt.append(s.burnt)

    t = 0.0
    for k, tf in enumerate(times):
        while t < tf - 1e-12:
            tm = t + 0.5 * s.max_dt()
            s.set_fixed(g.inlet, float(np.interp(tm, t_in, rho_in)), float(np.interp(tm, t_in, u_in)),
                        float(np.interp(tm, t_in, e_in)))
            t += s.step(tf - t)
        snapshot()

    T_all, rp_all = np.array(temps), np.array(props)
    emission = rp_all * glow(T_all) * seen[None]
    glow_total = emission.sum(axis=(1, 2))
    glow_x = (emission * xc[None]).sum(axis=(1, 2)) / np.maximum(glow_total, 1e-30)
    X = np.broadcast_to(s.xc[:, None], seen.shape)
    Rr = np.broadcast_to(s.rc[None, :], seen.shape)
    extent = []
    for T, rp in zip(T_all, rp_all):
        show = ((T > 800) | (rp > 1e-3)) & ~hidden
        extent.append([X[show].min(), X[show].max(), Rr[show].max()] if show.any() else [0.0, 0.0, 0.0])

    # The cloud at the end of the window: the propellant gas out in the air, and how fast it was growing.
    rho, u, v, p, Y, cv, rg = s.primitives()
    out = ~(hidden | g.inside)
    m_p = rho * Y * s.volume * out
    mass = float(m_p.sum())
    part = out & (Y > CLOUD_SHARE)
    m_all = rho * s.volume * part
    T = p / (rho * rg)
    size, last = sizes[-1], sizes[-2]
    growth = (size - last) / (times[-1] - times[-2])
    # A puff grows as (t - t0)^(1/4): its age since that virtual start is size / (4 growth).
    age = float(np.clip(size / (4 * growth), 2e-4, 0.05)) if growth > 0 else 0.05
    cloud = {"mass": mass, "origin": g.dims["origin"], "size": size, "age": age,
             "x": float((m_p * X).sum() / max(mass, 1e-30)),
             "velocity": float((m_all * u).sum() / max(m_all.sum(), 1e-30)),
             # Mean excess temperature of the cloud's gas over the air's, as a share of it: its buoyancy.
             "warmth": float((m_all * (T - ambient_temperature)).sum() / max(m_all.sum(), 1e-30) / ambient_temperature)}

    # What's still in the bore and the device, and what the bore lets out after the window, seeps out later.
    stored = float((rho * Y * s.volume * (g.inside | (g.bore & ~g.inlet))).sum())
    after = mf.t - mf.exit_time > window
    flow = np.maximum(mf.mdot[after], 0.0)
    dt = np.diff(np.concatenate(([window], mf.t[after] - mf.exit_time)))
    later = np.cumsum(flow * dt)
    total = stored + (float(later[-1]) if later.size else 0.0)
    if shot.device is not None:
        # The device lets its gas out slower than the bore fills it: time it by the device's outflow.
        dv = shot.device
        rel = dv.t - mf.exit_time
        left = dv.out_propellant[-1] - np.interp(window, rel, dv.out_propellant)
        reach = np.interp(window, rel, dv.out_propellant) + 0.63 * left
        tau = float(np.interp(reach, dv.out_propellant, rel)) - window if left > 0 else 0.0
    else:
        tau = float(np.interp(0.63 * later[-1], later, mf.t[after] - mf.exit_time)) - window \
            if later.size and later[-1] > 0 else 0.0
    trickle = {"mass": total, "tau": max(tau, 1e-3), "x": g.dims["exit"]}

    outside = ~(hidden | g.inside)
    return PlumeResult(
        grid=g, times=times, temperature=T_all, propellant=rp_all, glow=glow_total, glow_x=glow_x,
        extent=np.array(extent), cloud=cloud, trickle=trickle, afterburn=s.burnt, heat=s.heat,
        escaped=float(s.out[4] / max(mass + stored + s.out[4], 1e-30)),
        peak_temperature=float(T_all[:, outside].max()), steps=s.steps,
        seconds=time.perf_counter() - start, smoke=smokiness(additive, share), burnt=np.array(burnt))


_cache: dict = {}
_cache_lock = threading.Lock()


def simulate_cached(gun, blowdown_time: float, ambient_pressure: float = fluid.ATMOSPHERE) -> tuple:
    """simulate() on the cached fluid shot, remembered for the last couple of guns. Returns (plume, shot)."""
    key = fluid._cache_key(gun, blowdown_time, ambient_pressure)
    with _cache_lock:
        if key not in _cache:
            shot = fluid.simulate_cached(gun, blowdown_time=blowdown_time, ambient_pressure=ambient_pressure)
            if not shot.left_muzzle:
                raise ValueError("the projectile did not leave the muzzle, so there is no flash or smoke")
            if len(_cache) >= 2:
                _cache.pop(next(iter(_cache)))
            _cache[key] = (simulate(gun, shot, ambient_pressure), shot)
        return _cache[key]


def _bytes(a: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode("ascii")


def to_json(r: PlumeResult, shot) -> dict:
    """The plume for the 3D view.

    frames: base64 bytes, frames + 1 layers of nr rows of nx cells, two bytes per cell: the
    temperature, (T - 250 K) / 3000 K * 255, and the propellant gas's density,
    (log10(kg/m^3) + 5) / 7 * 255 (0 = none). The extra last layer is the cloud carried on
    after the window: the last frame without the gas still in the bore or the device.
    Lengths are in mm, times in s after exit.
    """
    g = r.grid
    held = g.inside | g.bore | g.solid
    T = np.concatenate((r.temperature, np.where(held, AMBIENT_TEMPERATURE, r.temperature[-1])[None]))
    rp = np.concatenate((r.propellant, np.where(held, 0.0, r.propellant[-1])[None]))
    t8 = np.clip((T - 250.0) / 3000.0 * 255.0 + 0.5, 0, 255).astype(np.uint8)
    p8 = np.where(rp > 1e-5, np.clip((np.log10(np.maximum(rp, 1e-5)) + 5) / 7 * 255 + 0.5, 1, 255), 0).astype(np.uint8)
    cells = np.stack((t8, p8), axis=-1).transpose(0, 2, 1, 3)   # (layers, nr, nx, 2)

    # The bore gas's temperature along the column, thinned to what the view needs.
    t_gas = np.array([t for t, _ in shot.bore_gas])
    exit_t = shot.muzzle_time
    want = np.concatenate((np.linspace(0, exit_t, 60), exit_t + np.geomspace(2e-6, 0.02, 90)))
    pick = np.unique(np.clip(np.searchsorted(t_gas, want), 0, len(t_gas) - 1))
    mm = lambda v: float(v) * 1e3
    return {
        "x_edges": (g.x_edges * 1e3).tolist(),
        "r_edges": (g.r_edges * 1e3).tolist(),
        "nx": int(g.dims["nx"]), "nr": int(g.dims["nr"]), "layers": int(cells.shape[0]),
        "frames": _bytes(cells),
        "times": r.times.tolist(),
        "glow": r.glow.tolist(),
        "glow_x": (r.glow_x * 1e3).tolist(),
        "extent": (r.extent * 1e3).tolist(),
        "cloud": {**r.cloud, "origin": mm(r.cloud["origin"]), "size": mm(r.cloud["size"]), "x": mm(r.cloud["x"])},
        "trickle": {**r.trickle, "x": mm(r.trickle["x"])},
        "afterburn": r.afterburn,
        "heat": r.heat,
        "escaped": r.escaped,
        "peak_temperature": r.peak_temperature,
        "smoke": r.smoke,
        "steps": r.steps,
        "seconds": r.seconds,
        "muzzle_time": exit_t,
        "bore": {"t": t_gas[pick].tolist(), "T": np.round(np.array([shot.bore_gas[i][1] for i in pick])).tolist()},
    }
