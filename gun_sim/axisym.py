"""2-D axisymmetric compressible flow, for muzzle devices and gas ports.

The quasi-1D bore solver (fluid.py) handles the barrel. Where the geometry
really is two-dimensional (a brake or suppressor on the muzzle, or the gas port
in the barrel wall), this solver takes over, coupled to the bore at its
boundary.

* Equations: the compressible Euler equations in (x, r), with x along the bore
  and r its distance from the axis, for a mixture of air and propellant gas
  (both ideal, each with its own R and gamma). A conserved mass fraction Y
  tracks the propellant gas.
* Finite volumes on a grid of rectangular cells: uniform squares h on a side,
  or, given the face positions, cells that stretch away from a fine region (the
  muzzle plume, plume.py, reaches far out at little cost). A cell's volume is
  its ring, pi (r_out^2 - r_in^2) dx, and its faces are rings and cylinders;
  the hoop term p dA/dr in the radial momentum equation keeps a gas at rest at
  rest. The slopes are taken per cell, not per length, which is first-order
  accurate where the cells grow, so the stretching should be gentle.
* Walls: every face has an aperture, the share of it that is open. Solid cells
  have all their faces shut. A partly open face is a perforated plate: the flux
  passes through the open part, and the shut part is a wall that each side
  pushes on with its own pressure. This is how a gas port (a hole, which an
  axisymmetric grid can only draw as a ring) keeps its real area: the ring is
  one cell wide and open by port area / ring area. It is also how a brake's
  vents (slots round part of the circumference) are drawn. The pressure on the
  shut parts is the force of the gas on the solid, which is how the push of a
  brake or suppressor on the gun is found.
* Scheme: HLL fluxes (Davis wave speeds) with MUSCL reconstruction of the
  primitives (minmod, never across a shut face) and SSP-RK2 time stepping:
  second order where the flow is smooth.
* Boundaries: the axis is a mirror. The outer edges let the flow leave (zero
  gradient). "Fixed" cells hold a state given from outside: the bore solver's
  gas, entering the device.
* Afterburning (optional): propellant gas is fuel-rich (CO and H2). A sixth
  conserved scalar carries the fuel still unburnt. Where the gas has mixed with
  air and is hot enough, the fuel burns with the air's oxygen at a one-step
  Arrhenius rate and releases its heat: the secondary muzzle flash, or the
  "first-round pop" of the air in a suppressor. See Afterburn.
* Heat loss: gas next to a wall gives heat to the cold steel at Stanton number
  WALL_STANTON (rough, turbulent), with the gas speed plus a tenth of its sound
  speed standing in for the turbulence in a chamber. In a suppressor this is a
  large part of what it does.

The grid is coarse (a few cells across the bore) so that it runs in seconds in
NumPy: it resolves the volumes, flow paths and shock structure of a device, not
its boundary layers.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

DTYPE = np.float32  # half the memory traffic of float64; plenty for a few cells across a bore
R_AIR = 287.05
GAMMA_AIR = 1.4
WALL_STANTON = 0.004
WALL_TEMPERATURE = 300.0
O2_IN_AIR = 0.232  # mass fraction


@dataclass
class Afterburn:
    """Combustion of the propellant gas's fuel (CO, H2) with the air's oxygen.

    fuel: kg of fuel per kg of propellant gas; heat: J released per kg of fuel
    burnt; oxygen: kg of O2 it needs per kg. The rate is one-step Arrhenius,
    first order in whichever of fuel and oxygen runs out first:
    d(fuel)/dt = -min(fuel, O2 / oxygen) * rate * exp(-activation / T).
    activation is that of CO oxidation; rate is set so a stoichiometric mix
    lights within tens of microseconds at about 1100 K and hardly at all below
    900 K, which is where muzzle gas is found to reignite. Above ceiling the
    products (CO2, H2O) come apart as fast as they form, so burning stops
    there and goes on as the gas cools.
    """
    fuel: float
    heat: float
    oxygen: float
    rate: float = 2e10           # 1/s
    activation: float = 15000.0  # K
    ceiling: float = 2600.0      # K


def _minmod(a, b):
    s = np.sign(a)
    return s * np.maximum(0.0, np.minimum(np.abs(a), s * b))


class Axisymmetric:
    """Gas in an axisymmetric region of nx by nr cells; x from x0, r from 0.

    The cells are squares of size h, unless x_edges (nx+1) and r_edges (nr+1, from 0)
    give the face positions. open_x (nx+1, nr) and open_r (nx, nr+1) are the face
    apertures in [0, 1]; solid (nx, nr) marks cells that are not gas (all their
    faces must be shut). force_from: x (m) from which the pressure on shut
    x-faces counts towards the device's force. afterburn: burn the propellant
    gas's fuel with the air (adds a sixth conserved variable).
    """

    def __init__(self, h: float, x0: float, solid: np.ndarray, open_x: np.ndarray, open_r: np.ndarray,
                 gas_constant: float, gas_gamma: float, ambient_pressure: float, ambient_temperature: float,
                 force_from: float = 0.0, cfl: float = 0.8, wall_heat: bool = True,
                 x_edges: np.ndarray | None = None, r_edges: np.ndarray | None = None,
                 afterburn: Afterburn | None = None):
        self.solid = np.asarray(solid, bool)
        self.nx, self.nr = nx, nr = self.solid.shape
        xf = np.asarray(x_edges, float) if x_edges is not None else x0 + np.arange(nx + 1) * h
        r = np.asarray(r_edges, float) if r_edges is not None else np.arange(nr + 1) * h
        self.h, self.x0 = h, float(xf[0])
        self.fluid = ~self.solid
        self.open_x = np.asarray(open_x, DTYPE)
        self.open_r = np.asarray(open_r, DTYPE)
        self.cfl = cfl
        self.wall_heat = wall_heat
        self.p0, self.T0 = ambient_pressure, ambient_temperature
        self.x_edges, self.r_edges = xf, r
        hx, hr = np.diff(xf), np.diff(r)
        self.xc = 0.5 * (xf[:-1] + xf[1:])
        self.rc = 0.5 * (r[:-1] + r[1:])
        self.area_x = (np.pi * (r[1:] ** 2 - r[:-1] ** 2)).astype(DTYPE)   # (nr,) ring faces
        self.area_r = (2 * np.pi * r[None, :] * hx[:, None]).astype(DTYPE)  # (nx, nr+1) cylinder faces
        self.volume = (self.area_x[None, :] * hx[:, None]).astype(DTYPE)   # (nx, nr)
        self.d_area_r = np.diff(self.area_r, axis=1)
        self.size = np.minimum(hx[:, None], hr[None, :]).astype(DTYPE)     # (nx, nr), for the time step
        self.force_faces = (((xf >= force_from - 1e-12)[:, None] * (1 - self.open_x)) * self.area_x[None, :]).astype(DTYPE)
        shut_x = (1 - self.open_x) * self.area_x[None, :]
        shut_r = (1 - self.open_r) * self.area_r
        wall = shut_x[:-1] + shut_x[1:] + shut_r[:, :-1] + shut_r[:, 1:]
        self.wall_ratio = np.where(self.fluid, wall / self.volume, 0.0).astype(DTYPE)  # wall area / volume
        self._open_x = (self.open_x > 0).astype(DTYPE)[None]
        self._open_r = (self.open_r > 0).astype(DTYPE)[None]
        self._open_r[0, :, 0] = 1.0  # the axis: slopes see the mirror image
        self.out_right = self.open_x[-1] * self.area_x
        self.out_left = self.open_x[0] * self.area_x
        self.out_top = self.open_r[:, -1] * self.area_r[:, -1]

        self.afterburn = afterburn
        self.nv = 6 if afterburn else 5   # conserved: rho, rho u, rho v, E, rho Y (, rho fuel)
        self.rp, self.gp = gas_constant, gas_gamma
        self.cva, self.cvp = R_AIR / (GAMMA_AIR - 1), gas_constant / (gas_gamma - 1)
        rho_a = ambient_pressure / (R_AIR * ambient_temperature)
        self.U = np.zeros((self.nv, nx, nr), DTYPE)
        self.U[0] = rho_a
        self.U[3] = ambient_pressure / (GAMMA_AIR - 1)
        self.fixed = np.zeros((nx, nr), bool)
        self.fixed_state = None
        self.t = 0.0
        self.steps = 0
        # Running totals: what has left through the outer edges, the impulse on the device
        # (+x forwards), the heat given to the walls and the heat afterburning released.
        self.out = np.zeros(self.nv)   # mass, x-momentum (gauge), -, energy (total enthalpy), propellant (, fuel)
        self.impulse = 0.0
        self.heat = 0.0
        self.burnt = 0.0

    # ---------- state ----------

    def set_fixed(self, mask: np.ndarray, rho: float, u: float, e: float, Y: float = 1.0) -> None:
        """Hold the cells in mask at this gas state (velocity u along x, internal energy e per kg)."""
        if not np.array_equal(self.fixed, mask):
            self.fixed = np.asarray(mask, bool)
            # Faces of held cells are inflow, not flow leaving the domain.
            self.out_left = self.open_x[0] * self.area_x * ~self.fixed[0]
            self.out_right = self.open_x[-1] * self.area_x * ~self.fixed[-1]
            self.out_top = self.open_r[:, -1] * self.area_r[:, -1] * ~self.fixed[:, -1]
        state = [rho, rho * u, 0.0, rho * (e + 0.5 * u * u), rho * Y]
        if self.afterburn:
            state.append(rho * Y * self.afterburn.fuel)
        self.fixed_state = np.array(state, DTYPE)
        self._apply_fixed(self.U)

    def _apply_fixed(self, U):
        if self.fixed_state is not None and self.fixed.any():
            U[:, self.fixed] = self.fixed_state[:, None]

    def _mix(self, Y):
        cv = self.cva + Y * (self.cvp - self.cva)
        return cv, R_AIR + Y * (self.rp - R_AIR)

    def primitives(self, U=None):
        U = self.U if U is None else U
        rho = U[0]
        u = U[1] / rho
        v = U[2] / rho
        Y = np.clip(U[4] / rho, 0.0, 1.0)
        cv, rg = self._mix(Y)
        e = np.maximum(U[3] / rho - 0.5 * (u * u + v * v), 1.0)
        return rho, u, v, rho * rg / cv * e, Y, cv, rg

    def pressure(self) -> np.ndarray:
        return self.primitives()[3]

    def temperature(self) -> np.ndarray:
        rho, _, _, p, _, _, rg = self.primitives()
        return p / (rho * rg)

    def mass_in(self, mask: np.ndarray) -> float:
        """Gas mass in the cells of mask."""
        return float(np.sum(self.U[0] * mask * self.volume, dtype=np.float64))

    # ---------- fluxes ----------

    def _hll(self, WL, WR):
        """HLL flux, with the first velocity component normal to the face. W = (rho, un, ut, p, Y(, fuel))."""
        F = []
        cons = []
        speeds = []
        for W in (WL, WR):
            rho, un, ut, p, Y = W[:5]
            cv, rg = self._mix(Y)
            g1 = rg / cv                      # gamma - 1
            E = p / g1 + 0.5 * rho * (un * un + ut * ut)
            m = rho * un
            cons.append((rho, m, rho * ut, E) + tuple(rho * z for z in W[4:]))
            F.append((m, m * un + p, m * ut, (E + p) * un) + tuple(m * z for z in W[4:]))
            c = np.sqrt((1 + g1) * p / rho)
            speeds.append((un - c, un + c))
        (a1, b1), (a2, b2) = speeds
        sl = np.minimum(np.minimum(a1, a2), 0.0)
        sr = np.maximum(np.maximum(b1, b2), 0.0)
        inv = 1.0 / (sr - sl + 1e-30)
        wl, wr, wd = sr * inv, -sl * inv, sl * sr * inv
        out = np.empty((self.nv,) + sl.shape, DTYPE)
        for k in range(self.nv):
            out[k] = wl * F[0][k] + wr * F[1][k] + wd * (cons[1][k] - cons[0][k])
        return out

    def _faces(self, W, axis):
        """Left and right states at every face along axis (1 = x, 2 = r), MUSCL with ghost cells.

        Differences across shut faces count as zero, so a wall doesn't bend the slopes.
        The outer edges copy the edge cell; the axis mirrors it.
        """
        if axis == 1:
            n = self.nx
            d = np.zeros((self.nv, n + 1, self.nr), DTYPE)
            d[:, 1:-1] = W[:, 1:] - W[:, :-1]
            d *= self._open_x
            slope = _minmod(d[:, :-1], d[:, 1:])
            left = np.empty_like(d)
            right = np.empty_like(d)
            left[:, 1:] = W + 0.5 * slope
            left[:, 0] = W[:, 0]
            right[:, :-1] = W - 0.5 * slope
            right[:, -1] = W[:, -1]
            return left, right
        n = self.nr
        d = np.zeros((self.nv, self.nx, n + 1), DTYPE)
        d[:, :, 1:-1] = W[:, :, 1:] - W[:, :, :-1]
        d[2, :, 0] = 2 * W[2, :, 0]   # v against its mirror image
        d *= self._open_r
        slope = _minmod(d[:, :, :-1], d[:, :, 1:])
        left = np.empty_like(d)
        right = np.empty_like(d)
        left[:, :, 1:] = W + 0.5 * slope
        left[:, :, 0] = W[:, :, 0]
        left[2, :, 0] = -W[2, :, 0]
        right[:, :, :-1] = W - 0.5 * slope
        right[:, :, -1] = W[:, :, -1]
        return left, right

    def _rhs(self, U):
        rho, u, v, p, Y, cv, rg = self.primitives(U)
        W = np.stack((rho, u, v, p, Y) + ((np.clip(U[5] / rho, 0.0, 1.0),) if self.afterburn else ()))
        # x faces: normal u, tangential v.
        WL, WR = self._faces(W, 1)
        F = self._hll(WL, WR)
        a = self.open_x
        FxL = a * F
        FxR = FxL.copy()
        FxL[1] += (1 - a) * WL[3]   # the shut part: a wall each side pushes on with its own pressure
        FxR[1] += (1 - a) * WR[3]
        force = float(np.sum(self.force_faces * (WL[3] - WR[3])))
        # r faces: normal v, tangential u.
        swap = [0, 2, 1, 3, 4, 5][:self.nv]
        WL, WR = self._faces(W, 2)
        WL, WR = WL[swap], WR[swap]
        G = self._hll(WL, WR)[swap]
        b = self.open_r
        GL = b * G
        GR = GL.copy()
        GL[2] += (1 - b) * WL[3]
        GR[2] += (1 - b) * WR[3]

        ax, ar = self.area_x[None, None, :], self.area_r[None]
        dU = -((FxL[:, 1:] - FxR[:, :-1]) * ax + (GL[:, :, 1:] * ar[:, :, 1:] - GR[:, :, :-1] * ar[:, :, :-1]))
        dU[2] += p * self.d_area_r
        dU /= self.volume[None]
        dU[:, self.solid] = 0.0
        dU[:, self.fixed] = 0.0
        flows = F[:, -1] @ self.out_right - F[:, 0] @ self.out_left + G[:, :, -1] @ self.out_top
        flows[1] -= self.p0 * (self.out_right.sum() - self.out_left.sum())
        c = np.sqrt((1 + rg / cv) * p / rho)
        return dU, flows, force, (u, v, c, rho, p, rg, cv)

    def max_dt(self, prims=None) -> float:
        u, v, c = (prims if prims is not None else self._speeds())[:3]
        rate = np.where(self.fluid, (np.abs(u) + np.abs(v) + 2 * c) / self.size, 0.0)
        return self.cfl / max(float(rate.max()), 1e-9)

    def _speeds(self):
        rho, u, v, p, Y, cv, rg = self.primitives()
        return u, v, np.sqrt((1 + rg / cv) * p / rho)

    # ---------- time stepping ----------

    def step(self, dt_max: float) -> float:
        """One SSP-RK2 step of at most dt_max. Returns the step taken."""
        k1, f1, force1, prims = self._rhs(self.U)
        dt = min(self.max_dt(prims), dt_max)
        U1 = self.U + dt * k1
        self._apply_fixed(U1)
        k2, f2, force2, _ = self._rhs(U1)
        U = 0.5 * (self.U + U1 + dt * k2)
        self._apply_fixed(U)
        if self.wall_heat:
            self._cool(U, dt)
        if self.afterburn:
            self._burn(U, dt)
        self.U = U
        self.out += 0.5 * dt * (f1 + f2)
        self.impulse += 0.5 * dt * (force1 + force2)
        self.t += dt
        self.steps += 1
        return dt

    def advance(self, duration: float) -> float:
        """Step forward by duration. Returns the mean force on the device over it (+x forwards)."""
        start = self.impulse
        left = duration
        while left > 1e-15:
            left -= self.step(left)
        return (self.impulse - start) / duration if duration > 0 else 0.0

    def _cool(self, U, dt):
        """Heat loss to the walls, decaying exactly towards the wall temperature."""
        rho, u, v, p, Y, cv, rg = self.primitives(U)
        T = p / (rho * rg)
        speed = np.sqrt(u * u + v * v) + 0.1 * np.sqrt((1 + rg / cv) * p / rho)
        k = (1 + rg / cv) * WALL_STANTON * speed * self.wall_ratio
        q = rho * cv * np.maximum(T - WALL_TEMPERATURE, 0.0) * (1 - np.exp(-k * dt))
        q[self.fixed] = 0.0
        U[3] -= q
        self.heat += float(np.sum(q * self.volume))

    def fuel_oxygen(self, U=None):
        """Mass fractions of the unburnt fuel and of the oxygen left in each cell (afterburn only)."""
        U = self.U if U is None else U
        a = self.afterburn
        rho = U[0]
        Y = np.clip(U[4] / rho, 0.0, 1.0)
        fuel = np.clip(U[5] / rho, 0.0, a.fuel)
        # The air's oxygen, less what the burnt fuel (fuel * Y at birth, less what's left) took.
        o2 = np.maximum(O2_IN_AIR * (1 - Y) - a.oxygen * (a.fuel * Y - fuel), 0.0)
        return fuel, o2

    def _burn(self, U, dt):
        """Afterburning: the fuel burns with the oxygen it has mixed with, exactly over dt at fixed T."""
        a = self.afterburn
        rho, _, _, p, _, cv, rg = self.primitives(U)
        T = p / (rho * rg)
        fuel, o2 = self.fuel_oxygen(U)
        k = a.rate * np.exp(-a.activation / np.maximum(T, 200.0))
        burnt = np.minimum(fuel, o2 / a.oxygen) * (1 - np.exp(-k * dt))
        burnt = np.minimum(burnt, np.maximum(cv * (a.ceiling - T), 0.0) / a.heat)
        burnt[self.fixed | self.solid] = 0.0
        U[5] -= rho * burnt
        U[3] += rho * burnt * a.heat
        self.burnt += float(np.sum(rho * burnt * self.volume, dtype=np.float64)) * a.heat
