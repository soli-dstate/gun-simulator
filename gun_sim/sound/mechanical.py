"""Mechanical sounds of the action, from the action simulation (gun_sim.action).

Each impact the action model reports becomes a burst of ringing steel (or
brass) at the place it happens:

* the hammer or striker falling, just before ignition, and before a
  revolver's hammer falls, its cylinder turning onto the cylinder stop;
* the bolt unlocking (the cam turning it), hitting the rear stop, and slamming
  back into battery, at the receiver;
* the spent case landing on the ground beside the shooter, after its fall;
* on a mount: the gun striking its recoil stop and running out into battery;
  a sliding wedge's crank picked up by the opening cam and its block striking
  the extractors;
* a chain gun's drive (motor()): the electric motor's whine and its gears,
  the chain's links clattering onto the sprocket and the brushes' hiss, at the
  speed and load the action simulation has the chain running at, so the whine
  sags as the bolt loads the motor and surges as it lets go;
* a tank gun's autoloader (autoloader()): its drives over each move of its
  cycle (servos, a geared motor and chains, or a hydraulic pump and valves),
  its clutches, latches and stops, the rounds seating and the block shutting.

A bigger part rings lower and longer: a steel part of more than a kilogram
has its modes divided by (mass / 1 kg)^(1/3), as its size, and its decay
times multiplied by it.

A ringing part is a few damped modes plus a short click of noise. How loud it
is comes from the energy of the impact: a fraction RADIATION_EFFICIENCY of the
kinetic energy lost in it is radiated as sound over the ring-down, spread over
a sphere. That fraction is an assumption (small parts struck hard radiate
something like 1e-5 to 1e-3 of the impact energy); everything else (which
impacts, when, how hard) comes from the simulation.
"""

from __future__ import annotations

import math

import numpy as np

RADIATION_EFFICIENCY = 1e-4
RHO_C = 413.0  # Pa s/m, air
# Modes of the parts that ring: (frequency Hz, decay time s, relative amplitude).
STEEL = [(1850, 0.020, 1.0), (3300, 0.014, 0.8), (5200, 0.010, 0.6), (7900, 0.006, 0.45), (11300, 0.004, 0.3)]
BRASS = [(4100, 0.030, 1.0), (6900, 0.022, 0.7), (9800, 0.016, 0.5), (13600, 0.010, 0.35)]
CASE_MASS = 0.012  # kg, a rifle case
LOCK_TIME = 0.003  # s, hammer fall to ignition
SMALL_PART = 1.0   # kg: parts up to this ring with the modes above as they are
CASE_FALL = 1.45   # m from the port to the ground
STUB_FALL = 0.6    # m from a cannon's breech into its deflector bag
ELECTRIC = ("chain", "sliding_wedge")   # fired by an electric primer: no hammer or striker


def steel(mass: float):
    """The modes of a steel part of `mass` kg: lower and longer-ringing as it gets bigger."""
    k = max(mass / SMALL_PART, 1.0) ** (1 / 3)
    return [(f / k, tau * k, amp) for f, tau, amp in STEEL]


def ring(fs: float, energy: float, modes, seed: int, click: float = 0.3) -> np.ndarray:
    """Pressure (Pa) at 1 m of a part struck with `energy` joules, as a ringing burst."""
    rng = np.random.default_rng(seed)
    duration = max(m[1] for m in modes) * 5
    t = np.arange(int(duration * fs)) / fs
    wave = np.zeros_like(t)
    for f, tau, amp in modes:
        f = f * (1 + 0.03 * rng.standard_normal())
        wave += amp * np.sin(2 * np.pi * f * t + rng.uniform(0, 2 * np.pi)) * np.exp(-t / tau)
    noise = rng.standard_normal(t.size) * np.exp(-t / 0.0004)
    wave += click * noise
    wave *= np.minimum(1.0, t / 1e-4)  # 0.1 ms attack
    # Radiated energy = efficiency * impact energy, spread over a sphere at 1 m:
    # intensity integral = sum p^2 dt / (rho c) = E_ac / (4 pi).
    e_acoustic = RADIATION_EFFICIENCY * max(energy, 0.0)
    target = math.sqrt(e_acoustic / (4 * math.pi) * RHO_C)
    norm = math.sqrt(np.sum(wave**2) / fs) or 1.0
    return wave * (target / norm)


