"""Backend calls behind the UI, shared by the desktop window and the browser fallback."""

from __future__ import annotations

import base64
import math
import sys
import tomllib
import traceback
from dataclasses import asdict
from pathlib import Path

import numpy as np

from .. import action, devices, exterior, fluid, lumped, plume, rifling, sound
from ..config import ACTION_TYPES, CORE_MATERIALS, DEVICE_TYPES, STANCES, Gun
from ..propellants import COMPOSITIONS, GRAINS
from ..results import ShotResult
from ..sound import GROUNDS, PRESET_LABELS, PRESETS, SoundSettings

STATIC_DIR = Path(__file__).parent / "static"
if getattr(sys, "frozen", False):
    CONFIG_DIR = Path(sys._MEIPASS) / "configs"
else:
    CONFIG_DIR = Path(__file__).resolve().parents[2] / "configs"

MODELS = {"fluid": fluid.simulate, "lumped": lumped.simulate}
MAX_POINTS = 600
BLOWDOWN = 0.025  # s after exit the bore is solved on (the sound's default), so recoil includes the gas jet

# Form layout: section -> [(field, label, display unit, SI value per display unit)].
# A "choice" field lists its options in place of the scale ("" = none); a "flag" is on/off.
FIELDS = {
    "barrel": [
        ("bore_diameter", "Bore diameter", "mm", 1e-3),
        ("travel", "Projectile travel", "mm", 1e-3),
        ("chamber_volume", "Chamber volume", "cm³", 1e-6),
        ("chamber_shape", "Chamber shape (fluid model)", "choice", ["cylinder", "case"]),
        ("twist", "Rifling twist (1 turn in; − = left-hand, 0 = smooth)", "in", 0.0254),
        ("groove_depth", "Groove depth", "mm", 1e-3),
        ("freebore", "Freebore (travel before the lands)", "mm", 1e-3),
        ("leade_angle", "Leade angle", "°", 1),
        ("breech_diameter", "Outside diameter at breech", "mm", 1e-3),
        ("muzzle_diameter", "Outside diameter at muzzle", "mm", 1e-3),
    ],
    "case": [
        ("length", "Case length", "mm", 1e-3),
        ("overall_length", "Overall length", "mm", 1e-3),
        ("rim_diameter", "Rim diameter", "mm", 1e-3),
        ("rim_thickness", "Rim thickness", "mm", 1e-3),
        ("groove_diameter", "Groove diameter", "mm", 1e-3),
        ("groove_width", "Groove width", "mm", 1e-3),
        ("base_diameter", "Base diameter", "mm", 1e-3),
        ("shoulder_diameter", "Shoulder diameter", "mm", 1e-3),
        ("shoulder_position", "Shoulder position", "mm", 1e-3),
        ("shoulder_angle", "Shoulder angle", "°", 1),
        ("neck_wall", "Neck wall", "mm", 1e-3),
        ("body_wall", "Body wall", "mm", 1e-3),
        ("head_thickness", "Head thickness", "mm", 1e-3),
        ("primer_diameter", "Primer diameter", "mm", 1e-3),
        ("primer_depth", "Primer pocket depth", "mm", 1e-3),
    ],
    "projectile": [
        ("mass", "Mass", "g", 1e-3),
        ("shot_start_pressure", "Shot-start pressure", "MPa", 1e6),
        ("bore_resistance", "Bore resistance", "MPa", 1e6),
        ("engraving_pressure", "Peak engraving resistance", "MPa", 1e6),
        ("length", "Length", "mm", 1e-3),
        ("ogive_length", "Ogive length", "mm", 1e-3),
        ("meplat_diameter", "Meplat diameter", "mm", 1e-3),
        ("boat_tail_length", "Boat-tail length", "mm", 1e-3),
        ("boat_tail_angle", "Boat-tail angle", "°", 1),
        ("drag_model", "Drag model", "choice", ["G7", "G1"]),
        ("ballistic_coefficient", "Ballistic coefficient (blank = estimate)", "kg/m²", 1),
        ("ogive_radius_ratio", "Ogive radius ratio", "", 1),
        ("hollow_point_diameter", "Hollow-point diameter", "mm", 1e-3),
        ("hollow_point_depth", "Hollow-point depth", "mm", 1e-3),
        ("cannelure_position", "Cannelure position", "mm", 1e-3),
        ("cannelure_width", "Cannelure width", "mm", 1e-3),
        ("cannelure_depth", "Cannelure depth", "mm", 1e-3),
        ("jacket_thickness", "Jacket thickness", "mm", 1e-3),
        ("core_material", "Core material", "choice", list(CORE_MATERIALS)),
        ("exposed_core_length", "Exposed core length", "mm", 1e-3),
    ],
    "propellant": [
        ("charge_mass", "Charge mass", "g", 1e-3),
        ("composition", "Composition", "choice", ["", *COMPOSITIONS]),
        ("grain", "Grain shape", "choice", ["", *(g for g in GRAINS if g != "ball")]),
        ("force", "Force (impetus)", "kJ/kg", 1e3),
        ("covolume", "Covolume", "cm³/g", 1e-3),
        ("gamma", "Gamma (γ)", "", 1),
        ("density", "Solid density", "kg/m³", 1),
        ("web", "Web thickness", "mm", 1e-3),
        ("burn_rate_coeff", "Burn-rate coeff. a", "(m/s)/Paⁿ", 1),
        ("burn_rate_exp", "Burn-rate exponent n", "", 1),
        ("form_chi", "Form function χ", "", 1),
        ("form_lambda", "Form function λ", "", 1),
        ("form_mu", "Form function μ", "", 1),
        ("grain_length", "Grain length", "mm", 1e-3),
        ("grain_diameter", "Grain outer diameter", "mm", 1e-3),
        ("perforation_diameter", "Perforation diameter", "mm", 1e-3),
        ("molar_mass", "Gas molar mass", "g/mol", 1e-3),
    ],
    "ignition": [
        ("pressure", "Igniter pressure", "MPa", 1e6),
        ("duration", "Primer flash duration (two-phase)", "ms", 1e-3),
        ("grain_ignition_temperature", "Grain ignition temperature (two-phase)", "K", 1),
    ],
    "action": [
        ("type", "Action", "choice", list(ACTION_TYPES)),
        ("gun_mass", "Gun mass (unloaded)", "kg", 1),
        ("bolt_mass", "Bolt / carrier / slide mass", "g", 1e-3),
        ("bolt_travel", "Bolt stroke (blank = enough to feed + 8 mm)", "mm", 1e-3),
        ("spring_rate", "Return spring rate", "N/mm", 1e3),
        ("spring_preload", "Return spring preload", "N", 1),
        ("unlock_travel", "Unlock travel (blank = 6 mm gas, 3 mm short recoil, 5/6 mm roller/lever)", "mm", 1e-3),
        ("delay_ratio", "Delay ratio, carrier : head (roller/lever; blank = 4 / 6)", "", 1),
        ("bolt_head_mass", "Bolt head mass (roller/lever; blank = a fifth)", "g", 1e-3),
        ("barrel_mass", "Barrel mass (short recoil; blank = from its steel)", "g", 1e-3),
        ("feed_force", "Feeding drag", "N", 1),
        ("rear_restitution", "Bounce off the rear stop", "", 1),
        ("battery_restitution", "Bounce into battery", "", 1),
        ("gas_port_position", "Gas port (travel from seat; blank = 75 %, gas-delayed 10 %)", "mm", 1e-3),
        ("gas_port_diameter", "Gas port diameter", "mm", 1e-3),
        ("piston_diameter", "Piston diameter", "mm", 1e-3),
        ("gas_volume", "Gas cylinder volume", "cm³", 1e-6),
        ("gas_stroke", "Piston stroke before it vents", "mm", 1e-3),
        ("bore_height", "Bore above the shoulder", "mm", 1e-3),
        ("cg_distance", "Butt to centre of mass", "mm", 1e-3),
        ("radius_of_gyration", "Radius of gyration (pitch)", "mm", 1e-3),
    ],
    "muzzle_device": [
        ("type", "Muzzle device", "choice", list(DEVICE_TYPES)),
        ("length", "Length (blank = from the bore)", "mm", 1e-3),
        ("outer_diameter", "Outer diameter (blank = from the bore)", "mm", 1e-3),
        ("baffles", "Baffles, or prongs (blank = 3 brake, 8 suppressor, 4 flash hider)", "", 1),
        ("bore_clearance", "Baffle hole over the bore", "mm", 1e-3),
        ("wall", "Wall and baffle thickness", "mm", 1e-3),
        ("blast_chamber", "Blast chamber (suppressor; blank = 5 bores)", "mm", 1e-3),
        ("baffle_angle", "Baffle cone angle (0 = flat)", "°", 1),
        ("vent_fraction", "Vent opening round the circumference (brake, flash hider)", "", 1),
        ("flare_angle", "Bore flare half-angle (flash hider)", "°", 1),
        ("mass", "Mass (blank = from its steel)", "g", 1e-3),
    ],
    "shooter": [
        ("stance", "Hold", "choice", list(STANCES)),
        ("body_mass", "Body mass moving with the gun", "kg", 1),
        ("shoulder_stiffness", "Shoulder stiffness", "N/mm", 1e3),
        ("shoulder_damping", "Shoulder damping", "N·s/m", 1),
        ("hold_stiffness", "Hold against muzzle rise", "N·m/rad", 1),
        ("hold_damping", "Hold damping", "N·m·s/rad", 1),
    ],
    "solver": [
        ("cells", "Fluid cells", "", 1),
        ("cfl", "CFL number", "", 1),
        ("max_time", "Time limit", "ms", 1e-3),
        ("record_every", "Record every N steps", "", 1),
        ("lumped_dt", "Lumped time step", "µs", 1e-6),
        ("wall_losses", "Wall friction and heat loss in the bore", "flag", None),
        ("two_phase", "Two-phase grain bed (grains move, flame spreads)", "flag", None),
        ("device_resolution", "2D cells across the bore", "", 1),
        ("device_time", "2D muzzle device window after exit", "ms", 1e-3),
        ("gas_port_2d", "Gas port discharge coefficient from 2D", "flag", None),
        ("plume_resolution", "Flash and smoke: 2D cells across the bore", "", 1),
        ("plume_time", "Flash and smoke: 2D window after exit", "ms", 1e-3),
    ],
}


