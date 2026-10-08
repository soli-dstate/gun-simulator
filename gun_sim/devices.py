"""Muzzle devices and the gas port, solved in 2D (axisym.py) and coupled to the bore.

Muzzle device. A brake or suppressor is drawn on an axisymmetric grid around
the muzzle (x = 0 at the muzzle face): the end of the barrel, the device, and
air all round it, behind the muzzle too so a brake's jets can turn back.

* Brake: `baffles` plates spaced along a tube; each chamber in front of the
  muzzle or a plate vents sideways through slots that open `vent_fraction` of
  the circumference (perforated faces in the tube wall). The gas that hits the
  plates and turns out of the slots pushes the brake forwards, against the
  recoil.
* Suppressor: a closed tube with a blast chamber, then baffles (flat, or cones
  pointing back at the muzzle), and a front cap. The gas has to fill the
  chambers and work its way out through the holes, cooling on the steel, so it
  leaves later, slower and colder.

Coupling. During the bore's blowdown (fluid.py), the gas in the bore's last
cell is fed into the device's inlet cells, and the pressure the device builds
in front of the muzzle is handed back as the bore's outlet pressure whenever
the exit flow is subsonic. So a suppressor's back-pressure slows the bore's
emptying (and raises the pressure at a gas port). The device is solved for
`solver.device_time` after exit. After that it becomes a vessel (0-D): the gas
in it, and what the bore still sends, mix and vent to the air through its exit
hole (and a brake's slots) as through an orifice. Its push on the gun is then
the momentum the bore's jet brings in, less the thrust of what leaves forwards,
so momentum balances to the end.

What comes out: the force on the device (added to the gun's loads), what
leaves the device region (the source of the muzzle blast in gun_sim.sound),
how much of the jet's forward momentum survives (it sets the blast's
directivity), the heat it took, and snapshots of the pressure field.

Gas port. A port is a hole in the side of the barrel, which an axisymmetric
grid can only draw as a ring. The ring is one cell wide and its faces are
open by port area / ring area, so it passes the port's area; the gas cylinder
is drawn as a ring chamber of the same volume over it. The bore gas at the
port (from the bore solver) flows past, the chamber fills, and the port's
discharge coefficient is the one for which the action model's orifice fills a
cylinder with the same mass. The 2D port loses flow to the crossflow in the
bore and the turn into the hole, which a fixed coefficient can only guess.
"""

from __future__ import annotations

import json
import math
import threading
from dataclasses import asdict, dataclass, field

import numpy as np

from .axisym import Axisymmetric

STEEL_DENSITY = 7850.0
SNAPSHOTS = 10


def _shut(solid, open_x, open_r):
    """Close every face of the solid cells."""
    open_x[:-1][solid] = 0.0
    open_x[1:][solid] = 0.0
    open_r[:, :-1][solid] = 0.0
    open_r[:, 1:][solid] = 0.0


def cell_size(gun) -> float:
    """Cell size: a whole number of cells across the bore radius, so the bore keeps its area."""
    return gun.barrel.bore_diameter / 2 / max(1, round(gun.solver.device_resolution / 2))


def dimensions(gun) -> dict:
    """The device's dimensions, filled in from the bore where the config leaves them out."""
    d = gun.muzzle_device
    bore = gun.barrel.bore_diameter
    brake = d.type == "brake"
    length = d.length or (8 if brake else 23) * bore
    od = d.outer_diameter or max(gun.barrel.muzzle_diameter + 4 * d.wall, (2.8 if brake else 5.1) * bore)
    baffles = d.baffles or (3 if brake else 8)
    blast = d.blast_chamber or min(5 * bore, 0.4 * length)
    return {"type": d.type, "length": length, "outer_radius": od / 2, "baffles": int(baffles),
            "hole_radius": bore / 2 + d.bore_clearance / 2, "wall": d.wall, "blast_chamber": blast,
            "baffle_angle": d.baffle_angle, "vent_fraction": d.vent_fraction}


