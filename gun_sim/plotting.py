"""Matplotlib plots of shot results."""

from __future__ import annotations

import matplotlib.pyplot as plt

from .config import Gun
from .results import ShotResult


def plot_results(gun: Gun, results: list[ShotResult], show: bool = True, save_path: str | None = None):
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5), layout="constrained")
    fig.suptitle(gun.name)
    ax_p, ax_v, ax_prof = axes

    for r in results:
        ax_p.plot(r.time * 1e3, r.breech_pressure / 1e6, label=f"{r.model} breech")
        ax_p.plot(r.time * 1e3, r.base_pressure / 1e6, "--", label=f"{r.model} base")
        ax_v.plot(r.travel * 1e3, r.velocity, label=r.model)

    ax_p.set(xlabel="time (ms)", ylabel="pressure (MPa)", title="Pressure history")
    ax_v.set(xlabel="travel (mm)", ylabel="velocity (m/s)", title="Projectile velocity")
    ax_p.legend()
    ax_v.legend()

    fluid_results = [r for r in results if r.profiles]
    if fluid_results:
        for t, x, p in fluid_results[0].profiles:
            ax_prof.plot(x * 1e3, p / 1e6, label=f"{t * 1e3:.3f} ms")
        ax_prof.axvline(0, color="grey", lw=0.8, ls=":")
        ax_prof.set(xlabel="position from seated base (mm)", ylabel="pressure (MPa)",
                    title="Pressure along the bore (fluid)")
        ax_prof.legend(fontsize="small")
    else:
        ax_prof.set_visible(False)

    for ax in axes:
        ax.grid(alpha=0.3)
    if save_path:
        fig.savefig(save_path, dpi=120)
    if show:
        plt.show()
    return fig
