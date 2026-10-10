"""Synthesise what a shot sounds like, from the fluid simulation.

    bore blowdown (fluid.py) --+--> spherical blast solver (blast.py) --> probes
    precursor (ballistic.py) --+                                           |
    secondary flash (plume.py) +                                           |
    bore blowdown (fluid.py) ----> the jet's roar (jet.py) ----------------|
    revolver's cylinder gap -----> spherical blast solver --> probes       |
                                    directivity, weak shocks, absorption,  |
    supersonic crack (ballistic.py) --> ground reflection, head (propagation.py)
                                                                           v
                                                       left / right ear, Pa

A revolver's cylinder gap blows its own blast out sideways, from beside the
shooter's hands, a little before the muzzle's: the gas that escapes it
(fluid.py's gap_flow) feeds a second spherical solution, heard without the
muzzle jet's forward throw.

The blast alone is a sharp crack. What gives a shot its weight comes after it:
the fuel-rich propellant gas burning in the air (a heat release of the same
order as the gas's own energy, which the blast solver turns into a deeper
boom) and the turbulent roar of the jet while the bore empties.

Nothing here is a recording or a sample: every sound comes from the gun's
configuration and the air it is fired in.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field, replace

import numpy as np

from .. import action, fluid, plume
from ..config import Gun
from ..results import ShotResult
from . import ballistic, jet, mechanical, propagation
from .blast import BlastResult, BlastSource, simulate_blast
from .settings import GROUNDS, SoundSettings

P_REF = 20e-6  # Pa, 0 dB SPL
OVERSAMPLE = 4
RING_FRACTION = 0.2  # of (peak device pressure x volume); mechanical.ring then radiates 1e-4 of that. Tuned: ~30 dB under the suppressed blast at the shooter


def spl(p: float) -> float:
    return 20 * math.log10(max(abs(p), P_REF) / P_REF)


@dataclass
class Sound:
    sample_rate: int
    start_time: float          # s after ignition of sample 0
    left: np.ndarray           # Pa at the left eardrum (well, at the ear entrance)
    right: np.ndarray
    pressure: np.ndarray       # Pa free field at the listener's head position (no head)
    reference: np.ndarray      # Pa, the blast at 1 m (omnidirectional), aligned with the direct blast; feeds room reverb
    # The same, as thrown towards the front (along the bore), the side and the rear: feeds echoes off surfaces there.
    references: dict = field(default_factory=dict)
    crack_source: dict | None = None  # the Mach cone along the trajectory, for echoes of the crack (see _crack_source)
    events: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    near_field: dict = field(default_factory=dict)
    stems: list = field(default_factory=list)  # per-sound-event tracks, see _stems()


@dataclass
class _Physics:
    shot: ShotResult
    blast: BlastResult
    t: np.ndarray          # uniform time base at the internal rate, s
    probes: np.ndarray     # (n_probes, len(t)), shock-fitted, Pa gauge
    ejected_energy: float
    directivity: float = 1.0   # share of the jet's forward momentum that survives a muzzle device
    source_x: float = 0.0      # m, where the blast comes from, ahead of the muzzle
    gap_probes: np.ndarray | None = None   # a revolver's cylinder gap blast, on the same time base and radii
    gap_x: float = 0.0         # m, where the gap is (behind the muzzle: negative)
    afterburn: float = 0.0     # J, heat of the secondary flash fed to the blast


_cache: dict = {}


def _afterburn(gun: Gun, shot: ShotResult, s: SoundSettings) -> dict:
    """The secondary flash's heat over time (cumulative J, s from ignition) and the fireball's radius.

    From the 2D plume (gun_sim.plume), solved for about as long as the bore takes to
    let most of its gas out, which is when the burning dies down.
    """
    mf = shot.muzzle_flow
    after = mf.t >= mf.exit_time
    t, mdot = mf.t[after], np.maximum(mf.mdot[after], 0.0)
    out = np.cumsum(mdot * np.diff(t, prepend=t[0]))
    t90 = float(np.interp(0.9 * out[-1], out, t)) - mf.exit_time if out[-1] > 0 else 0.0
    window = float(np.clip(t90, 2e-3, 1e-2))
    g = replace(gun, solver=replace(gun.solver, plume_time=window))
    r = plume.simulate(g, shot, s.pressure, s.temperature_k)
    heat = np.maximum.accumulate(r.burnt)
    if heat[-1] <= 0:
        return {"t": None, "heat": np.zeros(1), "radius": 0.0}
    # The fireball's size: a sphere of the hot region's volume when half the heat is out.
    k = int(np.argmax(heat >= 0.5 * heat[-1]))
    x0, x1, rad = r.extent[k]
    radius = (3 / 4 * rad * rad * max(x1 - x0, rad)) ** (1 / 3)
    return {"t": mf.exit_time + r.times, "heat": heat, "radius": float(radius)}


def _physics(gun: Gun, s: SoundSettings) -> _Physics:
    """Bore blowdown + muzzle blast. Independent of where the listener stands, so cached."""
    key = json.dumps([asdict(gun), s.pressure, s.temperature, s.blast_time, s.blast_cells,
                      s.blast_radius, s.sample_rate], sort_keys=True)
    if key in _cache:
        return _cache[key]

    shot = fluid.simulate_cached(gun, blowdown_time=s.blast_time, ambient_pressure=s.pressure)
    if not shot.left_muzzle:
        raise ValueError("no sound to make: the projectile did not leave the muzzle")
    mf = shot.muzzle_flow
    bar = gun.barrel

    # Air pushed out ahead of the projectile, then the propellant gas.
    pre = ballistic.precursor_flow(shot.time, shot.travel, shot.velocity, bar.travel, bar.bore_area,
                                   s.pressure, s.temperature_k)
    if pre is not None:
        t_pre, m_pre, e_pre = (a[pre[0] < mf.exit_time] for a in pre)
    else:
        t_pre = m_pre = e_pre = np.zeros(0)
    m0 = m_pre[-1] if m_pre.size else 0.0
    e0 = e_pre[-1] if e_pre.size else 0.0
    dev = shot.device
    if dev is None:
        dt = np.diff(mf.t, prepend=mf.exit_time)
        t_gas, m_gas, e_gas = mf.t, np.cumsum(mf.mdot * dt), np.cumsum(mf.edot * dt)
        directivity, source_x, ejected = 1.0, 0.0, mf.ejected_energy
    else:
        # What leaves the muzzle device: its propellant gas, and the energy over the still air's.
        t_gas, m_gas, e_gas = dev.t, dev.out_propellant, np.maximum.accumulate(dev.out_energy)
        directivity = dev.momentum_ratio
        source_x = dev.dims["length"] * (0.5 if dev.dims["type"] == "brake" else 1.0)  # its vents, or its front
        ejected = float(e_gas[-1])
    fire = _afterburn(gun, shot, s)
    source = BlastSource(
        t=np.concatenate((t_pre, [mf.exit_time], t_gas)),
        mass=np.concatenate((m_pre, [m0], m0 + m_gas)),
        energy=np.concatenate((e_pre, [e0], e0 + e_gas)),
        propellant=np.concatenate((np.zeros(t_pre.size + 1), m_gas)),
        heat_t=fire["t"], heat=fire["heat"], heat_radius=fire["radius"],
    )

    dx = s.blast_radius / s.blast_cells
    radii = np.geomspace(0.1, 0.9 * s.blast_radius, 14)
    blast = simulate_blast(source, gun.propellant.gas_constant, gun.propellant.gamma, s.pressure,
                           s.temperature_k, s.blast_radius, s.blast_cells, mf.exit_time + s.blast_time,
                           max(bar.bore_diameter, 2.5 * dx), radii)

    fs = s.sample_rate * OVERSAMPLE
    gap = shot.gap_flow
    gap_blast = None
    if gap is not None and gap["mass"] > 0:
        dt_gap = np.diff(gap["t"], prepend=gap["t"][0])
        mass = np.cumsum(gap["mdot"] * dt_gap)
        gap_source = BlastSource(t=np.concatenate(([gap["t"][0] - 1e-6], gap["t"])),
                                 mass=np.concatenate(([0.0], mass)),
                                 energy=np.concatenate(([0.0], np.cumsum(gap["edot"] * dt_gap))),
                                 propellant=np.concatenate(([0.0], mass)))
        gap_blast = simulate_blast(gap_source, gun.propellant.gas_constant, gun.propellant.gamma, s.pressure,
                                   s.temperature_k, s.blast_radius, s.blast_cells, mf.exit_time + s.blast_time,
                                   max(2 * bar.bore_diameter, 2.5 * dx), radii)
    start = min(blast.time[0], gap_blast.time[0]) if gap_blast is not None else blast.time[0]
    t = np.arange(start, blast.time[-1], 1 / fs)
    fade = np.clip((t[-1] - t) / 3e-3, 0.0, 1.0)  # the record ends; fade rather than cut
    probes = np.array([propagation.shock_fit(t, np.interp(t, blast.time, p, left=0.0)) * fade for p in blast.pressure])
    gap_probes = None if gap_blast is None else np.array(
        [propagation.shock_fit(t, np.interp(t, gap_blast.time, p, left=0.0)) * fade for p in gap_blast.pressure])

    phys = _Physics(shot, blast, t, probes, ejected, directivity, source_x, gap_probes,
                    -(bar.travel - gap["position"]) if gap_probes is not None else 0.0, float(fire["heat"][-1]))
    while len(_cache) >= 2:
        _cache.pop(next(iter(_cache)))
    _cache[key] = phys
    return phys


def synthesize(gun: Gun, settings: SoundSettings | None = None) -> Sound:
    s = (settings or SoundSettings()).resolved(gun.barrel.travel)
    phys = _physics(gun, s)
    shot, blast, t_u, probes = phys.shot, phys.blast, phys.t, phys.probes
    mf = shot.muzzle_flow
    fs_int = s.sample_rate * OVERSAMPLE
    c0, rho0, p0 = s.sound_speed, s.air_density, s.pressure
    radii = blast.radii

    # The blast cloud's size and the time it takes to slow down: E = p0 R0^3.
    r0 = (phys.ejected_energy / p0) ** (1 / 3)
    t_relax = r0 / c0

    listener = np.array(s.listener_position())
    from_source = listener - np.array([phys.source_x, 0.0, 0.0])  # the blast leaves the device, not the muzzle
    convection = s.convection_mach * phys.directivity
    h_s = s.muzzle_height
    resistivity = GROUNDS[s.ground]

    # ---- the paths: direct, and mirrored in the ground ----
    paths = [("direct", from_source, None)]
    if resistivity is not None and h_s > 0 and s.listener_height > 0:
        image = from_source + np.array([0.0, 0.0, 2 * h_s])  # listener seen from the source's image
        r2 = float(np.linalg.norm(image))
        grazing = math.asin(min(image[2] / r2, 1.0))
        paths.append(("ground", image, grazing))

    def blast_at(r: float, cos_theta: float, at_1m: bool = False):
        """(t_shift, waveform on t_u) of the muzzle blast travelling r metres at angle theta.

        at_1m: the waveform as thrown out at that angle, scaled back to 1 m (no weak-shock
        stretch), but timed to arrive with the blast at r.
        """
        k = int(np.searchsorted(radii, r, side="right")) - 1
        k = max(k, 0)
        rk = radii[k]
        p = probes[k]
        peak = p.max()
        ia = int(np.argmax(p >= 0.5 * peak))
        ta = t_u[ia]
        warped = propagation.directivity_warp(t_u, p, ta, cos_theta, convection, t_relax)
        if at_1m:
            return (r - rk) / c0, warped * rk
        wpk = warped.max()
        ipk = int(np.argmax(warped))
        zero = ipk + int(np.argmax(warped[ipk:] < 0))
        stretch = propagation.weak_shock_stretch(wpk, t_u[zero] - ta, rk, r, rho0, c0)
        local = np.where(t_u >= ta, ta + (t_u - ta) / stretch, t_u)
        return (r - rk) / c0, np.interp(local, t_u, warped) * (rk / r / stretch)

    # Each arrival: a waveform starting at time t0, the path length, the grazing
    # angle if it bounced off the ground, and the direction it travels in at the listener.
    arrivals = []
    for name, vec, grazing in paths:
        r = float(np.linalg.norm(vec))
        # The ground ray leaves the muzzle downwards at the same angle to the bore
        # as the image ray, and arrives travelling up, i.e. along the image vector.
        shift, wave = blast_at(r, vec[0] / r)
        arrivals.append(dict(name=f"muzzle blast ({name})", t0=t_u[0] + shift, wave=wave, r=r,
                             grazing=grazing, direction=vec / r))

    # ---- the jet's roar while the bore empties ----
    roar = jet.roar(mf, gun, shot.device, fs_int, p0, c0, rho0)
    if roar is not None:
        t_jet, jet_wave, jet_hz = roar
        for name, vec, grazing in paths:
            r = float(np.linalg.norm(vec))
            arrivals.append(dict(name=f"muzzle jet ({name})", t0=t_jet + r / c0,
                                 wave=jet_wave * math.sqrt(jet.directivity(vec[0] / r)) / r, r=r,
                                 grazing=grazing, direction=vec / r))

    # ---- a revolver's cylinder gap: a blast of its own, out sideways all round, without the jet's throw ----
    if phys.gap_probes is not None:
        def gap_at_range(r: float):
            k = max(int(np.searchsorted(radii, r, side="right")) - 1, 0)
            rk, p = radii[k], phys.gap_probes[k]
            ia = int(np.argmax(p >= 0.5 * p.max()))
            ipk = int(np.argmax(p))
            zero = ipk + int(np.argmax(p[ipk:] < 0))
            stretch = propagation.weak_shock_stretch(p.max(), t_u[zero] - t_u[ia], rk, r, rho0, c0)
            local = np.where(t_u >= t_u[ia], t_u[ia] + (t_u - t_u[ia]) / stretch, t_u)
            return (r - rk) / c0, np.interp(local, t_u, p) * (rk / r / stretch)

        from_gap = listener - np.array([phys.gap_x, 0.0, 0.0])
        gap_paths = [("direct", from_gap, None)]
        if len(paths) > 1:
            image = from_gap + np.array([0.0, 0.0, 2 * h_s])
            gap_paths.append(("ground", image, math.asin(min(image[2] / float(np.linalg.norm(image)), 1.0))))
        for name, vec, grazing in gap_paths:
            r = max(float(np.linalg.norm(vec)), 0.05)
            shift, wave = gap_at_range(r)
            arrivals.append(dict(name=f"cylinder gap blast ({name})", t0=t_u[0] + shift, wave=wave, r=r,
                                 grazing=grazing, direction=vec / r))

    # ---- the supersonic crack ----
    proj = gun.projectile
    crack_info = None
    lateral = math.hypot(listener[1], listener[2])
    x_max = max(listener[0], 0.0) + 3 * lateral + 20
    if shot.muzzle_velocity > c0 and listener[0] > 0:
        traj = ballistic.fly(shot.muzzle_velocity, gun.flight_mass, gun.flight_diameter, rho0, c0, x_max)
        for name, _, _ in paths:
            # Ground path: the projectile flies at z = 0, so mirror the listener below the ground.
            target = listener if name == "direct" else np.array([listener[0], listener[1], -2 * h_s - listener[2]])
            cr = ballistic.crack(traj, target, c0, p0, gun.flight_diameter, proj.length)
            if cr is None:
                continue
            # The mirrored ray really arrives travelling upwards.
            direction = cr.direction if name == "direct" else cr.direction * np.array([1, 1, -1])
            n = int(math.ceil((cr.duration + 1e-3) * fs_int))
            tt = np.arange(n) / fs_int - 2e-4
            path = cr.miss_distance / math.sqrt(1 - 1 / cr.mach**2)  # emission point to listener
            arrivals.append(dict(name=f"supersonic crack ({name})", t0=mf.exit_time + cr.time - 2e-4,
                                 wave=ballistic.n_wave(tt, 0.0, cr.overpressure, cr.duration), r=path,
                                 grazing=math.asin(min(abs(cr.direction[2]), 1.0)) if name != "direct" else None,
                                 direction=direction))
            if name == "direct":
                crack_info = cr

    # ---- a suppressor rings like a struck tube, from the gas impulse ----
    dev = shot.device
    if dev is not None and dev.dims["type"] == "suppressor":
        length, radius = dev.dims["length"], dev.dims["outer_radius"]
        at = np.array([length / 2, 0.0, 0.0])
        vec = listener - at
        r = max(float(np.linalg.norm(vec)), 0.05)
        energy = RING_FRACTION * float(dev.pressure.max()) * math.pi * radius**2 * length
        wave = mechanical.ring(fs_int, energy, _tube_modes(length, radius), seed=99) / r
        arrivals.append(dict(name="suppressor ring", t0=mf.exit_time + r / c0, wave=wave, r=r,
                             grazing=None, direction=vec / r))

    # ---- the action: hammer, bolt and the case landing ----
    if s.action_sounds:
        cycle = action.simulate(gun, shot)
        receiver = np.array([-(gun.barrel.travel + gun.case.length + 0.05), 0.0, 0.0])
        ground = np.array([receiver[0], -1.5, -h_s])  # cases land about 1.5 m to the right
        for k, imp in enumerate(mechanical.impacts(cycle, gun)):
            at = receiver if imp["where"] == "receiver" else ground
            vec = listener - at
            r = max(float(np.linalg.norm(vec)), 0.05)
            wave = mechanical.ring(fs_int, imp["energy"], imp["modes"], seed=k) / r
            arrivals.append(dict(name=f"action: {imp['name']}", t0=imp["time"] + r / c0, wave=wave, r=r,
                                 grazing=None, direction=vec / r))
        if cycle.drive is not None:
            # A chain gun's motor, gears and chain, over the shot's cycle (a burst repeats it shot by shot).
            vec = listener - receiver
            r = max(float(np.linalg.norm(vec)), 0.05)
            track = action.chain_track(gun, cycle.strokes["stroke"])
            wave = mechanical.motor(fs_int, cycle.time, cycle.drive, gun, track) / r
            arrivals.append(dict(name="action: chain drive", t0=float(cycle.time[0]) + r / c0, wave=wave, r=r,
                                 grazing=None, direction=vec / r))
        loader = mechanical.autoloader(fs_int, cycle.autoloader)
        if loader is not None:
            # A tank gun's autoloader, in the turret behind the breech, all through its cycle.
            vec = listener - (receiver - np.array([0.5, 0.0, 0.0]))
            r = max(float(np.linalg.norm(vec)), 0.05)
            arrivals.append(dict(name="action: autoloader", t0=loader[0] + r / c0, wave=loader[1] / r, r=r,
                                 grazing=None, direction=vec / r))

    # ---- render every arrival on one timeline, at the internal rate ----
    first = min(a["t0"] + _onset(a["wave"]) / fs_int for a in arrivals)
    start = max(0.0, first - 0.02)
    end = max(a["t0"] + len(a["wave"]) / fs_int for a in arrivals) + 0.02
    n_out = int(math.ceil((end - start) * fs_int))
    nfft = 1 << int(math.ceil(math.log2(n_out + 4096)))
    f = np.fft.rfftfreq(nfft, 1 / fs_int)
    alpha = propagation.absorption_db_per_m(f, s.temperature_k, s.humidity, s.pressure)

    mono = np.zeros(f.size, complex)
    left = np.zeros(f.size, complex)
    right = np.zeros(f.size, complex)
    events = []
    groups: dict = {}  # group name -> [left spectrum, right spectrum]
    for a in arrivals:
        offset = int(round((a["t0"] - start) * fs_int))
        x = np.zeros(nfft)
        wave = a["wave"]
        lo = max(0, -offset)
        hi = min(len(wave), n_out - offset)
        if hi <= lo:
            continue
        x[offset + lo: offset + hi] = wave[lo:hi]
        spec = np.fft.rfft(x)
        spec *= propagation.minimum_phase(10 ** (-alpha * a["r"] / 20), nfft)
        if a["grazing"] is not None:
            spec *= propagation.ground_reflection(f, resistivity, a["grazing"], rho0)
        hl, hr = propagation.head_responses(f, a["direction"], s.facing, c0)
        mono += spec
        left += spec * hl
        right += spec * hr
        g = groups.setdefault(_group(a["name"]), [np.zeros(f.size, complex), np.zeros(f.size, complex)])
        g[0] += spec * hl
        g[1] += spec * hr
        free = np.fft.irfft(spec, nfft)[:n_out]
        k = int(np.argmax(np.abs(free)))
        events.append(dict(name=a["name"], time=start + k / fs_int, peak=float(free[k]),
                           peak_db=spl(free[k]), path=a["r"]))

    def out(spec):
        return propagation.decimate(np.fft.irfft(spec, nfft)[:n_out], OVERSAMPLE)

    pressure, left_ear, right_ear = out(mono), out(left), out(right)

    # Room/echo feeds: the blast at 1 m as thrown forward, sideways (= omnidirectional) and
    # back, starting when the direct blast arrives.
    r_direct = float(np.linalg.norm(listener))
    references = {}
    for side, cos_theta in (("front", 1.0), ("side", 0.0), ("rear", -1.0)):
        shift, ref_wave = blast_at(r_direct, cos_theta, at_1m=True)
        ref = np.zeros(n_out)
        offset = int(round((t_u[0] + shift - start) * fs_int))
        lo, hi = max(0, -offset), min(len(ref_wave), n_out - offset)
        if hi > lo:
            ref[offset + lo: offset + hi] = ref_wave[lo:hi]
        if roar is not None:
            # The jet's roar reflects off the surroundings too.
            jw = jet_wave * math.sqrt(jet.directivity(cos_theta))
            offset = int(round((t_jet + r_direct / c0 - start) * fs_int))
            lo, hi = max(0, -offset), min(len(jw), n_out - offset)
            if hi > lo:
                ref[offset + lo: offset + hi] += jw[lo:hi]
        references[side] = propagation.decimate(ref, OVERSAMPLE)
    reference = references["side"]

    bare_peak = None
    if shot.device is not None:
        # The same shot without the device, to show how much it takes off (blast and crack only).
        bare_gun = replace(gun, muzzle_device=replace(gun.muzzle_device, type="none"))
        bare = synthesize(bare_gun, replace(s, action_sounds=False))
        bare_peak = float(max(np.max(np.abs(bare.left)), np.max(np.abs(bare.right))))

    stems = _stems(groups, out, references, s.sample_rate, start)

    k1 = int(np.argmin(np.abs(radii - 1.0)))
    peak_ff = float(np.max(np.abs(pressure)))
    stats = {
        "distance": r_direct,
        "angle": s.angle,
        "peak_pressure": peak_ff,
        "peak_db": spl(peak_ff),
        "peak_left_db": spl(float(np.max(np.abs(left_ear)))),
        "peak_right_db": spl(float(np.max(np.abs(right_ear)))),
        "first_arrival": first,
        "blast_1m_db": spl(float(probes[k1].max()) * radii[k1]),
        "muzzle_exit_pressure": mf.exit_pressure,
        "muzzle_gas_velocity": mf.exit_gas_velocity,
        "ejected_gas": mf.ejected_mass,
        "ejected_energy": phys.ejected_energy,
        "device": None if shot.device is None else {
            "type": shot.device.dims["type"], "heat": shot.device.heat,
            "momentum_ratio": shot.device.momentum_ratio, "peak_pressure": float(shot.device.pressure.max()),
        },
        "recoil_impulse": shot.recoil_impulse,
        "gap_gas": None if shot.gap_flow is None else shot.gap_flow["mass"],
        "muzzle_velocity": shot.muzzle_velocity,
        "muzzle_mach": shot.muzzle_velocity / c0,
        "sound_speed": c0,
        "crack": None if crack_info is None else {
            "mach": crack_info.mach, "miss_distance": crack_info.miss_distance,
            "duration": crack_info.duration, "overpressure": crack_info.overpressure,
        },
        "blast_steps": blast.steps,
        "afterburn": phys.afterburn,
        "jet_peak_frequency": None if roar is None else roar[2],
        "bare_peak": bare_peak,
        "listener": [float(v) for v in listener],
        "facing": s.facing,
    }

    # Near field for the chart: a few probes from just after exit.
    near = {"radii": [], "time": None, "pressure": []}
    window = (t_u >= mf.exit_time) & (t_u <= mf.exit_time + min(0.008, s.blast_time))
    for target in (0.25, 0.5, 1.0, 1.5):
        k = int(np.argmin(np.abs(radii - target)))
        if radii[k] not in near["radii"]:
            near["radii"].append(float(radii[k]))
            near["pressure"].append(probes[k][window])
    near["time"] = t_u[window]

    return Sound(sample_rate=s.sample_rate, start_time=start, left=left_ear, right=right_ear,
                 pressure=pressure, reference=reference, references=references,
                 crack_source=_crack_source(gun, shot, s),
                 events=sorted(events, key=lambda e: e["time"]), stats=stats, near_field=near, stems=stems)


CRACK_RANGE = 2500.0  # m of trajectory described for echoes of the crack


def _crack_source(gun: Gun, shot: ShotResult, s: SoundSettings) -> dict | None:
    """The supersonic part of the trajectory, for echoes of the crack off the surroundings.

    Per point: x (m downrange), t (s after muzzle exit), Mach, and Whitham's
    constants (see ballistic.py) so that the cone emitted there has, at miss
    distance b, overpressure kp / b^(3/4) and length kt * b^(1/4).
    """
    c0 = s.sound_speed
    if shot.muzzle_velocity <= c0:
        return None
    # An APFSDS's rod flies on alone once its sabot has gone.
    d, length = gun.flight_diameter, gun.projectile.length
    traj = ballistic.fly(shot.muzzle_velocity, gun.flight_mass, d, s.air_density, c0, CRACK_RANGE)
    mach = traj.v / c0
    n = int(np.argmax(mach <= 1.0)) if np.any(mach <= 1.0) else len(mach)
    if n < 2:
        return None
    idx = np.unique(np.linspace(0, n - 1, min(n, 400)).astype(int))
    m = mach[idx]
    m2 = m * m - 1
    return {
        "exit_time": shot.muzzle_flow.exit_time,
        "sound_speed": c0,
        "x": traj.x[idx].tolist(),
        "t": traj.t[idx].tolist(),
        "mach": m.tolist(),
        "kp": (0.53 * s.pressure * m2**0.125 * d / length**0.25).tolist(),
        "kt": (1.82 * m * d / (c0 * m2**0.375 * length**0.25)).tolist(),
    }


def _onset(wave: np.ndarray) -> int:
    """Index where a waveform first reaches 1 % of its peak."""
    a = np.abs(wave)
    return int(np.argmax(a >= 0.01 * a.max())) if a.max() > 0 else 0


def _tube_modes(length: float, radius: float):
    """Modes of a free thin steel tube: bending (beam theory) and the longitudinal half-wave."""
    c_steel = 5100.0
    f1 = 22.37 / (2 * math.pi) * c_steel * (radius / math.sqrt(2)) / length**2
    ratios = (1.0, 2.76, 5.40, 8.93)
    modes = [(f1 * k, 0.03 / (1 + 0.5 * i), 1.0 / (1 + 0.3 * i)) for i, k in enumerate(ratios)]
    modes.append((c_steel / (2 * length), 0.02, 0.5))
    return [m for m in modes if m[0] < 20000.0]


def _group(name: str) -> str:
    """The stem a sound belongs to: its paths together, and the jet's roar with the blast."""
    for suffix in (" (direct)", " (ground)"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return "muzzle blast" if name == "muzzle jet" else name


def _stems(groups: dict, out, references: dict, rate: int, start: float) -> list:
    """One trimmed left/right track per sound event (direct + ground paths summed).

    `time` is seconds after ignition of the stem's first sample. The blast stem also
    carries the reference feeds cut to the same window (`reference` is the side one).
    """
    stems = []
    for name, (sl, sr) in groups.items():
        left, right = out(sl), out(sr)
        env = np.maximum(np.abs(left), np.abs(right))
        peak = float(env.max()) if env.size else 0.0
        if peak <= 0:
            continue
        idx = np.nonzero(env > 1e-5 * peak)[0]
        i0 = max(0, int(idx[0]) - int(0.002 * rate))
        i1 = min(len(env), int(idx[-1]) + 1 + int(0.020 * rate))
        kind = ("blast" if name.startswith("muzzle blast") else "crack" if name.startswith("supersonic")
                else "device" if name == "suppressor ring" else "gap" if name.startswith("cylinder gap")
                else "action")
        refs = {k: v[i0:i1] for k, v in references.items()} if kind == "blast" else None
        stems.append(dict(name=name, kind=kind, time=start + i0 / rate, left=left[i0:i1], right=right[i0:i1],
                          peak=peak, reference=refs["side"] if refs else None, references=refs))
    return stems
