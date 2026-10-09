"""Compiled inner loops of the flow solvers.

Both solvers take thousands of small steps, and in NumPy each step is dozens of
calls on arrays of a few hundred values: the time goes on the calls, not the
arithmetic. Numba compiles these loops to machine code once (cached on disk,
per user, so later runs and the worker processes load it instead).

They compute exactly what the NumPy versions in fluid.py and axisym.py do, and
the tests hold the two together. Set GUN_SIM_JIT=0 (or go without Numba) to use
the NumPy versions instead.
"""

from __future__ import annotations

import math
import os
import types

import numpy as np

# The 2-D grids are a few thousand cells: past about 8 threads, starting them costs more than they save.
os.environ.setdefault("NUMBA_NUM_THREADS", str(min(8, os.cpu_count() or 1)))

try:
    import numba
    from numba import prange
except ImportError:  # pragma: no cover - numba is a dependency, but the NumPy path still works without it
    numba = None
    prange = range

ENABLED = numba is not None and os.environ.get("GUN_SIM_JIT", "").strip() != "0"

R_AIR = 287.05  # as axisym.R_AIR


def _jit(fn=None, parallel=False):
    if fn is None:
        return lambda f: _jit(f, parallel)
    if numba is None:
        return fn
    return numba.njit(cache=True, nogil=True, error_model="numpy", parallel=parallel)(fn)


# ---------- quasi-1D bore (fluid.py) ----------

@_jit
def _van_leer(a, b):
    prod = a * b
    return 2 * prod / (a + b) if prod > 0 else 0.0


@_jit
def bore_fluxes(q, u, p, e, c, w, wall, ghost):
    """fluid._faces(): HLLC fluxes at the n+1 nodes from MUSCL (van Leer) states.

    wall: the right end is the projectile, moving at w[-1]; otherwise ghost is
    the open muzzle's outside state (q, u, p, e, c).
    Returns the mass, momentum and energy fluxes and the star pressure.
    """
    n = q.size
    prim = np.empty((5, n + 2))
    prim[0, 1:-1] = q
    prim[1, 1:-1] = u
    prim[2, 1:-1] = p
    prim[3, 1:-1] = e
    prim[4, 1:-1] = c
    for k in range(5):
        prim[k, 0] = prim[k, 1]
        prim[k, n + 1] = prim[k, n] if wall else ghost[k]
    prim[1, 0] = -prim[1, 1]
    if wall:
        prim[1, n + 1] = -prim[1, n] + 2 * w[n]
    # states either side of each face: left[:, i] and right[:, i] at node i
    left = np.empty((5, n + 1))
    right = np.empty((5, n + 1))
    for k in range(5):
        for i in range(n):
            half = 0.5 * _van_leer(prim[k, i + 1] - prim[k, i], prim[k, i + 2] - prim[k, i + 1])
            left[k, i + 1] = prim[k, i + 1] + half
            right[k, i] = prim[k, i + 1] - half
        left[k, 0] = right[k, 0]
        right[k, n] = left[k, n] if wall else ghost[k]
    left[1, 0] = -right[1, 0]
    if wall:
        right[1, n] = -left[1, n] + 2 * w[n]

    fm = np.empty(n + 1)
    fp = np.empty(n + 1)
    fe = np.empty(n + 1)
    p_star = np.empty(n + 1)
    for i in range(n + 1):
        qL, uL, pL, eL, cL = left[0, i], left[1, i], left[2, i], left[3, i], left[4, i]
        qR, uR, pR, eR, cR = right[0, i], right[1, i], right[2, i], right[3, i], right[4, i]
        wi = w[i]
        EL = qL * (eL + 0.5 * uL * uL)
        ER = qR * (eR + 0.5 * uR * uR)
        sL = min(uL - cL, uR - cR)
        sR = max(uL + cL, uR + cR)
        mL = qL * (sL - uL)
        mR = qR * (sR - uR)
        s_star = (pR - pL + mL * uL - mR * uR) / (mL - mR)
        p_star[i] = pL + mL * (s_star - uL)
        if wi <= s_star:
            F0, F1, F2 = qL * uL, qL * uL * uL + pL, EL * uL + pL * uL
            if wi <= sL:
                fm[i], fp[i], fe[i] = F0 - wi * qL, F1 - wi * qL * uL, F2 - wi * EL
            else:
                r = mL / (sL - s_star)
                S0, S1, S2 = r, r * s_star, r * (EL / qL + (s_star - uL) * (s_star + pL / mL))
                fm[i] = F0 + sL * (S0 - qL) - wi * S0
                fp[i] = F1 + sL * (S1 - qL * uL) - wi * S1
                fe[i] = F2 + sL * (S2 - EL) - wi * S2
        else:
            F0, F1, F2 = qR * uR, qR * uR * uR + pR, ER * uR + pR * uR
            if wi <= sR:
                r = mR / (sR - s_star)
                S0, S1, S2 = r, r * s_star, r * (ER / qR + (s_star - uR) * (s_star + pR / mR))
                fm[i] = F0 + sR * (S0 - qR) - wi * S0
                fp[i] = F1 + sR * (S1 - qR * uR) - wi * S1
                fe[i] = F2 + sR * (S2 - ER) - wi * S2
            else:
                fm[i], fp[i], fe[i] = F0 - wi * qR, F1 - wi * qR * uR, F2 - wi * ER
    return fm, fp, fe, p_star