MOTOR_SLOTS = 12            # armature slots: the magnetic whine, and the commutator's
DRIVE_RADIATION = 1e-5      # share of the drive's power radiated as sound (assumed, like RADIATION_EFFICIENCY)
NO_LOAD_LOSS = 0.1          # share of the rated power the drive spends on itself at free speed
# How the drive's sound splits between the motor's whine, the gears, the chain's links and the brushes.
DRIVE_SHARES = {"whine": 0.2, "mesh": 0.25, "chain": 0.45, "brushes": 0.1}


def motor(fs: float, t: np.ndarray, q: np.ndarray, gun, track: dict, seed: int = 31) -> np.ndarray:
    """Pressure (Pa) at 1 m of a chain gun's drive over the action simulation's clock t (s, from 0).

    q is the chain's travel (m) from the action simulation; its speed sets the motor's
    speed (the pitch of the whine and the rate the links clatter onto the sprocket), and
    the motor's load (its force law, as action.py has it) how loud it is. The gearing:
    the motor turns at action.motor_rpm when the chain runs free, its pinion has
    action.pinion_teeth, and a link of action.drive_chain_pitch lands on the sprocket
    for each pitch the chain moves.
    """
    a = gun.action
    v_free = track["perimeter"] * a.chain_rate / 60
    f_stall = 4 * a.motor_power / v_free
    n = int(math.ceil((t[-1] - t[0]) * fs)) + 1
    tt = t[0] + np.arange(n) / fs
    qq = np.interp(tt, t, q)
    v = np.maximum(np.gradient(qq, 1 / fs), 0.0)
    # Smooth over a millisecond: the solver's steps would otherwise click.
    k = max(1, int(1e-3 * fs))
    v = np.convolve(v, np.ones(k) / k, mode="same")
    power = f_stall * np.maximum(1 - v / v_free, 0.0) * v + NO_LOAD_LOSS * a.motor_power * v / v_free
    p_rms = np.sqrt(RHO_C * DRIVE_RADIATION * power / (4 * math.pi))

    # Motor turns per s: the sprocket's, geared up so that free speed is motor_rpm.
    ratio = a.motor_rpm / 60 / (v_free / (2 * math.pi * track["radius"]))
    f_motor = v / (2 * math.pi * track["radius"]) * ratio
    phase = 2 * math.pi * np.cumsum(f_motor) / fs
    rng = np.random.default_rng(seed)
    nyq = 0.45 * fs

    def tones(base: float, harmonics) -> np.ndarray:
        out = np.zeros(n)
        for h, amp in harmonics:
            if base * h * f_motor.max() < nyq:
                out += amp * np.sin(base * h * phase + rng.uniform(0, 2 * math.pi))
        return out

    parts = {
        "whine": tones(MOTOR_SLOTS, [(1, 1.0), (2, 0.4), (3, 0.15)]) + tones(1, [(1, 0.3), (2, 0.2)]),
        "mesh": tones(round(a.pinion_teeth), [(1, 1.0), (2, 0.5), (3, 0.25)]),
    }
    # Each link landing on the sprocket: a tick that rings the steel, harder the faster the chain.
    links = np.cumsum(v) / fs / a.drive_chain_pitch
    ticks = np.zeros(n)
    at = np.nonzero(np.diff(np.floor(links)) > 0)[0] + 1
    ticks[at] = v[at] / v_free
    ring_t = np.arange(int(4e-3 * fs)) / fs
    kernel = sum(amp * np.sin(2 * math.pi * f * ring_t) * np.exp(-ring_t / (tau * 0.15))
                 for f, tau, amp in STEEL if f < nyq)
    parts["chain"] = np.convolve(ticks, kernel)[:n]
    # Brushes: hiss in the upper midrange.
    hiss = rng.standard_normal(n)
    spec = np.fft.rfft(hiss)
    f = np.fft.rfftfreq(n, 1 / fs)
    spec *= np.exp(-0.5 * (np.log(np.maximum(f, 1.0) / 4000.0) / 0.5) ** 2)
    parts["brushes"] = np.fft.irfft(spec, n)

    running = v > 0.05 * v_free
    wave = np.zeros(n)
    for name, x in parts.items():
        rms = math.sqrt(np.mean(x[running] ** 2)) if running.any() else 0.0
        if rms > 0:
            wave += x / rms * math.sqrt(DRIVE_SHARES[name])
    # Ease in and out over a few ms, so it doesn't click where its clock starts and stops.
    edge = np.minimum(1.0, np.minimum(np.arange(n), np.arange(n)[::-1]) / (3e-3 * fs))
    return wave * p_rms * edge


