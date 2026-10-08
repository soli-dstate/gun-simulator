"""Lumped-parameter (0-D) interior ballistics model.

The classic textbook approach: one uniform gas state behind the projectile,
with the Lagrange gradient assumption to estimate breech and base pressures.
It is fast and well understood, so it serves as a sanity check for the
fluid solver in fluid.py.

For recoil it records the force on the gun (breech pressure on the bore's
cross-section, less the projectile's drag on the bore) and the pressure at a
gas port from the Lagrange gradient. With blowdown_time > 0 it adds the gas
jet after the projectile leaves, as the classic exponentially decaying
after-effect force. Its impulse is the momentum the remaining gas takes away
when it empties like a vessel through a choked nozzle (mean jet speed
1.5 times the exit sound speed for gamma = 1.24), less the forward momentum
it already had in the bore.
"""

from __future__ import annotations

import numpy as np

from . import action, rifling
from .config import Gun
from .results import GunLoads, ShotResult

ATMOSPHERE = 101325.0  # Pa


def _jet_speed_factor(gamma: float) -> float:
    """Mean jet speed / initial sound speed for a vessel emptying isentropically through a choked nozzle.

    Thrust per unit mass flow at a sonic exit is (gamma + 1) / gamma times the
    throat sound speed, which is sqrt(2 / (gamma + 1)) times the vessel's;
    averaged over the mass as the vessel's sound speed falls, that gains a
    further 2 / (gamma + 1).
    """
    return (gamma + 1) / gamma * np.sqrt(2 / (gamma + 1)) * 2 / (gamma + 1)