@_jit
def _volume_at(x, edges, cumulative, bore_area):
    """chamber.ChamberProfile.volume_at()"""
    out = np.interp(x, edges, cumulative)
    length = edges[-1]
    for i in range(x.size):
        out[i] += bore_area * max(x[i] - length, 0.0)
    return out


@_jit
def _area_at(x, edges, area_bins, bore_area):
    """chamber.ChamberProfile.area_at(), at one place"""
    k = np.searchsorted(edges, x, side="right") - 1
    return area_bins[k] if 0 <= k < area_bins.size else bore_area


@_jit
def bore_wall_losses(mass, mom, energy, rho, nodes, edges, area_bins, bore_area, dt, cv, gamma,
                     friction_factor, viscosity, prandtl, wall_temperature):
    """The friction and heat loss of fluid.simulate()'s wall_losses(), over dt.

    Returns the new momentum and energy, the heat each cell lost, the cells' diameters,
    and the momentum friction gave the barrel.
    """
    n = mass.size
    mom_new = np.empty(n)
    energy_new = np.empty(n)
    q = np.empty(n)
    diameter = np.empty(n)
    friction = 0.0
    st_prandtl = prandtl ** (-2 / 3)
    for i in range(n):
        d = math.sqrt(4 / math.pi * _area_at(0.5 * (nodes[i] + nodes[i + 1]), edges, area_bins, bore_area))
        diameter[i] = d
        u_old = mom[i] / mass[i]
        k_f = friction_factor / 8 * (4 / d) * abs(u_old)
        u_new = u_old / (1 + k_f * dt)
        mom_new[i] = mass[i] * u_new
        reynolds = max(rho[i] * abs(u_new) * d / viscosity, 1e3)
        stanton = 0.023 * reynolds ** -0.2 * st_prandtl
        k_h = stanton * (4 / d) * abs(u_new)
        t_gas = (energy[i] / mass[i] - 0.5 * u_new ** 2) / cv
        q[i] = mass[i] * cv * max(t_gas - wall_temperature, 0.0) * (1 - math.exp(-gamma * k_h * dt))
        energy_new[i] = energy[i] - q[i]
        friction += mass[i] * (u_old - u_new)
    return mom_new, energy_new, q, diameter, friction


