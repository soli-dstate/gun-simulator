"""Command-line entry point: python -m gun_sim configs/example_rifle.toml"""

from __future__ import annotations

import argparse
import math
import sys
import time

from . import action, fluid, lumped, rifling, sound
from .config import Gun

MODELS = {"fluid": fluid.simulate, "lumped": lumped.simulate}
RECOIL_BLOWDOWN = 0.025  # s of bore blowdown after exit (as the sound's), so the recoil includes the gas jet


def print_range_table(gun: Gun, result, args) -> None:
    """External ballistics table from the shot's muzzle velocity."""
    from . import exterior

    traj = exterior.trajectory(gun, result.muzzle_velocity, zero_range=args.zero,
                               sight_height=args.sight_height, crosswind=args.wind, max_range=args.range)
    step = exterior.nice_step(args.range)
    print(f"[exterior] {gun.projectile.drag_model} BC {traj.ballistic_coefficient / exterior.LB_IN2:.3f} lb/in^2 "
          f"({traj.ballistic_coefficient:.1f} kg/m^2), v0 {result.muzzle_velocity:.1f} m/s ({result.model} model), "
          f"zero {args.zero:.0f} m, sight {args.sight_height * 1e3:.0f} mm, crosswind {args.wind:g} m/s")
    if traj.stability:
        print(f"  spin drift included (Sg {traj.stability:.2f})")
    print("  range      drop    MOA     mil   windage    MOA  velocity  energy   time")
    print("     m        cm                      cm              m/s       J      s")
    for r in traj.table(step):
        print(f"  {r['range']:5.0f} {r['drop'] * 100:9.1f} {r['drop_moa']:6.1f} {r['drop_mil']:7.2f} "
              f"{r['windage'] * 100:9.1f} {r['windage_moa']:6.1f} {r['velocity']:9.1f} {r['energy']:7.0f} {r['time']:6.3f}")
    if traj.stop_reason != "max range":
        print(f"  (flight ended at {traj.x[-1]:.0f} m: {traj.stop_reason})")
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gun_sim", description="Simulate one shot from a gun config.")
    parser.add_argument("config", help="path to a gun TOML file")
    parser.add_argument("--model", choices=[*MODELS, "both"], default="both")
    parser.add_argument("--cells", type=int, help="override the fluid solver's cell count")
    parser.add_argument("--no-recoil", action="store_true",
                        help="skip the bore blowdown, recoil and action cycle (faster)")
    parser.add_argument("--plot", action="store_true", help="show plots (needs matplotlib)")
    parser.add_argument("--save-plot", metavar="FILE", help="write the plots to an image file")
    parser.add_argument("--sound", metavar="FILE.wav", help="synthesise the sound of the shot to a .wav file")
    parser.add_argument("--listener", choices=list(sound.PRESETS), default="shooter",
                        help="where the sound is heard from (default: shooter)")
    parser.add_argument("--ground", choices=list(sound.GROUNDS), help="ground type (default: grass)")
    parser.add_argument("--range", type=float, metavar="METRES",
                        help="print a drop/windage/velocity table out to this range")
    parser.add_argument("--zero", type=float, default=100.0, metavar="METRES",
                        help="with --range: zero range (default: 100)")
    parser.add_argument("--sight-height", type=float, default=0.04, metavar="METRES",
                        help="with --range: line of sight height above the bore (default: 0.04)")
    parser.add_argument("--wind", type=float, default=0.0, metavar="M/S",
                        help="with --range: crosswind from left to right (negative = from the right)")
    args = parser.parse_args(argv)

    gun = Gun.load(args.config)
    if args.cells:
        gun.solver.cells = args.cells

    print(f"{gun.name}: {gun.barrel.bore_diameter * 1e3:.2f} mm bore, "
          f"{gun.barrel.travel * 1e3:.0f} mm travel, "
          f"{gun.projectile.mass * 1e3:.2f} g projectile, "
          f"{gun.propellant.charge_mass * 1e3:.2f} g charge\n")

    names = list(MODELS) if args.model == "both" else [args.model]
    results = []
    for name in names:
        start = time.perf_counter()
        blowdown = 0.0 if args.no_recoil else RECOIL_BLOWDOWN
        if name == "fluid":
            result = fluid.simulate_cached(gun, blowdown_time=blowdown)  # the sound below reuses it
        else:
            result = MODELS[name](gun, blowdown_time=blowdown)
        print(result.summary())
        if gun.barrel.twist:
            s = rifling.spin_report(gun, result)
            print(f"  spin at the muzzle   {s['spin_rpm']:9.0f} rpm ({s['spin_energy']:.1f} J), "
                  f"stability Sg {s['stability']:.2f}, peak rifling torque {s['peak_torque']:.2f} N m")
        if not args.no_recoil and result.left_muzzle:
            print(action.simulate(gun, result).summary())
        elapsed = time.perf_counter() - start
        print(f"  (computed in {elapsed:.2f} s)\n")
        results.append(result)

    if args.sound:
        settings = {"preset": args.listener}
        if args.ground:
            settings["ground"] = args.ground
        start = time.perf_counter()
        snd = sound.synthesize(gun, sound.SoundSettings.from_dict(settings))
        full_scale = sound.write_wav(snd, args.sound)
        st = snd.stats
        print(f"[sound] {args.listener}, {st['distance']:.2f} m from the muzzle at {st['angle']:.0f} deg")
        for e in snd.events:
            print(f"  {e['name']:28s} {e['time'] * 1e3:8.1f} ms  {e['peak_db']:6.1f} dB")
        print(f"  peak at the listener       {st['peak_db']:9.1f} dB ({st['peak_pressure']:.0f} Pa)")
        print(f"  recoil impulse             {st['recoil_impulse']:9.2f} N s (incl. gas jet)")
        print(f"  wrote {args.sound} (normalised: 0 dBFS = {20 * math.log10(full_scale / 20e-6):.1f} dB SPL)")
        print(f"  (computed in {time.perf_counter() - start:.2f} s)\n")

    if args.range:
        # Prefer the fluid model's muzzle velocity, else whichever model ran.
        best = next((r for r in results if r.model == "fluid"), results[0])
        print_range_table(gun, best, args)

    if args.plot or args.save_plot:
        from .plotting import plot_results
        plot_results(gun, results, show=args.plot, save_path=args.save_plot)

    return 0 if all(r.left_muzzle for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