@dataclass
class Grid:
    """A geometry on the 2D grid."""
    h: float
    x0: float
    solid: np.ndarray
    open_x: np.ndarray
    open_r: np.ndarray
    device: np.ndarray       # cells that belong to the device (solid steel of it)
    inside: np.ndarray       # gas cells inside the device
    inlet: np.ndarray        # bore cells held at the bore's exit state
    probe: np.ndarray        # bore cells whose pressure is handed back to the bore
    dims: dict = field(default_factory=dict)


def draw(gun, X, Rr, h):
    """The end of the barrel and the device on cells centred at X, Rr (2D arrays, m).

    h is the size of the cells round the device, the thinnest a wall can be.
    Returns solid, open_x, open_r, device (its steel), inside (gas cells in it) and the muzzle's radius.
    """
    dims = dimensions(gun)
    bore = gun.barrel.bore_diameter
    L, R, w = dims["length"], dims["outer_radius"], max(dims["wall"], h)
    rb, rh = bore / 2, dims["hole_radius"]
    r_muzzle = max(gun.barrel.muzzle_diameter / 2, rb + 2 * h)
    nx, nr = X.shape
    solid = (X < 0) & (Rr > rb) & (Rr < r_muzzle)          # the barrel
    dev = np.zeros_like(solid)
    slots = []  # (x_start, x_end) of each brake vent
    r_in = R - w
    if dims["type"] != "none":
        dev |= (X >= 0) & (X < L) & (Rr >= r_in) & (Rr < R)   # the tube
    if dims["type"] == "brake":
        n = dims["baffles"]
        pitch = L / n
        for k in range(1, n + 1):
            xb = k * pitch
            dev |= (X >= xb - w) & (X < xb) & (Rr >= rh) & (Rr < R)
            slots.append(((k - 1) * pitch + (w if k > 1 else 0.0) + w, xb - w - w))
        dev |= (X >= 0) & (X < w) & (Rr >= r_muzzle) & (Rr < R)   # rear ring round the muzzle
    elif dims["type"] == "suppressor":
        dev |= (X >= 0) & (X < w) & (Rr >= rb) & (Rr < R)          # rear cap
        dev |= (X >= L - w) & (X < L) & (Rr >= rh) & (Rr < R)      # front cap
        n = dims["baffles"]
        start, end = w + dims["blast_chamber"], L - w
        tan = math.tan(math.radians(dims["baffle_angle"]))
        thick = max(w / math.cos(math.radians(dims["baffle_angle"])), h * (1 + tan) * 1.01)
        for k in range(n):
            xk = start + (end - start) * k / max(n, 1)
            # A cone's tip (the hole) points back at the muzzle; it leans forward with radius.
            xs = xk + (Rr - rh) * tan
            dev |= (X >= xs) & (X < xs + thick) & (Rr >= rh) & (Rr < r_in + h) & (X < end)
    solid |= dev
    open_x = np.ones((nx + 1, nr))
    open_r = np.ones((nx, nr + 1))
    # Brake vents: the tube wall in each slot is gas, with its radial faces open by vent_fraction
    # and its axial faces too (gas can run along the slot); the slot's ends are shut.
    for xs, xe in slots:
        if xe - xs < h:
            continue
        cells = (X >= xs) & (X < xe) & (Rr >= r_in) & (Rr < R)
        solid &= ~cells
        dev &= ~cells
        i_cells, j_cells = np.nonzero(cells)
        for i, j in zip(i_cells, j_cells):
            open_r[i, j] = min(open_r[i, j], dims["vent_fraction"])
            open_r[i, j + 1] = min(open_r[i, j + 1], dims["vent_fraction"])
            open_x[i, j] = min(open_x[i, j], dims["vent_fraction"])
            open_x[i + 1, j] = min(open_x[i + 1, j], dims["vent_fraction"])
    _shut(solid, open_x, open_r)
    inside = (X >= 0) & (X < L) & (Rr < r_in) & ~solid if dims["type"] != "none" else np.zeros_like(solid)
    return solid, open_x, open_r, dev, inside, r_muzzle