@_jit
def bore_primitives(mass, mom, energy, nodes, grain_edges, unburnt, grains_move,
                    edges, cumulative, bore_area, gamma, b):
    """The gas state in each cell, around the unburnt grains (volume unburnt per grain slice).

    The primitives() of fluid.simulate(), for all but a two-phase bed.
    """
    n = mass.size
    v_cell = np.diff(_volume_at(nodes, edges, cumulative, bore_area))
    if grains_move:  # slices are the cells
        grains = unburnt
    else:  # spread each slice over the cells, evenly in volume
        acc = np.zeros(n + 1)
        acc[1:] = np.cumsum(unburnt)
        grains = np.diff(np.interp(_volume_at(nodes, edges, cumulative, bore_area),
                                   _volume_at(grain_edges, edges, cumulative, bore_area), acc))
    rho = np.empty(n)
    u = np.empty(n)
    e = np.empty(n)
    p = np.empty(n)
    c = np.empty(n)
    for i in range(n):
        rho[i] = mass[i] / (v_cell[i] - grains[i])
        u[i] = mom[i] / mass[i]
        e[i] = energy[i] / mass[i] - 0.5 * u[i] ** 2
        p[i] = (gamma - 1) * rho[i] * e[i] / (1 - b * rho[i])
        c[i] = math.sqrt(gamma * p[i] / ((mass[i] / v_cell[i]) * (1 - b * rho[i])))
    return v_cell, rho, u, e, p, c


@_jit
def bore_rhs(q, u, p, e, c, w, nodes, wall, ghost, edges, area_bins, bore_area):
    """fluid._bore_rhs(): the fluxes, the face areas, and the rates of change of the cell totals."""
    n = q.size
    fm, fp, fe, p_star = bore_fluxes(q, u, p, e, c, w, wall, ghost)
    area = np.empty(n + 1)
    for i in range(n):
        area[i] = _area_at(nodes[i], edges, area_bins, bore_area)
    area[n] = bore_area
    d_area = np.empty(n)
    d_mass = np.empty(n)
    d_mom = np.empty(n)
    d_energy = np.empty(n)
    wave = 0.0
    for i in range(n):
        d_area[i] = area[i + 1] - area[i]
        d_mass[i] = -(area[i + 1] * fm[i + 1] - area[i] * fm[i])
        d_mom[i] = -(area[i + 1] * fp[i + 1] - area[i] * fp[i]) + p[i] * d_area[i]
        d_energy[i] = -(area[i + 1] * fe[i + 1] - area[i] * fe[i])
        speed = abs(u[i] - 0.5 * (w[i] + w[i + 1])) + c[i]
        if not speed <= wave:  # NaN too, as np.max does, so a blow-up shows
            wave = speed
    return fm, fp, fe, p_star, area, d_area, d_mass, d_mom, d_energy, wave


# ---------- 2-D axisymmetric (axisym.py) ----------

@_jit
def _minmod(a, b):
    if a > 0:
        return max(0.0, min(a, b))
    if a < 0:
        return min(0.0, max(a, b))
    return 0.0


@_jit
def _hll(WL, WR, nv, normal, cva, cvp, rp, out):
    """HLL flux between states WL and WR (rho, u, v, p, Y(, fuel)), across a face whose
    normal velocity is W[normal] (1 = u, 2 = v). out gets the flux in (x, r) order."""
    tang = 3 - normal
    rho_l, un_l, ut_l, p_l, y_l = WL[0], WL[normal], WL[tang], WL[3], WL[4]
    rho_r, un_r, ut_r, p_r, y_r = WR[0], WR[normal], WR[tang], WR[3], WR[4]
    g1_l = (R_AIR + y_l * (rp - R_AIR)) / (cva + y_l * (cvp - cva))
    g1_r = (R_AIR + y_r * (rp - R_AIR)) / (cva + y_r * (cvp - cva))
    E_l = p_l / g1_l + 0.5 * rho_l * (un_l * un_l + ut_l * ut_l)
    E_r = p_r / g1_r + 0.5 * rho_r * (un_r * un_r + ut_r * ut_r)
    m_l, m_r = rho_l * un_l, rho_r * un_r
    c_l = math.sqrt((1 + g1_l) * p_l / rho_l)
    c_r = math.sqrt((1 + g1_r) * p_r / rho_r)
    sl = min(min(un_l - c_l, un_r - c_r), 0.0)
    sr = max(max(un_l + c_l, un_r + c_r), 0.0)
    inv = 1.0 / (sr - sl + 1e-30)
    wl, wr, wd = sr * inv, -sl * inv, sl * sr * inv
    out[0] = wl * m_l + wr * m_r + wd * (rho_r - rho_l)
    out[normal] = wl * (m_l * un_l + p_l) + wr * (m_r * un_r + p_r) + wd * (m_r - m_l)
    out[tang] = wl * m_l * ut_l + wr * m_r * ut_r + wd * (rho_r * ut_r - rho_l * ut_l)
    out[3] = wl * (E_l + p_l) * un_l + wr * (E_r + p_r) * un_r + wd * (E_r - E_l)
    for k in range(4, nv):
        out[k] = wl * m_l * WL[k] + wr * m_r * WR[k] + wd * (rho_r * WR[k] - rho_l * WL[k])


