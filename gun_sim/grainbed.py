"""Two-phase grain bed: grains that move, drag on the gas, and a flame that spreads from the primer.

With solver.two_phase, fluid.py solves the propellant grains as a second phase
on the same moving mesh as the gas: the two-fluid model of interior
ballistics codes such as Gough's NOVA. Without it, grains are fixed slices of
the charge that all light at once.

* Grains. Each cell holds grains with their own velocity. They cross the cell
  faces at their speed relative to the mesh (a donor-cell flux, with Rusanov
  dissipation where the bed is packed) and cannot pass the breech or the
  projectile; after exit they can leave the muzzle unburnt. The state per
  cell is the initial mass Omega of the grains in it, how much of that is lit,
  and, carried with them, the lit grains' burnt web fraction z, the grains'
  velocity and the heat the unlit ones have absorbed. Lit and unlit grains are
  kept apart, so a few burning grains drifting into a cell do not light it:
  its own grains have to be heated to their ignition temperature.
* Forces. The gas pressure's push on a cell's contents is shared between gas
  and grains by the volume they take up (the grains' buoyancy, -alpha dp/dx
  with alpha the solid fraction). A packed bed resists being squeezed further
  with an intergranular stress that is zero below the packing it was loaded at
  (or a settled packing, PACKED) and grows like rho_p a^2 (alpha - alpha_0),
  stiffening without bound towards MAX_PACKING, so compression waves cross a
  just-packed bed at a = BED_WAVE_SPEED. The bed pushes on the breech, the
  chamber walls (a shoulder) and the projectile's base.
* Drag. Gidaspow's law: Ergun's packed-bed drag below a gas fraction of 0.8,
  Wen and Yu's for a dilute cloud above. It is applied implicitly (exactly
  over the step for the slip at its start), so a dense bed locks gas and grains
  together without a tiny time step. Momentum is kept, and the kinetic energy
  it removes heats the gas.
* Ignition. The primer's gas (as much as ignition.pressure gives when it fills
  the space round the grains, at the flame temperature) is injected through
  the flash hole into the first cell over ignition.duration, as a jet at the
  speed of sound; the rest of the chamber starts full of cold gas at ambient
  pressure. A grain lights when its surface reaches
  ignition.grain_ignition_temperature. The gas heats it with the packed-bed
  correlation Nu = 2 + 0.4 Re^(2/3) Pr^(1/3) (Gelperin and Einstein, as used by
  Gough), and its surface temperature rise follows from the heat H it has
  absorbed per unit area by an integral (quadratic-profile) solution for a
  semi-infinite solid: theta^2 = 3 q H / (2 k rho c), with q = h (T_gas - T_0 -
  theta). So the flame runs as fast as the hot gas is driven through the bed,
  and stagnant corners light late.
* Burning. A lit grain burns at the local pressure with the propellant's burn
  law and form function (a cell's lit grains share one z: lit grains that mix,
  or newly lit ones joining them, take their mean), and its gas joins the gas
  at the grain's velocity. The grains'
  surface per unit volume, for drag and heating, also comes from the form
  function: S/V = 2 psi'(z) / (web (1 - psi)), which is 6/d for a sphere of
  diameter d.
"""

from __future__ import annotations

import numpy as np

PACKED = 0.55            # solid fraction of a settled bed of grains
MAX_PACKING = 0.85       # the bed's stress grows without bound towards this solid fraction
BED_WAVE_SPEED = 280.0   # m/s, compression waves in a just-packed bed (Gough)
GAS_VISCOSITY = 8e-5     # Pa s, propellant gas (as fluid.py)
GAS_PRANDTL = 0.75
GRAIN_CONDUCTIVITY = 0.2       # W/(m K), nitrocellulose propellant
GRAIN_HEAT_CAPACITY = 1500.0   # J/(kg K)
GRAIN_TEMPERATURE = 300.0      # K, as loaded; the cold gas round it too
EMPTY = 1e-9             # a cell with less than this share of a slice's charge counts as empty