def device_grid(gun) -> Grid:
    """The muzzle, the device and the air round them."""
    dims = dimensions(gun)
    bore = gun.barrel.bore_diameter
    h = cell_size(gun)
    L, R = dims["length"], dims["outer_radius"]
    # Room for the jets: a brake's go out sideways and back, a suppressor's forwards.
    if dims["type"] == "brake":
        back, front, r_top = max(4 * bore, 0.5 * L), max(5 * bore, 0.25 * L), R + max(3 * bore, R)
    else:
        back, front, r_top = 2 * bore, max(3 * bore, 0.15 * L), R + max(1.5 * bore, 0.4 * R)
    nx = int(math.ceil((back + L + front) / h))
    nr = int(math.ceil(r_top / h))
    x0 = -math.ceil(back / h) * h
    xc = x0 + (np.arange(nx) + 0.5) * h
    rc = (np.arange(nr) + 0.5) * h
    X, Rr = np.meshgrid(xc, rc, indexing="ij")
    solid, open_x, open_r, dev, inside, r_muzzle = draw(gun, X, Rr, h)
    rb = bore / 2
    inlet = (X < x0 + 2 * h) & (Rr < rb)
    probe = (X >= x0 + 2 * h) & (X < x0 + 3 * h) & (Rr < rb)
    dims.update(h=h, x0=x0, nx=nx, nr=nr, r_muzzle=r_muzzle)
    return Grid(h, x0, solid, open_x, open_r, dev, inside, inlet, probe, dims)


def device_mass(gun) -> float:
    """Mass of the device: given, or its steel on the grid."""
    if gun.muzzle_device.type == "none":
        return 0.0
    if gun.muzzle_device.mass is not None:
        return gun.muzzle_device.mass
    g = device_grid(gun)
    rings = np.pi * ((np.arange(g.dims["nr"]) + 1) ** 2 - np.arange(g.dims["nr"]) ** 2) * g.h**3
    volume = float(np.sum(g.device * rings[None, :]))
    return STEEL_DENSITY * volume


@dataclass
class DeviceResult:
    """The muzzle device: 2D over its window after exit, then a venting vessel to the end of the blowdown."""
    dims: dict
    t: np.ndarray             # s from ignition
    force: np.ndarray         # N, gas pushing the device forwards (against recoil)
    pressure: np.ndarray      # Pa, mean gas pressure inside the device
    back_pressure: np.ndarray  # Pa, pressure handed back to the bore
    out_mass: np.ndarray      # kg, cumulative, leaving the device region
    out_energy: np.ndarray    # J, cumulative total enthalpy, less the still air's
    out_propellant: np.ndarray  # kg, cumulative
    out_momentum: np.ndarray  # N s, cumulative forward momentum leaving
    in_momentum: np.ndarray   # N s, cumulative forward momentum the bore's jet brought in
    heat: float               # J taken by the walls
    window_end: float         # s from ignition, when the 2D solution handed over to the vessel
    stored_mass: float        # kg of gas over the still air's that was inside at the hand-over
    snapshots: list           # [(t, pressure field (nx, nr), Pa)]
    grid: Grid
    steps: int

    @property
    def impulse(self) -> float:
        """Forward impulse of the gas on the device (N s)."""
        return float(np.trapezoid(self.force, self.t)) if len(self.t) > 1 else 0.0

    @property
    def momentum_ratio(self) -> float:
        """Share of the jet's forward momentum that leaves the device going forwards."""
        return float(np.clip(self.out_momentum[-1] / max(self.in_momentum[-1], 1e-12), 0.0, 1.0))

    def at(self, t: float) -> float:
        """Forward force on the device at time t (0 outside the record)."""
        return float(np.interp(t, self.t, self.force, left=0.0, right=0.0))


