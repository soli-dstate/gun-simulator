"""Common result container returned by every ballistics model."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class MuzzleFlow:
    """What leaves the muzzle after the projectile does (fluid model with blowdown).

    Fluxes are positive out of the bore. Arrays share the time base `t` (s, from ignition).
    """
    exit_time: float          # s, projectile exit
    exit_pressure: float      # Pa, gas pressure at the muzzle at exit
    exit_gas_velocity: float  # m/s
    exit_density: float       # kg/m^3
    t: np.ndarray
    mdot: np.ndarray          # kg/s, mass flow
    edot: np.ndarray          # W, total energy flow (internal + kinetic + flow work)
    thrust: np.ndarray        # N, momentum flux + (p_exit - p_ambient) * bore area
    p_exit: np.ndarray        # Pa
    u_exit: np.ndarray        # m/s
    rho_exit: np.ndarray      # kg/m^3
    p_breech: np.ndarray      # Pa

    @property
    def ejected_mass(self) -> float:
        return float(np.sum(self.mdot[1:] * np.diff(self.t)))

    @property
    def ejected_energy(self) -> float:
        return float(np.sum(self.edot[1:] * np.diff(self.t)))


@dataclass
class GunLoads:
    """What the shot does to the gun, for recoil and the action (gun_sim/action.py).

    Forces are positive rearwards and are means over each sample's interval, so
    they integrate to the recoil impulse. Arrays share the time base `t`
    (s, from ignition), which runs on into the blowdown when there is one.
    """
    t: np.ndarray
    breech_force: np.ndarray      # N, gas on the bolt face (pressure over the inside of the case head)
    barrel_force: np.ndarray      # N, everything else: the chamber shoulder and the projectile's
                                  # drag on the bore push the barrel forwards (negative)
    port_pressure: np.ndarray     # Pa, gas at the gas port (ambient until the projectile passes it)
    port_temperature: np.ndarray  # K
    head_area: float              # m^2, inside of the case head the breech pressure pushes on
    port_position: float          # m of projectile travel from its seat to the port
    port_velocity: np.ndarray | None = None  # m/s, gas along the bore at the port

    @property
    def force(self) -> np.ndarray:
        return self.breech_force + self.barrel_force

    @property
    def impulse(self) -> float:
        return float(np.trapezoid(self.force, self.t))


@dataclass
class ShotResult:
    model: str
    left_muzzle: bool
    muzzle_velocity: float      # m/s
    muzzle_time: float          # s
    peak_breech_pressure: float # Pa
    burnt_at_muzzle: float      # fraction of the charge burnt when the projectile exits
    # Time histories, all the same length.
    time: np.ndarray
    travel: np.ndarray
    velocity: np.ndarray
    breech_pressure: np.ndarray
    base_pressure: np.ndarray
    # Optional pressure profiles along the bore (fluid model only):
    # list of (time, x positions, pressures).
    profiles: list = field(default_factory=list)
    # Fluid model with blowdown only.
    muzzle_flow: MuzzleFlow | None = None
    # N s, momentum given to the gun (includes the gas jet if blowdown ran).
    recoil_impulse: float | None = None
    # Forces on the gun and gas at the gas port over time, for gun_sim.action.
    loads: GunLoads | None = None
    # Fluid model with blowdown and a muzzle device: its 2D solution (gun_sim.devices.DeviceResult).
    device: object | None = None
    # Fluid model: heat lost to the wall (in the bore with solver.wall_losses,
    # and during blowdown), the barrel's mean temperature rise from it, and the
    # peak rise of the bore surface at the throat. K for both rises.
    heat_to_barrel: float | None = None  # J
    barrel_temperature_rise: float | None = None
    bore_temperature_rise: float | None = None
    # Fluid model: gas temperature along the column over time, [(t, K at BORE_GAS_POINTS
    # evenly spaced from the breech to the projectile base, or the muzzle after exit)].
    bore_gas: list = field(default_factory=list)
    # Fluid model with solver.two_phase (gun_sim/grainbed.py): the grain bed. Histories "t", "lit"
    # (share of the charge alight) and "burnt" (share burnt); "flame_spread_time" (s, until 99 % is
    # alight; None if it never was); "lit_time" (s, when the grains in each cell first lit) at
    # "cell_x" (m from the breech, where the cell started); "ejected" (kg of unburnt grain blown out
    # of the muzzle); "primer_mass" (kg); "profiles" [(t, x from the seated base, solid fraction,
    # grain velocity)] at the times of `profiles`.
    grain_bed: dict | None = None
    # Revolver (gun_sim/revolver.py): the gas lost through the cylinder gap. Arrays "t" (s), "mdot"
    # (kg/s) and "edot" (W, the enthalpy it carries); totals "mass" (kg) and "energy" (J); "position"
    # (m of travel where the projectile opened it) and "area" (m^2).
    gap_flow: dict | None = None

    def summary(self) -> str:
        status = "left muzzle" if self.left_muzzle else "DID NOT leave muzzle"
        return (
            f"[{self.model}] {status}\n"
            f"  muzzle velocity      {self.muzzle_velocity:9.1f} m/s\n"
            f"  time in barrel       {self.muzzle_time * 1e3:9.3f} ms\n"
            f"  peak breech pressure {self.peak_breech_pressure / 1e6:9.1f} MPa\n"
            f"  charge burnt at exit {self.burnt_at_muzzle * 100:9.1f} %"
            + (f"\n  heat to the barrel   {self.heat_to_barrel:9.1f} J"
               f" (+{self.barrel_temperature_rise:.2f} K bulk, +{self.bore_temperature_rise:.0f} K at the throat surface)"
               if self.heat_to_barrel else "")
            + (self._bed_summary() if self.grain_bed else "")
            + (f"\n  cylinder gap         {self.gap_flow['mass'] * 1e3:9.3f} g of gas out ({self.gap_flow['energy']:.0f} J)"
               if self.gap_flow else "")
        )

    def _bed_summary(self) -> str:
        g = self.grain_bed
        spread = (f"all alight {g['flame_spread_time'] * 1e3:.3f} ms after the primer" if g["flame_spread_time"]
                  else f"only {g['lit'][-1] * 100:.0f} % alight at exit")
        line = f"\n  grain bed (2-phase)  {spread}"
        if g["ejected"] > 1e-7:
            line += f"; {g['ejected'] * 1e6:.0f} mg blown out unburnt"
        return line