def simulate(gun: Gun, blowdown_time: float = 0.0) -> ShotResult:
    bar, proj, prop = gun.barrel, gun.projectile, gun.propellant
    area = bar.bore_area
    chamber = gun.effective_chamber_volume
    omega = prop.charge_mass
    m = proj.mass
    m_eff = rifling.effective_mass(gun)  # spinning the projectile up adds to its inertia
    f, b, gamma = prop.force, prop.covolume, prop.gamma
    z_end = prop.z_burnout  # 1 for a single-phase grain, z_k for multi-perforated

    # Igniter gas fills the space around the unburnt grains.
    p_ign = gun.ignition.pressure
    v_free0 = chamber - omega / prop.density
    m_ign = p_ign * v_free0 / (f + b * p_ign)

    # Lagrange gradient: p_mean = p_base * (1 + omega/3m), p_breech = p_base * (1 + omega/2m)
    base_factor = 1 + omega / (3 * m)
    breech_factor = 1 + omega / (2 * m)

    def pressures(z, x, v, work):
        """Mean, base and breech pressure, and the gas's R T."""
        psi = prop.burnt_fraction(z)
        gas = omega * psi + m_ign
        energy = gas * f / (gamma - 1) - work - omega * v**2 / 6
        v_free = chamber + area * x - omega * (1 - psi) / prop.density - b * gas
        p_mean = (gamma - 1) * energy / v_free
        p_base = p_mean / base_factor
        return p_mean, p_base, p_base * breech_factor, p_mean * v_free / gas

    def derivatives(state, moving):
        z, x, v, work = state
        p_mean, p_base, _, _ = pressures(z, x, v, work)
        dz = prop.web_regression_rate(max(p_mean, 0.0)) if z < z_end else 0.0
        if moving:
            dv = area * (p_base - rifling.resistance(gun, x)) / m_eff
        else:
            dv = 0.0
        # `work` is the energy the gas has delivered to the projectile.
        return np.array([dz, v, dv, area * p_base * v])

    dt = gun.solver.lumped_dt
    state = np.array([0.0, 0.0, 0.0, 0.0])
    t = 0.0
    moving = False
    hist = {k: [] for k in ("t", "x", "v", "pb", "pbase")}
    head_area = action.head_area(gun)
    port_travel = action.port_position(gun)
    l0 = chamber / area
    loads = {k: [] for k in ("t", "breech", "barrel", "port_p", "port_t", "port_u")}

    while state[1] < bar.travel and t < gun.solver.max_time:
        if not moving and pressures(*state)[1] >= proj.shot_start_pressure:
            moving = True
        # Classic RK4 step.
        k1 = derivatives(state, moving)
        k2 = derivatives(state + dt / 2 * k1, moving)
        k3 = derivatives(state + dt / 2 * k2, moving)
        k4 = derivatives(state + dt * k3, moving)
        state = state + dt / 6 * (k1 + 2 * k2 + 2 * k3 + k4)
        state[0] = min(state[0], z_end)
        state[2] = max(state[2], 0.0)
        t += dt

        _, p_base, p_breech, rt = pressures(*state)
        hist["t"].append(t)
        hist["x"].append(state[1])
        hist["v"].append(state[2])
        hist["pb"].append(p_breech)
        hist["pbase"].append(p_base)
        x = state[1]
        resist = area * rifling.resistance(gun, x) if moving else 0.0
        loads["t"].append(t)
        loads["breech"].append((p_breech - ATMOSPHERE) * head_area)
        loads["barrel"].append((p_breech - ATMOSPHERE) * (area - head_area) - resist)
        if x >= port_travel:
            frac = (l0 + port_travel) / (l0 + x)  # Lagrange: pressure falls as the square of the distance
            loads["port_p"].append(p_breech - (p_breech - p_base) * frac**2)
            loads["port_t"].append(rt / prop.gas_constant)
            loads["port_u"].append(state[2] * frac)  # Lagrange: the gas speed grows linearly to the base
        else:
            loads["port_p"].append(ATMOSPHERE)
            loads["port_t"].append(300.0)
            loads["port_u"].append(0.0)

    left = state[1] >= bar.travel
    impulse = float(np.sum(np.add(loads["breech"], loads["barrel"])) * dt)
    if left and blowdown_time > 0 and loads["t"]:
        # After-effect: the force decays exponentially, carrying the jet's impulse.
        p_mean, _, _, rt = pressures(*state)
        gas = omega * prop.burnt_fraction(state[0]) + m_ign
        jet = _jet_speed_factor(gamma) * np.sqrt(gamma * rt)
        after = gas * max(jet - state[2] / 2, 0.0)
        f_breech, f_barrel = loads["breech"][-1], loads["barrel"][-1]
        f_exit = f_breech + f_barrel
        if f_exit > 0 and after > 0:
            tau = after / f_exit
            p_port, t_port = loads["port_p"][-1], loads["port_t"][-1]
            for tt in t + np.linspace(0, blowdown_time, 301)[1:]:
                decay = np.exp(-(tt - t) / tau)
                loads["t"].append(tt)
                loads["breech"].append(f_breech * decay)
                loads["barrel"].append(f_barrel * decay)
                pp = ATMOSPHERE + (p_port - ATMOSPHERE) * decay
                loads["port_p"].append(pp)
                loads["port_t"].append(max(t_port * (pp / p_port) ** ((gamma - 1) / gamma), 300.0))
                loads["port_u"].append(loads["port_u"][-1] * np.sqrt(decay))
            impulse += after * (1 - np.exp(-blowdown_time / tau))

    breech = np.array(hist["pb"])
    return ShotResult(
        model="lumped",
        left_muzzle=left,
        muzzle_velocity=state[2],
        muzzle_time=t,
        peak_breech_pressure=float(breech.max()) if breech.size else 0.0,
        burnt_at_muzzle=float(prop.burnt_fraction(state[0])),
        time=np.array(hist["t"]),
        travel=np.array(hist["x"]),
        velocity=np.array(hist["v"]),
        breech_pressure=breech,
        base_pressure=np.array(hist["pbase"]),
        recoil_impulse=impulse,
        loads=GunLoads(
            t=np.array(loads["t"]), breech_force=np.array(loads["breech"]), barrel_force=np.array(loads["barrel"]),
            port_pressure=np.array(loads["port_p"]), port_temperature=np.array(loads["port_t"]),
            head_area=head_area, port_position=port_travel, port_velocity=np.array(loads["port_u"])),
    )