class DeviceCoupling:
    """The device solver, stepped along with the bore's blowdown."""

    def __init__(self, gun, ambient_pressure: float, ambient_temperature: float = 288.15):
        self.gun = gun
        self.grid = g = device_grid(gun)
        prop = gun.propellant
        self.solver = Axisymmetric(g.h, g.x0, g.solid, g.open_x, g.open_r, prop.gas_constant, prop.gamma,
                                   ambient_pressure, ambient_temperature, force_from=0.0)
        self.p0 = ambient_pressure
        self.rec = {k: [] for k in ("t", "force", "pressure", "back", "mass", "energy", "prop", "mom", "in_mom")}
        self.in_momentum = 0.0
        self.snapshots = []
        self.window = gun.solver.device_time
        self.start = None
        self.done = False
        rho_a = ambient_pressure / (287.05 * ambient_temperature)
        self.ambient_mass = rho_a * float(np.sum(g.inside * self.solver.volume))
        self.cv_p = prop.gas_constant / (prop.gamma - 1)
        self.bore_area = gun.barrel.bore_area
        self.h_air = 1.4 / 0.4 * 287.05 * ambient_temperature
        self.vessel = None
        self.window_end = None

    def step(self, t: float, dt: float, rho: float, u: float, e: float) -> tuple[float, float, float]:
        """Advance by dt with the bore's exit gas (density, velocity, specific internal energy).

        Returns the gas just past the inlet (density, velocity, pressure), for the
        bore's outlet: the two solvers overlap by a cell, each seeing the other's
        neighbouring state, so waves pass both ways.
        """
        if self.done:
            return self._vessel_step(t, dt, rho, u, e)
        s = self.solver
        if self.start is None:
            self.start = t
            self.next_snap = t
        s.set_fixed(self.grid.inlet, rho, max(u, 0.0), e)
        force = s.advance(dt)
        rho_2d, u_2d, _, p, *_ = s.primitives()
        # The jet's thrust at the muzzle: momentum flux plus its gauge pressure.
        p_jet = (self.gun.propellant.gamma - 1) * rho * e
        self.in_momentum += dt * self.bore_area * (rho * max(u, 0.0) ** 2 + p_jet - self.p0)
        probe = self.grid.probe
        back = float(np.mean(p[probe]))
        state = (float(np.mean(rho_2d[probe])), float(np.mean(u_2d[probe])), back)
        r = self.rec
        r["t"].append(t + dt)
        r["force"].append(force)
        r["pressure"].append(float(np.mean(p[self.grid.inside])))
        r["back"].append(back)
        r["mass"].append(s.out[0])
        r["energy"].append(s.out[3] - self.h_air * (s.out[0] - s.out[4]))  # less the still air's enthalpy
        r["prop"].append(s.out[4])
        r["mom"].append(s.out[1])
        r["in_mom"].append(self.in_momentum)
        if t + dt >= self.next_snap and len(self.snapshots) < SNAPSHOTS:
            self.snapshots.append((t + dt, p.astype(np.float32)))
            self.next_snap += self.window / (SNAPSHOTS - 1)
        if t + dt - self.start >= self.window:
            self.done = True
            self._hand_over(t + dt)
        return state

    # ---------- after the 2D window: the device as a venting vessel ----------

    def _hand_over(self, t):
        s, g = self.solver, self.grid
        rho, u, v, p, Y, cv, rg = s.primitives()
        vol = g.inside * s.volume
        V = float(vol.sum())
        m = float(np.sum(rho * vol, dtype=np.float64))
        e_int = float(np.sum(p / (rg / cv) * vol, dtype=np.float64))
        m_p = float(np.sum(rho * Y * vol, dtype=np.float64))
        dims = g.dims
        hole = np.pi * dims["hole_radius"] ** 2
        vents = 0.0
        if dims["type"] == "brake":
            r_in = dims["outer_radius"] - max(dims["wall"], g.h)
            vents = 2 * np.pi * r_in * dims["length"] * 0.5 * dims["vent_fraction"]
        self.vessel = {"V": V, "m": m, "mp": m_p, "E": e_int, "area": hole + vents, "forward": hole / (hole + vents)}
        self.window_end = t
        self.stored_mass = max(m - self.ambient_mass, 0.0)

    def _vessel_step(self, t, dt, rho, u, e):
        """The bore's jet flows in; the mixture vents to the air (choked or subsonic orifice)."""
        from .action import _orifice
        ves, r = self.vessel, self.rec
        prop = self.gun.propellant
        u = max(u, 0.0)
        g_b = prop.gamma
        mdot_in = rho * u * self.bore_area
        edot_in = mdot_in * (g_b * e + 0.5 * u * u)            # total enthalpy flow
        mom_in = self.bore_area * (rho * u * u + (g_b - 1) * rho * e - self.p0)
        y = min(ves["mp"] / ves["m"], 1.0)
        rg = 287.05 + y * (prop.gas_constant - 287.05)
        cv = 287.05 / 0.4 + y * (prop.gas_constant / (g_b - 1) - 287.05 / 0.4)
        gam = 1 + rg / cv
        p = ves["E"] * (gam - 1) / ves["V"]
        T = p * ves["V"] / (ves["m"] * rg)
        mdot_out = _orifice(ves["area"], p, T, self.p0, gam, rg)
        # A big vent empties the vessel faster than a step: it can't let out more than it
        # holds over still air at its temperature.
        spare = ves["m"] - self.p0 * ves["V"] / (rg * T) + dt * mdot_in
        mdot_out = min(mdot_out, max(spare, 0.0) / dt)
        # Thrust of the forward-going part of the outflow: sonic or subsonic jet with exit pressure.
        crit = (2 / (gam + 1)) ** (gam / (gam - 1))
        p_e = max(p * crit, self.p0)
        T_e = T * (p_e / p) ** ((gam - 1) / gam)
        u_e = np.sqrt(max(2 * gam / (gam - 1) * rg * (T - T_e), 0.0))
        thrust = ves["forward"] * (mdot_out * u_e + (p_e - self.p0) * ves["area"] * 0.8)
        h_out = gam / (gam - 1) * rg * T
        ves["mp"] += dt * (mdot_in - mdot_out * y)
        ves["m"] += dt * (mdot_in - mdot_out)
        ves["E"] += dt * (edot_in - mdot_out * h_out)
        force = mom_in - thrust
        r["t"].append(t + dt)
        r["force"].append(force)
        r["pressure"].append(p)
        r["back"].append(p)
        r["mass"].append(r["mass"][-1] + dt * mdot_out)
        r["energy"].append(r["energy"][-1] + dt * mdot_out * (h_out - (1 - y) * self.h_air))
        r["prop"].append(r["prop"][-1] + dt * mdot_out * y)
        r["mom"].append(r["mom"][-1] + dt * thrust)
        self.in_momentum += dt * mom_in
        r["in_mom"].append(self.in_momentum)
        return (ves["m"] / ves["V"], 0.0, p)

    def result(self) -> DeviceResult:
        s, g, r = self.solver, self.grid, self.rec
        if self.window_end is None:  # the blowdown ended inside the window
            self._hand_over(r["t"][-1] if r["t"] else 0.0)
        arr = {k: np.array(v) for k, v in r.items()}
        return DeviceResult(dims=g.dims, t=arr["t"], force=arr["force"], pressure=arr["pressure"],
                            back_pressure=arr["back"], out_mass=arr["mass"], out_energy=arr["energy"],
                            out_propellant=arr["prop"], out_momentum=arr["mom"], in_momentum=arr["in_mom"],
                            heat=s.heat, window_end=self.window_end, stored_mass=self.stored_mass,
                            snapshots=self.snapshots, grid=g, steps=s.steps)