def _axisym_rhs(U, open_x, open_r, solid, fixed, area_x, area_r, d_area_r, volume, force_faces,
                out_right, out_left, out_top, size, p0, cva, cvp, rp):
    """axisym.Axisymmetric._rhs(): the time derivative of U, plus what left through the
    outer edges, the force on the device, and the largest wave speed / cell size.

    Compiled twice: axisym_rhs() on one thread, and axisym_rhs_parallel(), whose
    loops over x (the prange ones) share out over the cores, for the larger grids.
    """
    nv, nx, nr = U.shape
    W = np.empty((nv, nx, nr))
    p = np.empty((nx, nr))
    row_rate = np.zeros(nx)
    for i in prange(nx):
        rate_i = 0.0
        for j in range(nr):
            rho = float(U[0, i, j])
            u = U[1, i, j] / rho
            v = U[2, i, j] / rho
            Y = min(max(U[4, i, j] / rho, 0.0), 1.0)
            cv = cva + Y * (cvp - cva)
            rg = R_AIR + Y * (rp - R_AIR)
            e = max(U[3, i, j] / rho - 0.5 * (u * u + v * v), 1.0)
            pij = rho * rg / cv * e
            W[0, i, j], W[1, i, j], W[2, i, j], W[3, i, j], W[4, i, j] = rho, u, v, pij, Y
            if nv > 5:
                W[5, i, j] = min(max(U[5, i, j] / rho, 0.0), 1.0)
            p[i, j] = pij
            if not solid[i, j]:
                c = math.sqrt((1 + rg / cv) * pij / rho)
                speed = (abs(u) + abs(v) + 2 * c) / size[i, j]
                if not speed <= rate_i:  # NaN too, as np.max does
                    rate_i = speed
        row_rate[i] = rate_i
    rate = 0.0
    for i in range(nx):
        if not row_rate[i] <= rate:
            rate = row_rate[i]

    # Slopes per cell along x and r: minmod of the differences, which count as zero across shut faces.
    sx = np.empty((nv, nx, nr))
    sr = np.empty((nv, nx, nr))
    for i in prange(nx):
        for k in range(nv):
            for j in range(nr):
                dm = W[k, i, j] - W[k, i - 1, j] if i > 0 and open_x[i, j] > 0 else 0.0
                dp = W[k, i + 1, j] - W[k, i, j] if i < nx - 1 and open_x[i + 1, j] > 0 else 0.0
                sx[k, i, j] = _minmod(dm, dp)
                if j > 0:
                    dm = W[k, i, j] - W[k, i, j - 1] if open_r[i, j] > 0 else 0.0
                else:
                    dm = 2 * W[k, i, 0] if k == 2 else 0.0  # v against its mirror image on the axis
                dp = W[k, i, j + 1] - W[k, i, j] if j < nr - 1 and open_r[i, j + 1] > 0 else 0.0
                sr[k, i, j] = _minmod(dm, dp)

    # The flux through every face, and the pressure either side of it (which pushes on its shut part).
    FX = np.empty((nv, nx + 1, nr))
    px_l = np.empty((nx + 1, nr))
    px_r = np.empty((nx + 1, nr))
    for i in prange(nx + 1):
        WL = np.empty(nv)
        WR = np.empty(nv)
        F = np.empty(nv)
        for j in range(nr):
            for k in range(nv):
                WL[k] = W[k, i - 1, j] + 0.5 * sx[k, i - 1, j] if i > 0 else W[k, 0, j]
                WR[k] = W[k, i, j] - 0.5 * sx[k, i, j] if i < nx else W[k, nx - 1, j]
            _hll(WL, WR, nv, 1, cva, cvp, rp, F)
            for k in range(nv):
                FX[k, i, j] = F[k]
            px_l[i, j], px_r[i, j] = WL[3], WR[3]
    FR = np.empty((nv, nx, nr + 1))
    pr_l = np.empty((nx, nr + 1))
    pr_r = np.empty((nx, nr + 1))
    for i in prange(nx):
        WL = np.empty(nv)
        WR = np.empty(nv)
        F = np.empty(nv)
        for j in range(nr + 1):
            for k in range(nv):
                WL[k] = W[k, i, j - 1] + 0.5 * sr[k, i, j - 1] if j > 0 else W[k, i, 0]
                WR[k] = W[k, i, j] - 0.5 * sr[k, i, j] if j < nr else W[k, i, nr - 1]
            if j == 0:
                WL[2] = -W[2, i, 0]
            _hll(WL, WR, nv, 2, cva, cvp, rp, F)
            for k in range(nv):
                FR[k, i, j] = F[k]
            pr_l[i, j], pr_r[i, j] = WL[3], WR[3]

    force = 0.0
    for i in range(nx + 1):
        for j in range(nr):
            force += force_faces[i, j] * (px_l[i, j] - px_r[i, j])
    flows = np.zeros(nv)
    for k in range(nv):
        for j in range(nr):
            flows[k] += FX[k, nx, j] * out_right[j] - FX[k, 0, j] * out_left[j]
        for i in range(nx):
            flows[k] += FR[k, i, nr] * out_top[i]
    flows[1] -= p0 * (out_right.sum() - out_left.sum())

    # Each cell: the flux in through its open faces, the walls' push on its shut ones, and the hoop term.
    out = np.empty((nv, nx, nr), U.dtype)
    for i in prange(nx):
        for j in range(nr):
            if solid[i, j] or fixed[i, j]:
                for k in range(nv):
                    out[k, i, j] = 0.0
                continue
            a0, a1, ax = open_x[i, j], open_x[i + 1, j], area_x[j]
            b0, b1 = open_r[i, j], open_r[i, j + 1]
            ar0, ar1 = area_r[i, j], area_r[i, j + 1]
            for k in range(nv):
                d = -((a1 * FX[k, i + 1, j] - a0 * FX[k, i, j]) * ax
                      + (b1 * FR[k, i, j + 1] * ar1 - b0 * FR[k, i, j] * ar0))
                if k == 1:
                    d -= ((1 - a1) * px_l[i + 1, j] - (1 - a0) * px_r[i, j]) * ax
                elif k == 2:
                    d -= (1 - b1) * pr_l[i, j + 1] * ar1 - (1 - b0) * pr_r[i, j] * ar0
                    d += p[i, j] * d_area_r[i, j]
                out[k, i, j] = d / volume[i, j]
    return out, flows, force, rate