# Sound panel layout, same format as FIELDS. "ground" is a choice, not a number.
SOUND_FIELDS = {
    "listener": [
        ("distance", "Distance from muzzle (0 = shooter's ear)", "m", 1),
        ("angle", "Angle from line of fire (+ right)", "°", 1),
        ("facing", "Facing (0 = downrange, + right)", "°", 1),
        ("listener_height", "Ear height", "m", 1),
        ("muzzle_height", "Muzzle height", "m", 1),
    ],
    "atmosphere": [
        ("temperature", "Temperature", "°C", 1),
        ("humidity", "Relative humidity", "%", 1),
        ("pressure", "Air pressure", "kPa", 1e3),
    ],
    "model": [
        ("blast_cells", "Blast solver cells", "", 1),
        ("blast_radius", "Blast solver radius", "m", 1),
        ("blast_time", "Blast time after exit", "ms", 1e-3),
        ("convection_mach", "Blast convection Mach", "", 1),
        ("sample_rate", "Sample rate", "Hz", 1),
    ],
}


def sound_schema() -> dict:
    return {
        "fields": SOUND_FIELDS,
        "defaults": asdict(SoundSettings()),
        "presets": {k: {**v, "label": PRESET_LABELS[k]} for k, v in PRESETS.items()},
        "grounds": list(GROUNDS),
    }