SERVO_RPM = 3000.0          # an electric autoloader's servo motors at their top speed
SERVO_PWM = 8000.0          # Hz, their drives' switching whine
GEAR_MOTOR_RPM = 4500.0     # an electromechanical one's motor, at the mechanism's top speed
GEAR_TEETH = 17             # its first pinion
RAMMER_CHAIN_PITCH = 25.4e-3  # m, a chain rammer's links
PUMP_RPM = 1500.0           # a hydraulic autoloader's pump, running all through the cycle
PUMP_PISTONS = 9
PUMP_IDLE = 0.15            # share of the drives' power the pump makes noise with when nothing moves
ENGINE_SHARES = {"whine": 0.35, "mesh": 0.3, "chain": 0.25, "hiss": 0.1}


def _band_noise(n: int, fs: float, centre: float, width: float, rng) -> np.ndarray:
    """Noise in a log-normal band round `centre` Hz, unit rms."""
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1 / fs)
    spec *= np.exp(-0.5 * (np.log(np.maximum(f, 1.0) / centre) / width) ** 2)
    x = np.fft.irfft(spec, n)
    rms = math.sqrt(np.mean(x * x)) or 1.0
    return x / rms


def _drive_wave(fs: float, d: dict, rng) -> np.ndarray:
    """Pressure (Pa) at 1 m of one powered move of an autoloader: its motor (or valve) over the move."""
    n = int(math.ceil(d["t"][-1] * fs)) + 1
    tt = np.arange(n) / fs
    v = np.interp(tt, d["t"], d["v"])
    share = np.clip(v / d["v_cap"], 0.0, 1.0)
    acc = np.gradient(v, 1 / fs)
    power = np.abs((d["resist"] + d["mass"] * acc) * v) + NO_LOAD_LOSS * d["power"] * share
    p_rms = np.sqrt(RHO_C * DRIVE_RADIATION * power / (4 * math.pi))
    nyq = 0.45 * fs
    parts = {}
    if d["drive"] in ("electric", "electromechanical"):
        rpm = SERVO_RPM if d["drive"] == "electric" else GEAR_MOTOR_RPM
        phase = 2 * math.pi * np.cumsum(rpm / 60 * share) / fs
        whine = np.zeros(n)
        for h, amp in ((MOTOR_SLOTS, 1.0), (2 * MOTOR_SLOTS, 0.35), (1, 0.25), (2, 0.15)):
            if rpm / 60 * h < nyq:
                whine += amp * np.sin(h * phase + rng.uniform(0, 2 * math.pi))
        parts["whine"] = whine
        if d["drive"] == "electric":
            pwm = np.sin(2 * math.pi * min(SERVO_PWM, nyq) * tt) * (share > 0.01)
            parts["hiss"] = 0.6 * pwm + 0.4 * _band_noise(n, fs, 5000.0, 0.5, rng)
        else:
            parts["mesh"] = np.sin(GEAR_TEETH * phase) + 0.5 * np.sin(2 * GEAR_TEETH * phase)
            parts["hiss"] = _band_noise(n, fs, 3000.0, 0.6, rng)
        if d["part"] == "rammer" or d["drive"] == "electromechanical":
            # A chain rammer's (or the gearing's chain's) links ticking over the sprocket.
            links = np.cumsum(v) / fs / RAMMER_CHAIN_PITCH
            ticks = np.zeros(n)
            at = np.nonzero(np.diff(np.floor(links)) > 0)[0] + 1
            ticks[at] = share[at]
            ring_t = np.arange(int(4e-3 * fs)) / fs
            kernel = sum(amp * np.sin(2 * math.pi * f * ring_t) * np.exp(-ring_t / (tau * 0.15))
                         for f, tau, amp in STEEL if f < nyq)
            parts["chain"] = np.convolve(ticks, kernel)[:n]
    else:
        # A valve opening the move's flow: the oil's hiss through it, louder the faster it moves.
        parts["hiss"] = _band_noise(n, fs, 2500.0, 0.7, rng)
    moving = share > 0.05
    wave = np.zeros(n)
    for name, x in parts.items():
        rms = math.sqrt(np.mean(x[moving] ** 2)) if moving.any() else 0.0
        if rms > 0:
            wave += x / rms * math.sqrt(ENGINE_SHARES[name])
    edge = np.minimum(1.0, np.minimum(np.arange(n), np.arange(n)[::-1]) / (3e-3 * fs))
    return wave * p_rms * edge