# ---------- gas port ----------

_port_cache: dict = {}
_port_lock = threading.Lock()


def port_grid(gun) -> tuple[Grid, np.ndarray]:
    """Bore, port ring and gas chamber ring. Returns the grid and the chamber cells."""
    a = gun.action
    bore = gun.barrel.bore_diameter
    rb = bore / 2
    # Cells no bigger than the port (where that is affordable): the faces' apertures carry its true area.
    h = rb / max(1, math.ceil(rb / min(cell_size(gun), max(a.gas_port_diameter, rb / 4))))
    port_area = math.pi / 4 * a.gas_port_diameter**2
    wall = max(2.5e-3, 2 * h)
    half = 10 * h + bore
    r_w = rb + wall
    chamber_len = max(4 * h, 2 * a.gas_port_diameter)
    r_c = math.sqrt(a.gas_volume / (math.pi * chamber_len) + r_w**2)
    nx = int(math.ceil(2 * half / h))
    nr = int(math.ceil(r_c / h)) + 1
    x0 = -nx * h / 2
    xc = x0 + (np.arange(nx) + 0.5) * h
    rc = (np.arange(nr) + 0.5) * h
    X, Rr = np.meshgrid(xc, rc, indexing="ij")
    i_port = int(np.argmin(np.abs(xc)))
    port = (np.arange(nx)[:, None] == i_port) & (Rr >= rb) & (Rr < r_w)
    chamber = (np.abs(X) < chamber_len / 2) & (Rr >= r_w) & (Rr < r_c)
    solid = (Rr >= rb) & ~port & ~chamber
    open_x = np.ones((nx + 1, nr))
    open_r = np.ones((nx, nr + 1))
    _shut(solid, open_x, open_r)
    # The port ring passes the port's area: its faces are open by port area / ring area.
    for j in np.nonzero(port[i_port])[0]:
        for face in (j, j + 1):
            open_r[i_port, face] = min(1.0, port_area / (2 * math.pi * face * h * h))
    open_r[:, -1] = 0.0  # the chamber's outer wall
    inlet = (X < x0 + 2 * h) & (Rr < rb)
    probe = np.zeros_like(inlet)
    g = Grid(h, x0, solid, open_x, open_r, np.zeros_like(solid), chamber, inlet, probe,
             {"h": h, "x0": x0, "nx": nx, "nr": nr, "port_area": port_area, "chamber_len": chamber_len,
              "r_chamber": r_c})
    return g, chamber