@_jit
def axisym_sources(U, dt, solid, fixed, volume, cva, cvp, rp,
                   wall_ratio, stanton, wall_temperature,
                   burn, fuel0, heat, oxygen, inhibition, rate, activation, ceiling, o2_in_air):
    """axisym.Axisymmetric._cool() (if wall_ratio has cells) then _burn() (if burn), on U in place.

    Returns the heat given to the walls and the heat afterburning released.
    """
    nv, nx, nr = U.shape
    cool = wall_ratio.size > 0
    lost = 0.0
    released = 0.0
    for i in range(nx):
        for j in range(nr):
            if fixed[i, j]:
                continue
            if cool:
                rho = float(U[0, i, j])
                u = U[1, i, j] / rho
                v = U[2, i, j] / rho
                Y = min(max(U[4, i, j] / rho, 0.0), 1.0)
                cv = cva + Y * (cvp - cva)
                rg = R_AIR + Y * (rp - R_AIR)
                p = rho * rg / cv * max(U[3, i, j] / rho - 0.5 * (u * u + v * v), 1.0)
                T = p / (rho * rg)
                speed = math.sqrt(u * u + v * v) + 0.1 * math.sqrt((1 + rg / cv) * p / rho)
                k = (1 + rg / cv) * stanton * speed * wall_ratio[i, j]
                q = rho * cv * max(T - wall_temperature, 0.0) * (1 - math.exp(-k * dt))
                U[3, i, j] -= q
                lost += q * volume[i, j]
            if burn and not solid[i, j]:
                rho = float(U[0, i, j])
                u = U[1, i, j] / rho
                v = U[2, i, j] / rho
                Y = min(max(U[4, i, j] / rho, 0.0), 1.0)
                cv = cva + Y * (cvp - cva)
                rg = R_AIR + Y * (rp - R_AIR)
                p = rho * rg / cv * max(U[3, i, j] / rho - 0.5 * (u * u + v * v), 1.0)
                T = p / (rho * rg)
                fuel = min(max(U[5, i, j] / rho, 0.0), fuel0)
                o2 = max(o2_in_air * (1 - Y) - oxygen * (fuel0 * Y - fuel), 0.0)
                k = rate * math.exp(-activation / max(T, 200.0))
                if inhibition:
                    k /= 1 + inhibition * Y
                burnt = min(fuel, o2 / oxygen) * (1 - math.exp(-k * dt))
                burnt = min(burnt, max(cv * (ceiling - T), 0.0) / heat)
                U[5, i, j] -= rho * burnt
                U[3, i, j] += rho * burnt * heat
                released += rho * burnt * volume[i, j]
    return lost, released * heat