def autoloader(fs: float, al: dict, seed: int = 47) -> tuple[float, np.ndarray] | None:
    """Pressure (Pa) at 1 m of an autoloader's cycle (gun_sim/autoloader.py): (start, s from ignition, and the wave).

    Its drives as they move (an electric one's servos whining up and down with each move and their
    switching hiss; an electromechanical one's motor, gears and chains; a hydraulic one's pump running
    all through the cycle and its valves hissing as each move flows), and every clutch, valve, latch and
    stop, the round seating in the forcing cone and the block springing shut, as the cycle has them.
    """
    if al is None or not al.get("stages"):
        return None
    rng = np.random.default_rng(seed)
    drives = al.get("drives", [])
    times = [st["start"] for st in al["stages"]] + [e["time"] for e in al["events"]]
    t0 = max(min(times) - 0.05, 0.0)
    t1 = al["end"] + 0.5
    n = int(math.ceil((t1 - t0) * fs))
    wave = np.zeros(n)

    def add(at: float, x: np.ndarray) -> None:
        i = int(round((at - t0) * fs))
        lo, hi = max(i, 0), min(i + len(x), n)
        if hi > lo:
            wave[lo:hi] += x[lo - i: hi - i]

    for d in drives:
        add(d["t0"], _drive_wave(fs, d, rng))
    hyd = [d for d in drives if d["drive"] == "hydraulic"]
    if hyd:
        # The pump runs from the first move to the last, labouring while any move flows.
        a, b = min(d["t0"] for d in hyd), max(d["t0"] + d["t"][-1] for d in hyd)
        m = int(math.ceil((b - a) * fs))
        tt = np.arange(m) / fs
        load = np.full(m, PUMP_IDLE)
        for d in hyd:
            load = np.maximum(load, np.interp(tt, d["t0"] - a + d["t"], d["v"] / d["v_cap"], left=0.0, right=0.0))
        rpm = PUMP_RPM * (1 - 0.06 * load)        # it sags a little under load
        phase = 2 * math.pi * np.cumsum(rpm / 60) / fs
        x = sum(amp * np.sin(PUMP_PISTONS * h * phase + rng.uniform(0, 2 * math.pi))
                for h, amp in ((1, 1.0), (2, 0.5), (3, 0.3), (4, 0.15)))
        x = x / math.sqrt(np.mean(x * x)) + 0.3 * _band_noise(m, fs, 1500.0, 0.6, rng)
        power = max(d["power"] for d in hyd) * load
        edge = np.minimum(1.0, np.minimum(np.arange(m), np.arange(m)[::-1]) / (0.08 * fs))
        add(a, x * np.sqrt(RHO_C * DRIVE_RADIATION * power / (4 * math.pi)) * edge)
    for k, e in enumerate(al["events"]):
        if e["energy"] > 0:
            add(e["time"], ring(fs, e["energy"], steel(max(e["mass"], 0.05)), seed=seed + k))
    return t0, wave