def port_discharge(gun, loads, window: float = 1.2e-3) -> dict | None:
    """Discharge coefficient of the gas port, from a 2D fill of the gas chamber.

    loads: the shot's GunLoads (the bore gas at the port over time).
    Returns {"cd", "mass_2d", "time", "pressure"} or None if the port is never uncovered.
    """
    from .action import AIR_TEMPERATURE, AMBIENT, _orifice
    p_port, t_port = loads.port_pressure, loads.port_temperature
    u_port = loads.port_velocity if loads.port_velocity is not None else np.zeros_like(p_port)
    opened = np.nonzero(p_port > 1.5 * AMBIENT)[0]
    if not opened.size:
        return None
    key = json.dumps([asdict(gun.action), gun.barrel.bore_diameter, gun.solver.device_resolution,
                      float(np.sum(p_port)), float(np.sum(t_port)), len(p_port)])
    with _port_lock:
        if key in _port_cache:
            return _port_cache[key]
        t_open = float(loads.t[opened[0]])
        t_end = min(t_open + window, float(loads.t[-1]))
        g, chamber = port_grid(gun)
        prop = gun.propellant
        s = Axisymmetric(g.h, g.x0, g.solid, g.open_x, g.open_r, prop.gas_constant, prop.gamma,
                         AMBIENT, AIR_TEMPERATURE, wall_heat=False, cfl=0.7)
        cv = prop.gas_constant / (prop.gamma - 1)
        vol = float(np.sum(chamber * s.volume))
        m0 = s.mass_in(chamber)
        times, masses, pressures = [t_open], [0.0], [AMBIENT]
        t = t_open
        dt_drive = 2e-6
        while t < t_end:
            p_in = float(np.interp(t, loads.t, p_port))
            T_in = float(np.interp(t, loads.t, t_port))
            u_in = float(np.interp(t, loads.t, u_port))
            s.set_fixed(g.inlet, p_in / (prop.gas_constant * T_in), u_in, cv * T_in)
            s.advance(dt_drive)
            t += dt_drive
            times.append(t)
            masses.append(s.mass_in(chamber) - m0)
            pressures.append(float(np.mean(s.pressure()[chamber])))
        times, masses = np.array(times), np.array(masses)

        # The orifice model's fill of the same chamber, for a given Cd (ideal gas, adiabatic).
        gamma, r_gas = prop.gamma, prop.gas_constant
        area = math.pi / 4 * gun.action.gas_port_diameter**2
        tt = np.linspace(t_open, t_end, 2000)
        pp, TT = np.interp(tt, loads.t, p_port), np.interp(tt, loads.t, t_port)

        def fill(cd):
            m = AMBIENT * vol / (r_gas * AIR_TEMPERATURE)
            E = m * cv * AIR_TEMPERATURE
            peak = 0.0
            for k in range(len(tt) - 1):
                dt = tt[k + 1] - tt[k]
                pc = (gamma - 1) * E / vol
                tc = pc * vol / (m * r_gas)
                if pp[k] > pc:
                    flow = cd / 0.8 * _orifice(area, pp[k], TT[k], pc, gamma, r_gas)
                    E += flow * dt * cv * gamma * TT[k]
                else:
                    flow = -cd / 0.8 * _orifice(area, pc, tc, pp[k], gamma, r_gas)
                    E += flow * dt * cv * gamma * tc
                m += flow * dt
                peak = max(peak, m - AMBIENT * vol / (r_gas * AIR_TEMPERATURE))
            return peak

        target = float(masses.max())
        lo, hi = 0.05, 1.5
        for _ in range(30):
            mid = 0.5 * (lo + hi)
            if fill(mid) < target:
                lo = mid
            else:
                hi = mid
        out = {"cd": 0.5 * (lo + hi), "mass_2d": target, "time": times, "pressure": np.array(pressures),
               "steps": s.steps, "cells": int(g.solid.size)}
        _port_cache.clear()
        _port_cache[key] = out
        return out