def _twin(fn, name):
    """A copy of fn under another name, so it can be compiled (and cached) a second way."""
    twin = types.FunctionType(fn.__code__, fn.__globals__, name, fn.__defaults__, fn.__closure__)
    twin.__qualname__ = name
    return twin


axisym_rhs = _jit(_axisym_rhs)
axisym_rhs_parallel = _jit(_twin(_axisym_rhs, "_axisym_rhs_parallel"), parallel=True)
PARALLEL_CELLS = 1000  # grids this big or bigger use axisym_rhs_parallel


def warm() -> None:
    """Compile every kernel now (or load it from the cache), with the argument types the solvers pass.

    The first compile takes seconds; a worker does it as it boots, not in the middle of a shot.
    """
    if not ENABLED:
        return
    from .axisym import Afterburn, Axisymmetric

    f = np.ones(4)
    nodes = np.linspace(0.0, 1.0, 5)
    edges, area = np.array([0.0, 0.5]), np.ones(1)
    bore_fluxes(f, f, f, f, f, nodes, True, np.zeros(5))
    bore_rhs(f, f, f, f, f, nodes, nodes, True, np.zeros(5), edges, area, 1.0)
    bore_primitives(f, f, 2 * f, nodes, nodes, 0.1 * f, True, edges, edges, 1.0, 1.25, 1e-3)
    bore_wall_losses(f, f, 2 * f, f, nodes, edges, area, 1.0, 1e-6, 1.0, 1.25, 0.03, 8e-5, 0.75, 300.0)
    for shape in ((4, 3), (40, 25)):  # one-thread and parallel
        for burn in (None, Afterburn(0.3, 1e7, 0.6)):
            solid = np.zeros(shape, bool)
            s = Axisymmetric(1e-3, 0.0, solid, np.ones((shape[0] + 1, shape[1])), np.ones((shape[0], shape[1] + 1)),
                             330.0, 1.24, 101325.0, 288.15, afterburn=burn)
            s.step(1e-9)