def impacts(action_result, gun) -> list[dict]:
    """The sounds of one shot's cycle: {time (s from ignition), name, energy (J), where, modes}."""
    from .. import revolver
    from ..feed import case_mass, chambers
    a = action_result
    bolt = gun.action.bolt_mass
    recoiling = getattr(a, "gun_mass", 0.0) or gun.action.gun_mass
    out = []
    if getattr(a, "striker_energy", None) is not None:
        out.append({"time": -a.lock_time, "name": "striker falls", "where": "receiver",
                    "energy": a.striker_energy, "modes": STEEL})
    elif gun.action.type not in ELECTRIC:
        # The hammer as the action simulation has it, or a typical one (30 g at 4 m/s, 3 ms before ignition).
        simulated = getattr(a, "hammer_energy", None) is not None
        out.append({"time": -a.lock_time if simulated else -LOCK_TIME, "name": "hammer falls", "where": "receiver",
                    "energy": a.hammer_energy if simulated else 0.5 * 0.03 * 4.0**2, "modes": STEEL})
    if gun.action.type == "revolver":
        # The cylinder turned onto its stop as the hammer came back, before it fell: as fast as the hand turned it.
        t = gun.trigger
        span = revolver.INDEX_END - revolver.INDEX_START
        speed = 2 * math.pi / chambers(gun) / (span * t.pull_time)
        energy = a.cylinder_lock_energy if getattr(a, "cylinder_lock_energy", None) is not None else \
            0.5 * revolver.cylinder_inertia(gun, chambers(gun)) * speed**2
        out.append({"time": -a.lock_time - (1 - revolver.INDEX_END) * t.pull_time, "name": "cylinder locks",
                    "where": "receiver", "energy": energy, "modes": steel(gun.action.cylinder_mass)})
    spent = case_mass(gun)
    for e in a.events:
        if e.get("shot", 1) != 1:
            continue
        speed = abs(e["speed"]) if e.get("speed") is not None else None
        if e["name"] == "bolt hits the rear stop" and speed:
            out.append({"time": e["time"], "name": "bolt hits the rear stop", "where": "receiver",
                        "energy": 0.5 * bolt * speed**2 * (1 - gun.action.rear_restitution**2), "modes": steel(bolt)})
        elif e["name"] in ("back in battery", "closes on an empty chamber") and speed:
            out.append({"time": e["time"], "name": "bolt slams home", "where": "receiver",
                        "energy": 0.5 * bolt * speed**2, "modes": steel(bolt)})
        elif e["name"] == "gun hits the recoil stop" and speed:
            out.append({"time": e["time"], "name": e["name"], "where": "receiver",
                        "energy": 0.5 * recoiling * speed**2 * (1 - gun.mount.stop_restitution**2),
                        "modes": steel(recoiling)})
        elif e["name"] == "gun runs out into battery" and speed:
            out.append({"time": e["time"], "name": e["name"], "where": "receiver",
                        "energy": 0.5 * recoiling * speed**2, "modes": steel(recoiling)})
        elif e["name"] == "the opening cam turns the crank" and speed:
            # The block picked up at the cam's ratio of the gun's speed.
            gear = a.strokes["stroke"] / gun.action.cam_travel
            out.append({"time": e["time"], "name": "the cam picks up the crank", "where": "receiver",
                        "energy": 0.5 * bolt * (gear * speed) ** 2, "modes": steel(bolt)})
        elif e["name"] == "block strikes the extractors" and speed:
            out.append({"time": e["time"], "name": e["name"], "where": "receiver",
                        "energy": 0.5 * bolt * speed**2, "modes": steel(bolt)})
        elif e["name"] == "hammer cocked":
            # The sear snapping over the hammer's notch: a small click.
            out.append({"time": e["time"], "name": "hammer cocked", "where": "receiver",
                        "energy": 0.002, "modes": STEEL})
        elif e["name"] in ("bolt unlocks", "barrel stops and unlocks"):
            out.append({"time": e["time"], "name": "bolt unlocks", "where": "receiver",
                        "energy": 0.02 * 0.5 * bolt * 25.0, "modes": STEEL})
        elif e["name"] == "case ejected" and speed:
            # It falls from the port to the ground and lands about 1.5 m to the right (a cannon's stub
            # drops behind the breech into the deflector bag).
            height = STUB_FALL if gun.action.type == "sliding_wedge" else CASE_FALL
            fall = math.sqrt(2 * height / 9.81)
            mass = spent if gun.case.combustible or gun.action.type in ELECTRIC else CASE_MASS
            out.append({"time": e["time"] + fall, "name": "case lands", "where": "ground",
                        "energy": 0.5 * mass * (9.81 * fall) ** 2,
                        "modes": BRASS if gun.case.material == "brass" else steel(mass)})
    return out
