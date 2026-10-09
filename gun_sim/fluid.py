"""1-D fluid-dynamics interior ballistics model.

The propellant gas between the breech and the projectile base is solved with
the quasi-1D compressible Euler equations on a finite-volume mesh:

* Moving mesh (ALE): N cells span [0, L(t)], where L = chamber length + travel.
  Node i moves with velocity w_i = (i / N) * v_projectile, so the mesh
  stretches as the projectile moves down the bore.
* Area: the cross-section A(x) may change along the axis (quasi-1D). With
  barrel.chamber_shape = "case" the chamber is the inside of the cartridge
  case, shoulder and neck included (see chamber.py); otherwise it is a
  bore-sized cylinder of the chamber's volume. Fluxes are multiplied by the
  face area, and the walls push on the gas with p dA/dx.
* Flux: HLLC (Toro), evaluated at each moving face: the Riemann fan is sampled
  at the face's speed w. HLLC resolves contact surfaces, which the earlier
  Rusanov flux smeared.
* Reconstruction: MUSCL, piecewise linear with the van Leer limiter, so the
  scheme is second order in space where the flow is smooth.
* Time stepping: two-stage SSP Runge-Kutta (Heun), second order, with the
  projectile's motion advanced in the same stages as the gas.
* Equation of state: Noble-Abel, p = (gamma - 1) * rho * e / (1 - b * rho).
* Propellant: grains are spread through the chamber. Each slice of the charge
  burns according to the local pressure (Vieille's law with the propellant's
  geometric form function) and releases gas with energy f / (gamma - 1) per
  kilogram. In a cylindrical chamber the grains move with the mesh (as in
  the Lagrange gradient of the lumped model). In a case-shaped chamber they
  stay where they are: grains that followed the stretching mesh would be
  squeezed through the shoulder into the neck. The igniter's gas fills the
  chamber at the start and every grain is alight.
* Two-phase grain bed (solver.two_phase, see grainbed.py): instead, the grains
  are a second phase on the same mesh, with their own velocity. The gas's
  pressure and drag carry them forwards, a packed bed pushes back, and they
  light one cell at a time as the primer's hot gas reaches and heats them.
  The chamber starts full of cold gas at ambient pressure.
* Recoil: the gun is pushed by the pressure on the breech face and on the
  chamber walls, and pulled forwards by the projectile's drag on the bore.
  Grains that move with the mesh are carried rather than pushed, so the
  momentum they gain, and give their gas as it is born, is added to the push
  on the breech, where the gas that drags them forwards pushes back.
* Projectile: driven by the base pressure against the bore resistance and
  the engraving resistance at its travel, with the effective mass of a
  projectile that is spun up by the rifling (see rifling.py).
* Boundaries: reflective wall at the breech; a moving wall at the projectile
  base. The pressures on the breech face and on the projectile are the HLLC
  star pressures at those walls.
* Wall losses: turbulent friction (Darcy factor WALL_FRICTION, high because of
  the rifling) and heat loss to the cold steel (Colburn's correlation,
  St = 0.023 Re^-0.2 Pr^-2/3: roughness raises friction far more than heat
  transfer, so the Reynolds analogy St = f/8 would overstate it). They act in the
  bore when solver.wall_losses is set, and always during blowdown. The heat
  that goes into the barrel gives its mean temperature rise, and the heat flux
  history at the throat gives the peak bore surface temperature there
  (conduction into a semi-infinite steel wall).
* Blowdown (optional): once the projectile leaves, the mesh freezes and the
  muzzle becomes an open end. The gas empties into the atmosphere and the bore
  rings as a closed-open pipe. The fluxes through the muzzle are recorded; they
  drive the muzzle blast model in gun_sim.sound and the muzzle flash and smoke
  in gun_sim.plume. The wall losses damp the ringing and let the cooling gas
  draw air back in, as in a real barrel.
* The gas temperature along the column is recorded too (bore_gas), so the
  3D view can show it glowing as hot as it is, and fading as it expands
  and cools on the steel.

Each cell stores totals: gas mass M, momentum P and total energy E. The flux
treats M / V (gas mass per unit of cell volume, grains included) as the
density, so a cell packed with grains passes less gas.
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict

import numpy as np

from . import action, devices, kernels, rifling
from .chamber import chamber_profile
from .config import Gun
from .grainbed import GrainBed
from .results import GunLoads, MuzzleFlow, ShotResult

ATMOSPHERE = 101325.0  # Pa
BORE_GAS_POINTS = 24   # temperatures recorded along the gas column
WALL_FRICTION = 0.03   # Darcy friction factor of a rifled bore
WALL_TEMPERATURE = 300.0  # K, the barrel is cold (one shot) and stays so in bulk
GAS_VISCOSITY = 8e-5   # Pa s, propellant gas at ~2500 K
GAS_PRANDTL = 0.75
# Gun steel.
STEEL_DENSITY = 7850.0     # kg/m^3
STEEL_HEAT_CAPACITY = 460.0  # J/(kg K)
STEEL_CONDUCTIVITY = 40.0  # W/(m K)


def _surface_temperature_rise(t, flux, at):
    """Surface temperature rise of a semi-infinite wall heated by flux(t), W/m^2.

    Duhamel's integral for a flux held constant over each step:
    dT(t) = 2 / sqrt(pi k rho c) * sum q_i (sqrt(t - t_(i-1)) - sqrt(t - t_i)).
    """
    t = np.asarray(t)
    flux = np.asarray(flux)
    t0 = np.concatenate(([t[0]], t[:-1]))
    effusivity = np.sqrt(STEEL_CONDUCTIVITY * STEEL_DENSITY * STEEL_HEAT_CAPACITY)
    rise = []
    for tn in at:
        on = t <= tn
        rise.append(np.sum(flux[on] * (np.sqrt(tn - t0[on]) - np.sqrt(tn - t[on]))))
    return 2 / np.sqrt(np.pi) / effusivity * np.array(rise)


def _van_leer(d_minus, d_plus):
    """Limited slope (per cell) from the backward and forward differences."""
    prod = d_minus * d_plus
    denom = d_minus + d_plus
    safe = np.where(prod > 0, denom, 1.0)
    return np.where(prod > 0, 2 * prod / safe, 0.0)


def _hllc(qL, uL, pL, eL, cL, qR, uR, pR, eR, cR, w):
    """HLLC flux F(U) - w U through faces moving at speed w.

    q is the density, e the specific internal energy, c the sound speed.
    Returns the mass, momentum and energy fluxes and the star pressure.
    """
    EL = qL * (eL + 0.5 * uL**2)
    ER = qR * (eR + 0.5 * uR**2)
    sL = np.minimum(uL - cL, uR - cR)
    sR = np.maximum(uL + cL, uR + cR)
    mL = qL * (sL - uL)  # mass flux through the left wave, in its frame
    mR = qR * (sR - uR)
    s_star = (pR - pL + mL * uL - mR * uR) / (mL - mR)
    p_star = pL + mL * (s_star - uL)

    # Flux and state on each side, then sample the fan at x/t = w.
    U_L = np.stack((qL, qL * uL, EL))
    U_R = np.stack((qR, qR * uR, ER))
    F_L = U_L * uL + np.stack((0 * pL, pL, pL * uL))
    F_R = U_R * uR + np.stack((0 * pR, pR, pR * uR))
    rL = mL / (sL - s_star)  # star-region densities
    rR = mR / (sR - s_star)
    Us_L = rL * np.stack((np.ones_like(uL), s_star, EL / qL + (s_star - uL) * (s_star + pL / mL)))
    Us_R = rR * np.stack((np.ones_like(uR), s_star, ER / qR + (s_star - uR) * (s_star + pR / mR)))
    out = np.where(w <= s_star,
                   np.where(w <= sL, F_L - w * U_L, F_L + sL * (Us_L - U_L) - w * Us_L),
                   np.where(w <= sR, F_R + sR * (Us_R - U_R) - w * Us_R, F_R - w * U_R))
    return out[0], out[1], out[2], p_star


_MIRROR = np.array([1.0, -1.0, 1.0, 1.0, 1.0])[:, None]
_NO_GHOST = np.zeros(5)


def _faces(q, u, p, e, c, w, ghost=None):
    """Fluxes at the n+1 nodes, MUSCL-reconstructed.

    ghost=None: the right end is a wall (the projectile, moving at w[-1]);
    otherwise it is the open muzzle's outside state (q, u, p, e, c).
    kernels.bore_fluxes() is the compiled twin of this.
    """
    prim = np.stack((q, u, p, e, c))
    ghost_l = prim[:, :1] * _MIRROR
    if ghost is None:
        ghost_r = prim[:, -1:] * _MIRROR
        ghost_r[1] += 2 * w[-1]
    else:
        ghost_r = np.array(ghost, dtype=float)[:, None]
    ext = np.concatenate((ghost_l, prim, ghost_r), axis=1)
    d = np.diff(ext, axis=1)
    half = 0.5 * _van_leer(d[:, :-1], d[:, 1:])
    lo, hi = prim - half, prim + half  # states at each cell's left and right faces
    left = np.concatenate((lo[:, :1] * _MIRROR, hi), axis=1)
    if ghost is None:
        edge = hi[:, -1:] * _MIRROR
        edge[1] += 2 * w[-1]
    else:
        edge = ghost_r
    rght = np.concatenate((lo, edge), axis=1)
    return _hllc(*left, *rght, w)


def _bore_rhs(q, u, p, e, c, w, nodes, ghost, chamber):
    """Fluxes, face areas, and the rates of change of the cell totals (less any two-phase bed's share).

    Also the fastest wave relative to the mesh, for the time step. kernels.bore_rhs() is the compiled twin.
    """
    area = chamber.area_at(nodes)
    area[-1] = chamber.bore_area
    fm, fp, fe, p_star = _faces(q, u, p, e, c, w, ghost)
    d_area = np.diff(area)
    d_mass = -np.diff(area * fm)
    d_mom = -np.diff(area * fp) + p * d_area
    d_energy = -np.diff(area * fe)
    wave = np.max(np.abs(u - 0.5 * (w[:-1] + w[1:])) + c)
    return fm, fp, fe, p_star, area, d_area, d_mass, d_mom, d_energy, wave


def bore_rhs(q, u, p, e, c, w, nodes, ghost, chamber):
    """_bore_rhs(), compiled when Numba is there."""
    if kernels.ENABLED:
        wall = ghost is None
        return kernels.bore_rhs(q, u, p, e, c, w, nodes, wall, _NO_GHOST if wall else np.array(ghost, dtype=float),
                                chamber.edges, chamber.area, chamber.bore_area)
    return _bore_rhs(q, u, p, e, c, w, nodes, ghost, chamber)


_cache: dict = {}
_cache_lock = threading.Lock()


def _cache_key(gun: Gun, blowdown_time: float, ambient_pressure: float) -> str:
    data = asdict(gun)
    data.pop("feed", None)   # the magazine doesn't change the shot
    return json.dumps([data, blowdown_time, ambient_pressure], sort_keys=True)


def _store(key: str, shot: ShotResult) -> None:
    if key not in _cache and len(_cache) >= 4:
        _cache.pop(next(iter(_cache)))
    _cache[key] = shot


def simulate_cached(gun: Gun, blowdown_time: float = 0.0, ambient_pressure: float = ATMOSPHERE,
                    run=None) -> ShotResult:
    """simulate(), remembered for the last few guns.

    The firing range asks for the shot and its sound at the same moment; with a
    muzzle device the coupled 2D solution takes seconds, so the second caller
    waits for the first and shares its result.

    run(simulate, gun, **kwargs), if given, is how simulate() gets called (e.g. in a worker process).
    """
    key = _cache_key(gun, blowdown_time, ambient_pressure)
    with _cache_lock:
        if key not in _cache:
            kwargs = {"blowdown_time": blowdown_time, "ambient_pressure": ambient_pressure}
            _store(key, run(simulate, gun, **kwargs) if run else simulate(gun, **kwargs))
        return _cache[key]


def remember(gun: Gun, blowdown_time: float, ambient_pressure: float, shot: ShotResult) -> None:
    """Hand simulate_cached() a shot solved elsewhere (another process), so it isn't solved again."""
    with _cache_lock:
        _store(_cache_key(gun, blowdown_time, ambient_pressure), shot)


def simulate(gun: Gun, profile_count: int = 8, blowdown_time: float = 0.0,
             ambient_pressure: float = ATMOSPHERE) -> ShotResult:
    """Simulate one shot.

    blowdown_time > 0 keeps solving for that long after muzzle exit, with the
    muzzle open to ambient_pressure, and fills ShotResult.muzzle_flow.
    """
    bar, proj, prop, cfg = gun.barrel, gun.projectile, gun.propellant, gun.solver
    n = cfg.cells
    bore = bar.bore_area
    f, b, gamma = prop.impetus, prop.covolume, prop.gamma
    e_release = f / (gamma - 1)        # specific internal energy of fresh gas
    z_end = prop.z_burnout
    chamber = chamber_profile(gun)
    l0 = chamber.length
    m_eff = rifling.effective_mass(gun)

    # Grains: one slice of the charge per initial cell, sized by volume. Slices
    # either move with the mesh (cylinder) or stay put (case), unless they are a
    # two-phase bed that moves by itself.
    two_phase = cfg.two_phase
    grains_move = bar.chamber_shape == "cylinder" and not two_phase
    xi = np.arange(n + 1) / n            # node positions as a fraction of L
    grain_x0 = xi * l0
    v0 = np.diff(chamber.volume_at(grain_x0))
    omega = prop.charge_mass * v0 / v0.sum()
    z = np.zeros(n)                    # burnt web fraction per slice
    burnt = np.zeros(n)                # burnt mass per slice
    bed = GrainBed(gun, omega, chamber.volume) if two_phase else None

    def grain_edges(x_p):
        return xi * (l0 + x_p) if grains_move else grain_x0

    def per_cell(nodes, edges, amounts):
        """Spread per-slice amounts over the cells, evenly in volume within each slice."""
        acc = np.concatenate(([0.0], np.cumsum(amounts)))
        if grains_move:  # slices are the cells
            return amounts
        return np.diff(np.interp(chamber.volume_at(nodes), chamber.volume_at(edges), acc))

    # --- initial state: igniter gas at rest filling the space around the grains,
    # or (two-phase) cold gas at ambient pressure, the primer's gas still to come
    p_ign = gun.ignition.pressure
    if two_phase:
        rho0, e0 = GrainBed.cold_gas(prop, ambient_pressure)
        p_base = ambient_pressure
    else:
        rho0, e0 = p_ign / (f + b * p_ign), e_release
        p_base = p_ign
    mass = rho0 * (v0 - omega / prop.density)
    mom = np.zeros(n)
    energy = mass * e0
    m_ign = mass.sum()

    x_p = 0.0   # projectile travel
    v_p = 0.0   # projectile velocity
    moving = False
    t = 0.0
    step = 0

    hist = {k: [] for k in ("t", "x", "v", "pb", "pbase")}
    bore_gas = []      # (t, temperatures along the column, breech to base/muzzle)
    gas_points = (np.arange(BORE_GAS_POINTS) + 0.5) / BORE_GAS_POINTS
    profiles = []
    next_profile_x = 0.0
    peak_breech = 0.0
    # Momentum given to the gun (rearwards): pressure on the breech face and on
    # the chamber walls (a shoulder is pushed forwards), minus the forward drag
    # of the projectile on the bore.
    impulse = 0.0
    # The same force over time, split into the push on the bolt face and the
    # rest (on the barrel), plus the gas at the gas port, for gun_sim.action.
    head_area = action.head_area(gun)
    port_travel = action.port_position(gun)
    loads = {k: [] for k in ("t", "breech", "barrel", "port_p", "port_t", "port_u")}
    acc = {"t": 0.0, "total": 0.0, "breech": 0.0}

    def accumulate(dt, d1, d2, friction, grains=0.0, device_force=0.0):
        """Add one step's momentum to the gun; returns it.

        grains is the momentum the grains gained (and gave their gas as it was
        born). They are moved with the mesh rather than pushed, so nothing in
        the flux pays for it; the gas that drags them forwards is pushed back,
        and the gas pushes the breech. device_force is the gas pushing a muzzle
        device forwards.
        """
        total = dt * (0.5 * (d1["force"] + d2["force"]) - device_force) - friction + grains
        acc["t"] += dt
        acc["total"] += total
        acc["breech"] += dt * (0.5 * (d1["breech_push"] + d2["breech_push"]) - ambient_pressure) * head_area + grains
        return total

    def record_loads(t, diag, x_p):
        """Store the mean forces since the last record, and the gas at the port now."""
        if acc["t"] <= 0:
            return
        loads["t"].append(t - 0.5 * acc["t"])
        loads["breech"].append(acc["breech"] / acc["t"])
        loads["barrel"].append((acc["total"] - acc["breech"]) / acc["t"])
        acc.update(t=0.0, total=0.0, breech=0.0)
        if x_p < port_travel:  # the projectile hasn't uncovered the port yet
            loads["port_p"].append(ambient_pressure)
            loads["port_t"].append(WALL_TEMPERATURE)
            loads["port_u"].append(0.0)
            return
        nodes = diag["nodes"]
        centres = 0.5 * (nodes[:-1] + nodes[1:])
        x = l0 + port_travel
        p = float(np.interp(x, centres, diag["p"]))
        rho = float(np.interp(x, centres, diag["rho"]))
        loads["port_p"].append(p)
        loads["port_t"].append(p * (1 - b * rho) / (rho * prop.gas_constant))
        loads["port_u"].append(float(np.interp(x, centres, diag["u"])))

    def record_gas(t, diag):
        temps = diag["p"] * (1 - b * diag["rho"]) / (diag["rho"] * prop.gas_constant)
        bore_gas.append((t, np.interp(gas_points, xi_c, temps).astype(np.float32)))

    def primitives(mass, mom, energy, x_p, grains=None):
        nodes = xi * (l0 + x_p)
        if kernels.ENABLED and not two_phase:
            return (nodes, *kernels.bore_primitives(
                mass, mom, energy, nodes, grain_edges(x_p), (omega - burnt) / prop.density, grains_move,
                chamber.edges, chamber._cumulative, chamber.bore_area, gamma, b))
        v_cell = np.diff(chamber.volume_at(nodes))
        if two_phase:  # a bed squeezed nearly solid still leaves the gas a little room
            rho = mass / np.maximum(v_cell - bed.solid_volume(grains), 0.02 * v_cell)
        else:
            rho = mass / (v_cell - per_cell(nodes, grain_edges(x_p), (omega - burnt) / prop.density))
        u = mom / mass
        e = energy / mass - 0.5 * u**2
        p = (gamma - 1) * rho * e / (1 - b * rho)
        # Sound speed of the gas-and-grains system the flux solves: the gas's
        # c / sqrt(gas fraction), since only the gas between the grains compresses.
        c = np.sqrt(gamma * p / ((mass / v_cell) * (1 - b * rho)))
        return nodes, v_cell, rho, u, e, p, c

    def rhs(state, moving, right):
        """Time derivatives of the state (cell totals, the projectile, and a two-phase bed's grains), plus diagnostics."""
        mass, mom, energy, x_p, v_p = state[:5]
        grains = state[5] if two_phase else None
        nodes, v_cell, rho, u, e, p, c = primitives(mass, mom, energy, x_p, grains)
        w = xi * v_p
        # right = "wall" (the projectile, moving at w[-1]) or, for an open muzzle,
        # a function of the cell states returning the ghost (q, u, p, e, c).
        q = mass / v_cell
        fm, fp, fe, p_star, area, d_area, d_mass, d_mom, d_energy, wave = bore_rhs(
            q, u, p, e, c, w, nodes, None if right == "wall" else right(q, u, p, e, c), chamber)
        p_breech = p_star[0]
        p_base = p_star[-1] if right == "wall" else p[-1]
        rates = [d_mass, d_mom, d_energy, v_p, 0.0]
        # A two-phase bed takes its share of the gas's push, and pushes the walls and projectile itself.
        bed_breech = bed_base = bed_walls = outflow = 0.0
        dt_bed = np.inf
        if two_phase:
            d_bed, push, work, bed_breech, bed_base, bed_walls, outflow, dt_bed = bed.rhs(
                grains, nodes, area, w, v_cell, p, p_star, right != "wall")
            d_mom -= push
            d_energy -= work
            rates.append(d_bed)
        p_base += bed_base
        resist = rifling.resistance(gun, x_p) if moving else 0.0
        rates[4] = bore * (p_base - resist) / m_eff if moving else 0.0
        # Until shot start the case neck holds the projectile, so its push comes back to the barrel.
        held = 0.0 if moving or right != "wall" else bore * (p_base - ambient_pressure)
        force = ((p_breech + bed_breech - ambient_pressure) * area[0]
                 + np.sum((p - ambient_pressure) * d_area) + bed_walls
                 - bore * resist - held)
        dt_max = cfg.cfl * min((nodes[1] - nodes[0]) / wave, dt_bed)
        diag = {"p": p, "u": u, "rho": rho, "c": c, "e": e, "p_breech": p_breech, "p_base": p_base,
                "breech_push": p_breech + bed_breech, "force": force, "dt_max": dt_max, "flux": (fm, fp, fe),
                "v_cell": v_cell, "nodes": nodes, "outflow": outflow}
        return rates, diag

    def rk2(state, moving, right):
        """One SSP-RK2 step. Returns the new state, dt, and the two stages' diagnostics."""
        k1, d1 = rhs(state, moving, right)
        dt = d1["dt_max"]
        s1 = [a + dt * da for a, da in zip(state, k1)]
        s1[4] = max(s1[4], 0.0)
        k2, d2 = rhs(s1, moving, right)
        new = [0.5 * a + 0.5 * (a1 + dt * da) for a, a1, da in zip(state, s1, k2)]
        new[4] = max(new[4], 0.0)
        return new, dt, d1, d2

    def pack(x_p, v_p):
        return [mass, mom, energy, x_p, v_p] + ([bed.U] if two_phase else [])

    def burn(dt, p, nodes, x_p, v_p):
        """Burn each slice at the pressure of the cell it lies in; put the gas into the cells."""
        nonlocal mass, mom, energy, z, burnt
        if not np.any(z < z_end):
            return 0.0
        edges = grain_edges(x_p)
        centres = 0.5 * (edges[:-1] + edges[1:])
        cell = np.clip(((centres / nodes[-1]) * n).astype(int), 0, n - 1)
        z = np.minimum(z + dt * prop.web_regression_rate(np.maximum(p[cell], 0.0)), z_end)
        dm = omega * prop.burnt_fraction(z) - burnt
        burnt = burnt + dm
        v_grain = xi_c * v_p if grains_move else np.zeros(n)
        dm_cell = per_cell(nodes, edges, dm)
        mass = mass + dm_cell
        mom = mom + per_cell(nodes, edges, dm * v_grain)
        energy = energy + per_cell(nodes, edges, dm * (e_release + 0.5 * v_grain**2))
        return float(np.sum(dm * v_grain))

    def grain_momentum(v_p):
        """Momentum of the unburnt grains, which move with the mesh in a cylindrical chamber."""
        return float(np.sum((omega - burnt) * xi_c)) * v_p if grains_move else 0.0

    xi_c = 0.5 * (xi[:-1] + xi[1:])
    cv = prop.gas_constant / (gamma - 1)
    x_throat = l0 + 0.5 * bar.bore_diameter  # a little ahead of the seated base
    heat = {"total": 0.0, "t": [], "flux": []}

    def wall_losses(dt, nodes, rho):
        """Wall friction and heat loss over dt. Returns the momentum friction gives the barrel."""
        nonlocal mom, energy
        if kernels.ENABLED:
            mom, energy, q, diameter, friction = kernels.bore_wall_losses(
                mass, mom, energy, rho, nodes, chamber.edges, chamber.area, chamber.bore_area, dt, cv, gamma,
                WALL_FRICTION, GAS_VISCOSITY, GAS_PRANDTL, WALL_TEMPERATURE)
            return heat_flux(dt, nodes, q, diameter, friction)
        diameter = np.sqrt(4 / np.pi * chamber.area_at(0.5 * (nodes[:-1] + nodes[1:])))
        # Friction (implicit, so it can only slow the gas) turns kinetic energy into heat.
        u_old = mom / mass
        k_f = WALL_FRICTION / 8 * (4 / diameter) * np.abs(u_old)
        u_new = u_old / (1 + k_f * dt)  # du/dt = -(f/8) (4/D) u|u|
        mom = mass * u_new
        # Heat loss, decaying exactly towards the wall temperature: dT/dt = -gamma St |u| (4/D) (T - T_wall).
        reynolds = np.maximum(rho * np.abs(u_new) * diameter / GAS_VISCOSITY, 1e3)
        stanton = 0.023 * reynolds**-0.2 * GAS_PRANDTL**(-2 / 3)
        k_h = stanton * (4 / diameter) * np.abs(u_new)
        t_gas = (energy / mass - 0.5 * u_new**2) / cv
        q = mass * cv * np.maximum(t_gas - WALL_TEMPERATURE, 0.0) * (1 - np.exp(-gamma * k_h * dt))
        energy = energy - q
        return heat_flux(dt, nodes, q, diameter, np.sum(mass * (u_old - u_new)))

    def heat_flux(dt, nodes, q, diameter, friction):
        """Record the heat the cells lost (q) and the flux into the wall at the throat; returns friction."""
        heat["total"] += float(q.sum())
        dx = nodes[1] - nodes[0]
        j = int(x_throat / dx)
        heat["t"].append(t + dt)
        heat["flux"].append(q[j] / (np.pi * diameter[j] * dx * dt) if j < n else 0.0)
        return friction

    def exchange(dt, new):
        """Unpack a step's new state and, for a two-phase bed, let the grains and the gas trade over it.
        Returns the momentum the primer's jet gave the breech."""
        nonlocal mass, mom, energy
        mass, mom, energy = new[:3]
        if not two_phase:
            return 0.0
        bed.U = new[5]
        bed.U[0] = np.maximum(bed.U[0], 0.0)
        v_cell = np.diff(chamber.volume_at(xi * (l0 + new[3])))
        mass, mom, energy, kick = bed.exchange(t, dt, mass, mom, energy, v_cell)
        return kick

    bed_hist = {"t": [], "lit": [], "burnt": []}
    bed_profiles = []   # two-phase: (t, centres, solid fraction, grain velocity), with the pressure profiles

    def record_bed(t, nodes, v_cell):
        u_g, solid = bed.unpack(bed.U)[3:6:2]
        bed_hist["t"].append(t)
        bed_hist["lit"].append(bed.lit_share())
        bed_hist["burnt"].append(bed.burnt() / prop.charge_mass)
        return solid / prop.density / v_cell, u_g

    while x_p < bar.travel and t < cfg.max_time:
        # Shot start: the projectile moves once the gas (and a two-phase bed) pushes hard enough.
        moving = moving or p_base >= proj.shot_start_pressure
        grains = -grain_momentum(v_p)
        new, dt, d1, d2 = rk2(pack(x_p, v_p), moving, "wall")
        grains += exchange(dt, new)
        x_p, v_p = new[3], new[4]
        if not two_phase:
            grains += burn(dt, d1["p"], xi * (l0 + x_p), x_p, v_p)
        grains += grain_momentum(v_p)
        friction = wall_losses(dt, xi * (l0 + x_p), d2["rho"]) if cfg.wall_losses else 0.0
        impulse += accumulate(dt, d1, d2, friction, grains)

        t += dt
        step += 1
        p_breech, p_base = d1["p_breech"], d2["p_base"]
        peak_breech = max(peak_breech, p_breech)

        if step % cfg.record_every == 0:
            hist["t"].append(t)
            hist["x"].append(x_p)
            hist["v"].append(v_p)
            hist["pb"].append(p_breech)
            hist["pbase"].append(p_base)
            record_loads(t, d1, x_p)
            record_gas(t, d1)
            if two_phase:
                record_bed(t, d1["nodes"], d1["v_cell"])
        if x_p >= next_profile_x and len(profiles) < profile_count:
            dx = (l0 + x_p) / n
            centres = (np.arange(n) + 0.5) * dx - l0  # measured from the seated base
            profiles.append((t, centres, d1["p"].copy()))
            if two_phase:
                bed_profiles.append((t, centres, *record_bed(t, d1["nodes"], d1["v_cell"])))
            next_profile_x += bar.travel / profile_count

    left = x_p >= bar.travel
    record_loads(t, d1, x_p)
    muzzle_time = t
    muzzle_velocity = v_p
    burnt_mass = bed.burnt() if two_phase else mass.sum() - m_ign

    muzzle_flow = None
    device_result = None
    if left and blowdown_time > 0:
        v_p = 0.0  # the mesh freezes
        rec = {k: [] for k in ("t", "mdot", "edot", "thrust", "p_exit", "u_exit", "rho_exit", "p_breech")}
        end = t + blowdown_time

        _, d0 = rhs(pack(x_p, 0.0), False, "wall")
        exit_state = (float(d0["p"][-1]), float(d0["u"][-1]), float(d0["rho"][-1]))
        porosity = float(mass[-1] / d0["rho"][-1] / d0["v_cell"][-1])  # gas share of the last cell

        # A muzzle device is solved in 2D alongside, for its window after exit.
        coupling = devices.DeviceCoupling(gun, ambient_pressure) if gun.muzzle_device.type != "none" else None
        outside = {"state": None, "force": 0.0}

        def outlet(q, u, p, e, c):
            """Open end: supersonic outflow leaves undisturbed (extrapolate). Otherwise the exit
            sees ambient pressure, or, with a muzzle device, the device's gas just past the muzzle."""
            if u[-1] >= c[-1]:
                return (q[-1], u[-1], p[-1], e[-1], c[-1])
            if outside["state"] is None:
                r_g, u_g, p_out = q[-1] / porosity, u[-1], ambient_pressure  # same density, ambient pressure
            else:
                r_g, u_g, p_out = outside["state"]
            q_g = r_g * porosity
            e_g = p_out * (1 - b * r_g) / ((gamma - 1) * r_g)
            c_g = np.sqrt(gamma * p_out / (q_g * (1 - b * r_g)))
            return (q_g, u_g, p_out, e_g, c_g)

        record_gas(t, d0)
        while t < end:
            new, dt, d1, d2 = rk2(pack(x_p, 0.0), False, outlet)
            kick = exchange(dt, new)
            if two_phase:
                bed.ejected += 0.5 * dt * (d1["outflow"] + d2["outflow"])
            else:
                burn(dt, d1["p"], d1["nodes"], x_p, 0.0)
            friction = wall_losses(dt, d1["nodes"], d2["rho"])
            if coupling is not None:
                outside["state"] = coupling.step(t, dt, float(d1["rho"][-1]), float(d1["u"][-1]), float(d1["e"][-1]))
                outside["force"] = coupling.rec["force"][-1]
            impulse += accumulate(dt, d1, d2, friction, kick, device_force=outside["force"])
            t += dt
            record_loads(t, d1, x_p)
            fm, fp, fe = (0.5 * (a[-1] + b_[-1]) for a, b_ in zip(d1["flux"], d2["flux"]))
            rec["t"].append(t)
            rec["mdot"].append(bore * fm)
            rec["edot"].append(bore * fe)
            rec["thrust"].append(bore * (fp - ambient_pressure))
            rec["p_exit"].append(d1["p"][-1])
            rec["u_exit"].append(d1["u"][-1])
            rec["rho_exit"].append(d1["rho"][-1])
            rec["p_breech"].append(d1["p_breech"])
            step += 1
            if step % cfg.record_every == 0:
                record_gas(t, d1)
        if coupling is not None:
            device_result = coupling.result()
        muzzle_flow = MuzzleFlow(
            exit_time=muzzle_time,
            exit_pressure=exit_state[0],
            exit_gas_velocity=exit_state[1],
            exit_density=exit_state[2],
            **{k: np.array(v) for k, v in rec.items()},
        )

    # Barrel heating. The bulk rise spreads the heat through a frustum of steel
    # between the outside diameters; the surface at the throat sees the flux
    # history directly.
    length = l0 + bar.travel
    d1, d2 = bar.breech_diameter, bar.muzzle_diameter
    steel = np.pi / 12 * length * (d1 * d1 + d1 * d2 + d2 * d2) - bore * length
    surface_rise = 0.0
    if heat["t"] and max(heat["flux"]) > 0:
        at = np.linspace(heat["t"][0], heat["t"][-1], 200)
        surface_rise = float(_surface_temperature_rise(heat["t"], heat["flux"], at).max())

    grain_bed = None
    if two_phase:
        lit = np.array(bed_hist["lit"])
        alight = np.nonzero(lit >= 0.99)[0]
        grain_bed = {
            "t": np.array(bed_hist["t"]), "lit": lit, "burnt": np.array(bed_hist["burnt"]),
            "flame_spread_time": float(bed_hist["t"][alight[0]]) if alight.size else None,
            "lit_time": bed.lit_time.copy(),
            "cell_x": 0.5 * (grain_x0[:-1] + grain_x0[1:]),   # where each cell was at the start, from the breech
            "ejected": bed.ejected, "primer_mass": bed.primer_mass,
            "profiles": bed_profiles,
        }

    return ShotResult(
        model="fluid",
        left_muzzle=left,
        muzzle_velocity=muzzle_velocity,
        muzzle_time=muzzle_time,
        peak_breech_pressure=float(peak_breech),
        burnt_at_muzzle=float(burnt_mass / prop.charge_mass),
        time=np.array(hist["t"]),
        travel=np.array(hist["x"]),
        velocity=np.array(hist["v"]),
        breech_pressure=np.array(hist["pb"]),
        base_pressure=np.array(hist["pbase"]),
        profiles=profiles,
        muzzle_flow=muzzle_flow,
        recoil_impulse=float(impulse),
        loads=GunLoads(
            t=np.array(loads["t"]), breech_force=np.array(loads["breech"]), barrel_force=np.array(loads["barrel"]),
            port_pressure=np.array(loads["port_p"]), port_temperature=np.array(loads["port_t"]),
            head_area=head_area, port_position=port_travel, port_velocity=np.array(loads["port_u"])),
        device=device_result,
        heat_to_barrel=heat["total"],
        barrel_temperature_rise=heat["total"] / (STEEL_DENSITY * steel * STEEL_HEAT_CAPACITY),
        bore_temperature_rise=surface_rise,
        bore_gas=bore_gas,
        grain_bed=grain_bed,
    )