def _b64(a: np.ndarray) -> str:
    return base64.b64encode(np.asarray(a, dtype="<f4").tobytes()).decode("ascii")


def _envelope(t: np.ndarray, y: np.ndarray, points: int = 1500) -> tuple[list, list]:
    """Min/max pairs per bucket, so a downsampled plot keeps every peak."""
    if len(y) <= 2 * points:
        return t.tolist(), y.tolist()
    edges = np.linspace(0, len(y), points + 1).astype(int)
    xs, ys = [], []
    for a, b in zip(edges[:-1], edges[1:]):
        seg = y[a:b]
        i, j = a + int(np.argmin(seg)), a + int(np.argmax(seg))
        for k in sorted((i, j)):
            xs.append(float(t[k]))
            ys.append(float(y[k]))
    return xs, ys


def synthesize(payload: dict) -> dict:
    gun = Gun.from_dict(payload["gun"])
    gun.solver.cells = int(gun.solver.cells)
    gun.solver.record_every = int(gun.solver.record_every)
    settings_in = dict(payload.get("sound") or {})
    for key in ("blast_cells", "sample_rate"):
        if key in settings_in:
            settings_in[key] = int(settings_in[key])
    snd = sound.synthesize(gun, SoundSettings.from_dict(settings_in))
    t = snd.start_time + np.arange(len(snd.pressure)) / snd.sample_rate
    wt, wp = _envelope(t, snd.pressure)
    nf = snd.near_field
    nt = nf["time"]
    stride = max(1, len(nt) // 800)
    return {
        "sample_rate": snd.sample_rate,
        "start_time": snd.start_time,
        "left": _b64(snd.left),
        "right": _b64(snd.right),
        "reference": _b64(snd.reference),
        "references": {k: _b64(v) for k, v in snd.references.items()},
        "crack_source": snd.crack_source,
        "events": snd.events,
        "stems": [{"name": m["name"], "kind": m["kind"], "time": m["time"], "peak": m["peak"],
                   "left": _b64(m["left"]), "right": _b64(m["right"]),
                   "reference": None if m["reference"] is None else _b64(m["reference"]),
                   "references": None if m["references"] is None
                   else {k: _b64(v) for k, v in m["references"].items()}}
                  for m in snd.stems],
        "stats": snd.stats,
        "waveform": {"time": wt, "pressure": wp},
        "near_field": {
            "radii": nf["radii"],
            "time": nt[::stride].tolist(),
            "pressure": [p[::stride].tolist() for p in nf["pressure"]],
        },
    }


def list_presets() -> dict[str, dict]:
    presets = {}
    for path in sorted(CONFIG_DIR.glob("*.toml")):
        try:
            presets[path.stem] = asdict(Gun.load(path))
        except (OSError, ValueError, tomllib.TOMLDecodeError):
            traceback.print_exc()
    return presets


def schema() -> dict:
    return {"fields": FIELDS, "presets": list_presets(), "models": list(MODELS), "sound": sound_schema(),
            "compositions": COMPOSITIONS, "grains": GRAINS}


def _downsample(*arrays: np.ndarray) -> list[list[float]]:
    n = len(arrays[0])
    idx = np.unique(np.linspace(0, n - 1, min(n, MAX_POINTS)).astype(int)) if n else []
    return [np.asarray(a)[idx].tolist() for a in arrays]


def action_to_json(a: action.ActionResult) -> dict:
    """Recoil and action cycle. The series are already sampled finely enough to animate."""
    def floats(arr):
        return [float(f"{v:.6g}") for v in arr]
    return {
        "kind": a.kind,
        "stance": a.stance,
        "time": floats(a.time),
        "recoil": floats(a.recoil),
        "recoil_velocity": floats(a.recoil_velocity),
        "pitch": floats(a.pitch),
        "bolt": floats(a.bolt),
        "bolt_velocity": floats(a.bolt_velocity),
        "force": floats(a.force),
        "shoulder_force": floats(a.shoulder_force),
        "gas_pressure": floats(a.gas_pressure),
        "events": a.events,
        "warnings": a.warnings,
        "status": a.status,
        "strokes": a.strokes,
        **{k: (None if getattr(a, k) is None else float(getattr(a, k))) for k in (
            "impulse", "free_recoil_velocity", "free_recoil_energy", "max_recoil", "peak_recoil_velocity",
            "peak_shoulder_force", "max_pitch", "bolt_max_travel", "rear_speed", "cycle_time", "cyclic_rate",
            "unlock_pressure", "gas_peak_pressure", "port_cd", "gun_mass")},
        "port_cd_2d": a.port_cd_2d,
        "shot_times": [float(t) for t in a.shot_times],
    }


def result_to_json(r: ShotResult, gun: Gun | None = None, burst: int = 1) -> dict:
    t, x, v, pb, pbase = _downsample(r.time, r.travel, r.velocity, r.breech_pressure, r.base_pressure)
    spin = {k: float(v) for k, v in rifling.spin_report(gun, r).items()} if gun else None
    recoil = None
    if gun and r.left_muzzle and r.loads is not None:
        recoil = action_to_json(action.simulate(gun, r, shots=burst))
    return {
        "model": r.model,
        "left_muzzle": bool(r.left_muzzle),
        "muzzle_velocity": float(r.muzzle_velocity),
        "muzzle_time": float(r.muzzle_time),
        "peak_breech_pressure": float(r.peak_breech_pressure),
        "burnt_at_muzzle": float(r.burnt_at_muzzle),
        "time": t,
        "travel": x,
        "velocity": v,
        "breech_pressure": pb,
        "base_pressure": pbase,
        "profiles": [{"time": float(pt), "x": px.tolist(), "p": pp.tolist()} for pt, px, pp in r.profiles],
        "spin": spin,
        "action": recoil,
        "recoil_impulse": None if r.recoil_impulse is None else float(r.recoil_impulse),
        "device": devices.to_json(r.device) if r.device is not None else None,
        "grain_bed": _bed_to_json(r.grain_bed) if r.grain_bed else None,
    }


def _bed_to_json(bed: dict) -> dict:
    t, lit, burnt = _downsample(bed["t"], bed["lit"], bed["burnt"])
    return {"t": t, "lit": lit, "burnt": burnt, "flame_spread_time": bed["flame_spread_time"],
            "ejected": float(bed["ejected"]), "primer_mass": float(bed["primer_mass"])}


def simulate(payload: dict) -> dict:
    gun = Gun.from_dict(payload["gun"])
    gun.solver.cells = int(gun.solver.cells)
    gun.solver.record_every = int(gun.solver.record_every)
    if not 2 <= gun.solver.cells <= 5000:
        raise ValueError("fluid cells must be between 2 and 5000")
    models = payload.get("models") or list(MODELS)
    # The UI passes the sound's air and blowdown time, so this run is the one the sound uses too.
    blowdown = float(payload.get("blowdown", BLOWDOWN))
    ambient = float(payload.get("ambient_pressure", fluid.ATMOSPHERE))
    burst = int(payload.get("burst", 1))
    if not 1 <= burst <= action.MAX_BURST:
        raise ValueError(f"burst must be between 1 and {action.MAX_BURST} shots")
    fitted = gun.muzzle_device.type != "none"
    results = []
    for name in models:
        if name not in MODELS:
            raise ValueError(f"unknown model {name!r}")
        if name == "fluid":
            r = fluid.simulate_cached(gun, blowdown_time=blowdown, ambient_pressure=ambient)
        else:
            r = MODELS[name](gun, blowdown_time=blowdown)
            if fitted and r.left_muzzle:
                # The lumped model has no 2D device of its own: borrow the fluid model's, lined up on its exit.
                f = fluid.simulate_cached(gun, blowdown_time=blowdown, ambient_pressure=ambient)
                if f.device is not None:
                    r.loads = devices.with_device(r.loads, f.device, r.muzzle_time - f.muzzle_time,
                                                  source=f.loads, exit_time=r.muzzle_time)
                    r.recoil_impulse = r.loads.impulse
        if not math.isfinite(r.muzzle_velocity) or not math.isfinite(r.peak_breech_pressure):
            raise ValueError(f"the {name} model went unstable (non-finite values); check the inputs")
        results.append(result_to_json(r, gun, burst))
    return {"results": results, "travel": gun.barrel.travel}


def plume_field(payload: dict) -> dict:
    """Muzzle flash and smoke for the firing range: the gas leaving the muzzle, solved in 2D.

    payload: gun, and the blowdown and ambient_pressure the shot was simulated with (so the fluid run is shared).
    """
    gun = Gun.from_dict(payload["gun"])
    blowdown = float(payload.get("blowdown", BLOWDOWN))
    ambient = float(payload.get("ambient_pressure", fluid.ATMOSPHERE))
    result, shot = plume.simulate_cached(gun, blowdown, ambient)
    return plume.to_json(result, shot)


def trajectory(payload: dict) -> dict:
    """External ballistics for a gun at a given muzzle velocity: curves plus a range table.

    payload: gun, muzzle_velocity (m/s), and optionally zero_range, max_range, sight_height (m),
    crosswind (m/s), headwind (m/s), atmosphere {temperature (C), pressure (Pa), humidity (%)}.
    """
    gun = Gun.from_dict(payload["gun"])
    v0 = float(payload["muzzle_velocity"])
    zero = float(payload.get("zero_range", 100.0))
    max_range = float(payload.get("max_range", 1000.0))
    if not 1 <= max_range <= 5000:
        raise ValueError("max range must be between 1 and 5000 m")
    if not 1 <= zero <= max_range:
        raise ValueError("zero range must be between 1 m and the max range")
    atm = payload.get("atmosphere") or {}
    traj = exterior.trajectory(
        gun, v0, zero_range=zero, max_range=max_range,
        sight_height=float(payload.get("sight_height", 0.04)),
        crosswind=float(payload.get("crosswind", 0.0)), headwind=float(payload.get("headwind", 0.0)),
        atmosphere=exterior.Atmosphere(**{k: float(v) for k, v in atm.items()}) if atm else None)
    if not np.all(np.isfinite(traj.y)):
        raise ValueError("the trajectory went unstable; check the inputs")
    x, y, v = _downsample(traj.x, traj.y, traj.velocity)
    return {
        "range": x, "drop": y, "velocity": v,
        "drag_model": traj.drag_model,
        "ballistic_coefficient": traj.ballistic_coefficient,
        "launch_angle": traj.launch_angle,
        "stop_reason": traj.stop_reason,
        "max_range": float(traj.x[-1]),
        "stability": float(traj.stability),
        "table": traj.table(exterior.nice_step(max_range)),
    }


def parse_toml(text: str) -> dict:
    return asdict(Gun.from_dict(tomllib.loads(text)))


USER_ERRORS = (ValueError, TypeError, KeyError, tomllib.TOMLDecodeError)


def error_message(e: Exception) -> str:
    """Message for the UI; unexpected errors also get a traceback on stderr."""
    if isinstance(e, USER_ERRORS):
        return str(e)
    traceback.print_exc()
    return f"{type(e).__name__}: {e}"
