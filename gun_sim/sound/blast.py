"""Muzzle blast: compressible flow in the air around the muzzle.

The gas that leaves the muzzle (from the bore blowdown in gun_sim.fluid, plus
the air the projectile pushes out ahead of itself) is fed into a small sphere
at the muzzle. The air around it is solved with the 1-D spherically symmetric
Euler equations, so the blast wave forms by itself: a shock front, the decay
behind it, the negative phase from the gas cloud over-expanding, and the
ringing of the bore as it empties. Pressure probes at several radii record
what a microphone there would hear.

* Two gases: air and propellant gas, each ideal with its own R and gamma.
  A conserved mass fraction Y tracks how much of each cell is propellant gas.
* Finite volumes on r in [0, R]: the centre is closed (zero area); the outer
  edge is a far-field (Riemann invariant) boundary, so the wave leaves the
  domain and the air beyond stays at ambient pressure.
* MUSCL reconstruction (minmod) of rho, u, p, Y with a Rusanov flux and Heun
  (SSP-RK2) time stepping: second order, so the shock stays a few cells thick.
* The geometric pressure term p dA/dr keeps a uniform gas at rest exactly at rest.

* The secondary flash: the fuel-rich propellant gas burns in the air (solved
  in 2D by gun_sim.plume), and its heat, released over the fireball, adds a
  slower, deeper push to the blast: the boom behind the crack.

The real near field is not spherical (there is a jet, and the gun is in the
way); the directivity this misses is added later in propagation.py.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .settings import GAMMA_AIR, R_AIR


@dataclass
class BlastSource:
    """Cumulative amounts that have entered the source sphere by time t."""
    t: np.ndarray           # s, increasing
    mass: np.ndarray        # kg
    energy: np.ndarray      # J, total (internal + kinetic + flow work)
    propellant: np.ndarray  # kg of the mass that is propellant gas (the rest is air)
    # Heat released by the propellant gas burning in the air (the secondary flash), cumulative J on its
    # own time base, and the radius of the fireball it is released over.
    heat_t: np.ndarray | None = None
    heat: np.ndarray | None = None
    heat_radius: float = 0.0


@dataclass
class BlastResult:
    radii: np.ndarray       # m, probe radii
    time: np.ndarray        # s, from ignition (non-uniform: one sample per solver step)
    pressure: np.ndarray    # Pa gauge, shape (len(radii), len(time))
    source_radius: float    # m
    steps: int


def simulate_blast(source: BlastSource, gas_constant: float, gas_gamma: float,
                   ambient_pressure: float, ambient_temperature: float,
                   radius: float, cells: int, t_end: float, source_radius: float,
                   probes, cfl: float = 0.45) -> BlastResult:
    n = cells
    dx = radius / n
    r_f = np.arange(n + 1) * dx
    r_c = (np.arange(n) + 0.5) * dx
    area = 4 * np.pi * r_f**2
    vol = 4 / 3 * np.pi * (r_f[1:]**3 - r_f[:-1]**3)
    d_area = np.diff(area)

    cv_a = R_AIR / (GAMMA_AIR - 1)
    cv_p = gas_constant / (gas_gamma - 1)

    def eos(rho, Y, e):
        cv = cv_a + Y * (cv_p - cv_a)
        rg = R_AIR + Y * (gas_constant - R_AIR)
        return cv, rg

    # Ambient air at rest.
    rho_a = ambient_pressure / (R_AIR * ambient_temperature)
    U = np.zeros((4, n))
    U[0] = rho_a
    U[2] = ambient_pressure / (GAMMA_AIR - 1)

    # Source: cells inside source_radius (at least two).
    n_src = max(2, int(np.searchsorted(r_c, source_radius)))
    v_src = vol[:n_src].sum()

    probes = np.asarray(probes, dtype=float)
    pi = np.clip(np.searchsorted(r_c, probes) - 1, 0, n - 2)
    pw = np.clip((probes - r_c[pi]) / dx, 0.0, 1.0)

    def primitives(U):
        rho = U[0]
        u = U[1] / rho
        Y = np.clip(U[3] / rho, 0.0, 1.0)
        e = np.maximum(U[2] / rho - 0.5 * u * u, 1.0)
        cv, rg = eos(rho, Y, e)
        p = rho * e * rg / cv
        return rho, u, p, Y, cv, rg

    c_a = np.sqrt(GAMMA_AIR * ambient_pressure / rho_a)
    entropy_a = ambient_pressure / rho_a**GAMMA_AIR
    g1 = GAMMA_AIR - 1

    def far_field(w):
        """Ghost state at the outer edge from Riemann invariants: the outgoing one
        from inside, the incoming one from still ambient air. Outgoing waves leave
        without reflecting, and the domain cannot drift away from ambient pressure."""
        rho, u, p, Y = w
        out = u + 2 * np.sqrt(GAMMA_AIR * p / rho) / g1
        inc = -2 * c_a / g1
        ub = 0.5 * (out + inc)
        cb = 0.25 * g1 * (out - inc)
        s = p / rho**GAMMA_AIR if ub >= 0 else entropy_a
        rb = (cb * cb / (GAMMA_AIR * s)) ** (1 / g1)
        return np.array([[rb], [ub], [s * rb**GAMMA_AIR], [Y]])

    def flux_side(rho, u, p, Y):
        cv, rg = eos(rho, Y, None)
        E = p * cv / rg + 0.5 * rho * u * u
        c = np.sqrt((1 + rg / cv) * p / rho)
        cons = np.stack((rho, rho * u, E, rho * Y))
        flux = np.stack((rho * u, rho * u * u + p, (E + p) * u, rho * Y * u))
        return cons, flux, np.abs(u) + c

    def rhs(U):
        rho, u, p, Y, cv, rg = primitives(U)
        W = np.stack((rho, u, p, Y))
        d = np.diff(W, axis=1)
        a, b = d[:, :-1], d[:, 1:]
        slope = np.zeros_like(W)
        slope[:, 1:-1] = 0.5 * (np.sign(a) + np.sign(b)) * np.minimum(np.abs(a), np.abs(b))
        WL = W[:, :-1] + 0.5 * slope[:, :-1]   # interior faces 1..n-1
        WR = W[:, 1:] - 0.5 * slope[:, 1:]
        WL = np.concatenate((WL, W[:, -1:]), axis=1)
        WR = np.concatenate((WR, far_field(W[:, -1])), axis=1)
        cL, fL, sL = flux_side(*WL)
        cR, fR, sR = flux_side(*WR)
        s = np.maximum(sL, sR)
        F = 0.5 * (fL + fR) - 0.5 * s * (cR - cL)
        AF = F * area[1:]
        net = np.empty((4, n))
        net[:, 0] = AF[:, 0]                   # the centre face has zero area
        net[:, 1:] = AF[:, 1:] - AF[:, :-1]
        dU = -net / vol
        dU[1] += p * d_area / vol
        return dU, u, p, np.sqrt((1 + rg / cv) * p / rho)

    t_src, m_src, e_src, y_src = source.t, source.mass, source.energy, source.propellant
    started = np.nonzero(m_src > 0)[0]
    t = float(t_src[started[0] - 1]) if started.size and started[0] > 0 else float(t_src[0])
    m_prev, e_prev, y_prev = (np.interp(t, t_src, a) for a in (m_src, e_src, y_src))
    burning = source.heat is not None and source.heat.size and source.heat[-1] > 0
    if burning:
        n_heat = max(n_src, int(np.searchsorted(r_c, min(source.heat_radius, 0.45 * radius))))
        v_heat = vol[:n_heat].sum()
        q_prev = float(np.interp(t, source.heat_t, source.heat, left=0.0))

    times = []
    rec = []
    steps = 0
    while t < t_end:
        k1, u, p, c = rhs(U)
        dt = min(cfl * dx / np.max(np.abs(u) + c), t_end - t)
        rec.append(p[pi] * (1 - pw) + p[pi + 1] * pw)
        times.append(t)

        U1 = U + dt * k1
        k2 = rhs(U1)[0]
        U = 0.5 * (U + U1 + dt * k2)
        t += dt
        steps += 1

        # Gas from the muzzle enters the source sphere (operator split).
        m_now, e_now, y_now = (np.interp(t, t_src, a) for a in (m_src, e_src, y_src))
        dm, de, dy = m_now - m_prev, e_now - e_prev, y_now - y_prev
        m_prev, e_prev, y_prev = m_now, e_now, y_now
        if dm > 0:
            U[0, :n_src] += dm / v_src
            U[2, :n_src] += max(de, 0.0) / v_src
            U[3, :n_src] += min(max(dy, 0.0), dm) / v_src
        elif dm < 0:
            # Air drawn back into the bore: take it from the source cells as they are.
            m_cells = U[0, :n_src] @ vol[:n_src]
            U[:, :n_src] *= 1 - min(-dm / m_cells, 0.5)
        if burning:
            # The fireball's heat, spread evenly through its volume.
            q_now = float(np.interp(t, source.heat_t, source.heat, left=0.0))
            if q_now > q_prev:
                U[2, :n_heat] += (q_now - q_prev) / v_heat
            q_prev = q_now

    pressure = np.array(rec).T - ambient_pressure
    return BlastResult(radii=probes, time=np.array(times), pressure=pressure,
                       source_radius=float(r_f[n_src]), steps=steps)