class GrainBed:
    """The grains on the bore solver's mesh.

    State U, (5, cells): Omega (initial mass of the grains in the cell), Omega_lit (of which lit),
    Omega_lit z (z of the lit grains), m u (the momentum of the unburnt grain), Omega_unlit H (heat
    per unit area the unlit grains have absorbed).
    """

    def __init__(self, gun, omega: np.ndarray, chamber_volume: float):
        p = self.prop = gun.propellant
        n = len(omega)
        self.U = np.zeros((5, n))
        self.U[0] = omega
        self.charge = float(omega.sum())
        self.tiny = EMPTY * self.charge / n
        loaded = p.charge_mass / p.density / chamber_volume
        self.alpha0 = min(max(loaded, PACKED), MAX_PACKING - 0.05)
        self.k_rho_c = GRAIN_CONDUCTIVITY * p.density * GRAIN_HEAT_CAPACITY
        self.surface0 = float(self._surface(np.zeros(1), np.zeros(1))[0])   # of a whole grain, 1/m
        self.theta_light = gun.ignition.grain_ignition_temperature - GRAIN_TEMPERATURE
        cp = p.gamma * p.gas_constant / (p.gamma - 1)
        self.k_gas = GAS_VISCOSITY * cp / GAS_PRANDTL
        self.e_release = p.impetus / (p.gamma - 1)
        # The primer: its gas, how long it takes to come out, and the flash-hole jet.
        p_ign = gun.ignition.pressure
        free = chamber_volume - p.charge_mass / p.density
        self.primer_mass = p_ign / (p.impetus + p.covolume * p_ign) * free
        self.primer_time = gun.ignition.duration
        self.jet = np.sqrt(2 * p.gamma / (p.gamma + 1) * p.impetus)   # sonic, at the flame temperature
        self.lit_time = np.full(n, np.nan)   # s, when each cell's grains first lit
        self.ejected = 0.0                   # kg of unburnt grain blown out of the muzzle

    @staticmethod
    def cold_gas(prop, pressure: float) -> tuple[float, float]:
        """Density and specific internal energy of the propellant gas at pressure and GRAIN_TEMPERATURE."""
        r_t = prop.gas_constant * GRAIN_TEMPERATURE
        return pressure / (r_t + prop.covolume * pressure), r_t / (prop.gamma - 1)

    # ---------- state ----------

    def unpack(self, U):
        """Per cell: Omega, lit Omega, the lit grains' z, velocity, the unlit grains' absorbed heat,
        unburnt mass, the lit grains' burnt fraction, and which cells hold grains."""
        om = np.maximum(U[0], 0.0)
        lit = np.clip(U[1], 0.0, om)
        full = om > self.tiny
        burning = lit > self.tiny
        unlit = om - lit
        z = np.where(burning, U[2] / np.where(burning, lit, 1.0), 0.0)
        heat = np.where(unlit > self.tiny, U[4] / np.where(unlit > self.tiny, unlit, 1.0), 0.0)
        psi = self.prop.burnt_fraction(np.clip(z, 0.0, self.prop.z_burnout))
        solid = om - lit * psi
        moves = full & (solid > self.tiny)
        u = np.where(moves, U[3] / np.where(moves, solid, 1.0), 0.0)
        return om, lit, z, u, heat, solid, psi, full

    def solid_volume(self, U) -> np.ndarray:
        """Volume of unburnt grain in each cell."""
        return self.unpack(U)[5] / self.prop.density

    def burnt(self) -> float:
        """Mass of the charge burnt so far (excluding what left the muzzle unburnt)."""
        om, lit, z, u, heat, solid, psi, full = self.unpack(self.U)
        return float(np.sum(lit * psi))

    def lit_share(self) -> float:
        """Share of the charge in the bore that has lit."""
        om, lit, *_ = self.unpack(self.U)
        return float(np.sum(lit) / max(np.sum(om), 1e-30))

    def stress(self, alpha):
        """Intergranular stress (Pa, over the whole cross-section) and the speed of compression waves in the bed."""
        a0, am = self.alpha0, MAX_PACKING
        x = np.clip(alpha, 0.0, am - 1e-3)
        over = np.maximum(x - a0, 0.0)
        rho_a2 = self.prop.density * BED_WAVE_SPEED**2
        s = rho_a2 * over * (am - a0) / (am - x)
        c = np.where(over > 0, BED_WAVE_SPEED * (am - a0) / (am - x), 0.0)
        return s, c

    def _surface(self, z, psi):
        """Grain surface per unit of unburnt grain volume (1/m), from the form function."""
        prop = self.prop
        eps = 1e-4
        ahead = prop.burnt_fraction(np.clip(z + eps, 0.0, prop.z_burnout))
        behind = prop.burnt_fraction(np.clip(z - eps, 0.0, prop.z_burnout))
        slope = np.maximum(ahead - behind, 0.0) / (np.minimum(z + eps, prop.z_burnout) - np.maximum(z - eps, 0.0))
        return 2 * np.maximum(slope, 1e-3) / (prop.web * np.maximum(1 - psi, 1e-6))

    # ---------- transport and forces (inside the bore solver's Runge-Kutta stages) ----------

    def rhs(self, U, nodes, area, w, v_cell, p, p_star, open_end: bool):
        """Rates of change of U on the moving mesh, and the grains' exchanges with the gas and the walls.

        nodes, area, w: the n+1 face positions, areas and speeds; v_cell, p: cell volumes and gas
        pressures; p_star: the gas pressure at the faces. open_end: the muzzle is open (after exit).
        Returns (dU, push, work, breech, base, walls, outflow, dt_max): the force the gas gives the
        grains in each cell (taken from the gas's momentum) and its work (from the gas's energy);
        the bed's stress on the breech face and on the projectile (Pa); its push on the chamber walls
        (N, + rearwards); unburnt grain leaving the muzzle (kg/s); and the time step it allows.
        """
        om, lit, z, ug, heat, solid, psi, full = self.unpack(U)
        n = len(om)
        alpha = solid / self.prop.density / v_cell
        s, cs = self.stress(alpha)
        # Donor-cell flux of grain through the moving faces, with Rusanov dissipation where it is packed.
        q = om / v_cell
        wf = w[1:-1]
        vl, vr = ug[:-1] - wf, ug[1:] - wf
        lam = np.maximum(np.abs(vl), np.abs(vr)) + np.maximum(cs[:-1], cs[1:])
        f = area[1:-1] * (0.5 * (q[:-1] * vl + q[1:] * vr) - 0.5 * lam * (q[1:] - q[:-1]))
        # What a unit of Omega carries with it: its lit share, their z, its momentum and its heat.
        per = np.where(full, 1 / np.where(full, om, 1.0), 0.0)
        share = lit * per
        carried = np.stack((np.ones(n), share, share * z, solid * per * ug, (1 - share) * heat))
        flux = np.zeros((5, n + 1))
        flux[:, 1:-1] = f * np.where(f > 0, carried[:, :-1], carried[:, 1:])
        outflow = 0.0
        if open_end:  # grains can blow out of the muzzle, never back in
            f_out = area[-1] * q[-1] * max(ug[-1] - w[-1], 0.0)
            flux[:, -1] = f_out * carried[:, -1]
            outflow = f_out * (1 - share[-1] * psi[-1])
        dU = -np.diff(flux, axis=1)

        # Forces: the grains' share of the gas pressure's push, and the bed's own stress.
        d_area = np.diff(area)
        push = np.clip(alpha, 0.0, 1.0) * (-np.diff(area * p_star) + p * d_area)
        sig = np.empty(n + 1)
        sig[1:-1] = 0.5 * (s[:-1] + s[1:])
        sig[0] = s[0]
        sig[-1] = 0.0 if open_end else s[-1]
        force = push - np.diff(area * sig) + s * d_area
        dU[3] += force

        centres = 0.5 * (w[:-1] + w[1:])
        speed = np.where(full, np.abs(ug - centres) + cs, 0.0)
        dt_max = float(np.min(np.diff(nodes) / np.maximum(speed, 1e-9)))
        return dU, push, push * ug, float(sig[0]), float(sig[-1]), float(np.sum(s * d_area)), outflow, dt_max

    # ---------- exchanges with the gas (split from the stages, exact over the step) ----------

    def exchange(self, t: float, dt: float, mass, mom, energy, v_cell):
        """Primer, drag, heating, ignition and burning over dt. Returns the gas's new (mass, momentum,
        energy) and the momentum the primer's jet gives the breech face (rearwards)."""
        prop = self.prop
        om, lit, z, ug, heat, solid, psi, full = self.unpack(self.U)
        b, r_gas = prop.covolume, prop.gas_constant
        mass, mom, energy = mass.copy(), mom.copy(), energy.copy()

        # Primer: its gas jets through the flash hole into the first cell.
        kick = 0.0
        if t < self.primer_time:
            dm = self.primer_mass / self.primer_time * min(dt, self.primer_time - t)
            mass[0] += dm
            mom[0] += dm * self.jet
            energy[0] += dm * self.e_release
            kick = dm * self.jet

        vs = solid / prop.density
        v_gas = np.maximum(v_cell - vs, 0.02 * v_cell)
        phi = v_gas / v_cell
        alpha = 1 - phi
        rho = mass / v_gas
        u = mom / mass
        e = energy / mass - 0.5 * u * u
        p = (prop.gamma - 1) * rho * e / (1 - b * rho)
        T = p * (1 - b * rho) / (rho * r_gas)
        ok = full & (solid > 0)
        # Grain surface: unlit grains are whole; lit ones have burnt to z.
        v_unlit = (om - lit) / prop.density
        surface = self.surface0 * v_unlit + self._surface(z, psi) * (vs - v_unlit)
        d = np.maximum(6 * vs / np.maximum(surface, 1e-30), 1e-6)
        slip = u - ug
        speed = np.abs(slip)

        # Drag (Gidaspow), implicit: the slip decays exactly, momentum is kept, lost energy heats the gas.
        mu = GAS_VISCOSITY
        re = phi * rho * speed * d / mu
        dense = 150 * alpha**2 * mu / (phi * d * d) + 1.75 * alpha * rho * speed / d
        cd_speed = np.where(re < 1000, 24 * mu / (phi * rho * d) * (1 + 0.15 * re**0.687), 0.44 * speed)
        dilute = 0.75 * cd_speed * alpha * phi * rho * phi**-2.65 / d
        beta = np.where(phi < 0.8, dense, dilute)
        m_s = np.where(ok, solid, 1.0)
        rate = beta * v_cell * (1 / mass + 1 / m_s)
        total = mass + m_s
        centre = (mass * u + m_s * ug) / total
        left = slip * np.exp(-rate * dt)
        u_new = np.where(ok, centre + m_s / total * left, u)
        ug_new = np.where(ok, centre - mass / total * left, ug)
        energy -= np.where(ok, 0.5 * m_s * (ug_new**2 - ug**2), 0.0)
        mom = mass * u_new

        # Heating of the unlit grains, and ignition once their surface is hot enough.
        unlit = ok & (om - lit > self.tiny)
        nu = 2 + 0.4 * (rho * speed * d / mu) ** (2 / 3) * GAS_PRANDTL ** (1 / 3)
        h = nu * self.k_gas / d
        excess = np.maximum(T - GRAIN_TEMPERATURE, 0.0)

        def surface_rise(absorbed):
            k = 1.5 * absorbed * h / self.k_rho_c
            return 0.5 * (-k + np.sqrt(k * k + 4 * k * excess))

        area = self.surface0 * v_unlit
        q = np.where(unlit, h * (excess - surface_rise(heat)), 0.0)
        gas_heat = np.minimum(q * area * dt, 0.5 * mass * e)
        energy -= gas_heat
        heat = heat + np.where(unlit, gas_heat / np.maximum(area, 1e-30), 0.0)
        light = unlit & (surface_rise(heat) >= self.theta_light)
        self.lit_time[light & np.isnan(self.lit_time)] = t + dt
        # Newly lit grains join the cell's burning ones at z = 0 (they share the mean z).
        z = np.where(light, lit * z / np.where(full, om, 1.0), z)
        lit = np.where(light, om, lit)

        # Burning: lit grains burn at the local pressure; their gas leaves at the grain's speed.
        burning = ok & (lit > self.tiny)
        z_new = np.where(burning, np.minimum(z + dt * prop.web_regression_rate(np.maximum(p, 0.0)),
                                             prop.z_burnout), z)
        dm = lit * (prop.burnt_fraction(z_new) - prop.burnt_fraction(z))
        mass += dm
        mom += dm * ug_new
        energy += dm * (self.e_release + 0.5 * ug_new**2)

        self.U = np.stack((om, lit, lit * z_new, (solid - dm) * ug_new, (om - lit) * heat))
        return mass, mom, energy, kick