def with_device(loads, device: DeviceResult, shift: float, source=None, exit_time: float | None = None):
    """A copy of loads with a muzzle device's effects, for a model that solved no device itself.

    The device's solution comes from the fluid model, with its time moved by shift
    to line up on this model's muzzle exit. Without source, only the device's push
    on the gun is added. With source (the fluid model's loads) and exit_time (this
    model's), everything after exit is the fluid model's coupled blowdown: the
    device's back-pressure keeps the bore, and so the breech and the gas port,
    pressurised for longer, and this model's own after-effect knows nothing of it.
    """
    from .results import GunLoads
    t_dev = device.t + shift
    t = np.union1d(loads.t, t_dev)

    def on(a, fill):
        return np.interp(t, loads.t, a, left=fill, right=fill)

    breech, barrel = on(loads.breech_force, 0.0), on(loads.barrel_force, 0.0)
    port = [on(loads.port_pressure, loads.port_pressure[-1]), on(loads.port_temperature, loads.port_temperature[-1]),
            None if loads.port_velocity is None else on(loads.port_velocity, 0.0)]
    if source is None or exit_time is None:
        barrel -= np.interp(t, t_dev, device.force, left=0.0, right=0.0)
    else:
        after = t > exit_time
        tt = t[after] - shift
        take = lambda a: np.interp(tt, source.t, a, left=0.0, right=0.0)
        breech[after] = take(source.breech_force)
        barrel[after] = take(source.barrel_force)   # the fluid model's barrel force includes the device's push
        port[0][after] = np.interp(tt, source.t, source.port_pressure)
        port[1][after] = np.interp(tt, source.t, source.port_temperature)
        if port[2] is not None and source.port_velocity is not None:
            port[2][after] = np.interp(tt, source.t, source.port_velocity)
    return GunLoads(t=t, breech_force=breech, barrel_force=barrel, port_pressure=port[0], port_temperature=port[1],
                    head_area=loads.head_area, port_position=loads.port_position, port_velocity=port[2])


def to_json(device: DeviceResult) -> dict:
    """The device for the UI: summary, histories, and pressure snapshots on its grid."""
    g = device.grid
    stride = max(1, len(device.t) // 600)
    # Cell kinds for drawing: 0 gas, 1 barrel, 2 device, 3 vent (perforated).
    kind = np.zeros(g.solid.shape, np.int8)
    kind[g.solid] = 1
    kind[g.device] = 2
    vent = (g.open_r[:, :-1] < 1) & (g.open_r[:, :-1] > 0) & ~g.solid
    kind[vent] = 3
    return {
        "dims": {k: (float(v) if isinstance(v, (int, float, np.floating)) else v) for k, v in g.dims.items()},
        "kind": kind.T.tolist(),
        "t": device.t[::stride].tolist(),
        "force": device.force[::stride].tolist(),
        "pressure": device.pressure[::stride].tolist(),
        "snapshots": [{"t": float(t), "p": np.round(p.T / 1e3, 1).tolist()} for t, p in device.snapshots],
        "impulse": device.impulse,
        "heat": device.heat,
        "momentum_ratio": device.momentum_ratio,
        "peak_pressure": float(device.pressure.max()),
        "window_end": device.window_end,
        "stored_mass": device.stored_mass,
        "steps": device.steps,
    }
