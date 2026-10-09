"""The muzzle jet's roar: turbulent mixing noise while the bore empties.

After the projectile leaves, the propellant gas blows out of the muzzle as a
hot, highly under-expanded jet for as long as the bore takes to empty. The
spherical blast solver (blast.py) carries the jet's mass and energy but, being
one-dimensional, has no turbulence; this is the roar that turbulence makes.

* Speed and size of the jet: the muzzle's state (fluid.py's p_exit, u_exit,
  rho_exit) is expanded to ambient pressure. The fully expanded jet's velocity
  carries the same thrust, U_j = u + (p - p_a) / (rho u); its diameter holds
  the mass flow at the expanded density.
* Loudness: a share of the jet's mechanical power, 1/2 mdot U_j^2, is radiated
  as sound. Lighthill's U^8 law (efficiency ~1e-4 M^5) up to the ~0.5 % that
  hot supersonic jets (rockets, gun muzzles) reach.
* Spectrum: the large-scale turbulence's hump, peaking at a Strouhal number
  f D_j / U_j of about 0.2, rising as f^2 below and falling as f^-2 above.
* Directivity: loudest some 30-45 degrees off the jet's axis, quietest behind
  the gun (measured jet noise; the table below, normalised to the sphere's
  average).

A muzzle brake or flash hider lets the gas out at about the same speed; a
suppressor holds it and lets it out slow, at the share of the momentum that
survives it.
"""

from __future__ import annotations

import math

import numpy as np

EFFICIENCY_MAX = 0.005
STROUHAL = 0.2
# dB re the sphere's average, at degrees from the jet's axis (0 = straight downrange).
_DIR_DEG = np.array([0.0, 20.0, 35.0, 50.0, 70.0, 90.0, 120.0, 150.0, 180.0])
_DIR_DB = np.array([3.0, 7.0, 8.0, 6.0, 3.0, 0.0, -3.0, -5.0, -6.0])


def _normalised_directivity():
    theta = (np.arange(720) + 0.5) * math.pi / 720
    gain = 10 ** (np.interp(np.degrees(theta), _DIR_DEG, _DIR_DB) / 10)
    mean = np.sum(gain * np.sin(theta)) * (math.pi / 720) / 2  # average over the sphere
    return _DIR_DB - 10 * math.log10(mean)


_DIR_NORM = _normalised_directivity()


def directivity(cos_theta: float) -> float:
    """Intensity gain (re the sphere's average) at an angle theta from the bore."""
    deg = math.degrees(math.acos(max(-1.0, min(1.0, cos_theta))))
    return 10 ** (float(np.interp(deg, _DIR_DEG, _DIR_NORM)) / 10)


def roar(mf, gun, device, fs: float, p_a: float, c0: float, rho_air: float, seed: int = 7):
    """(t0, wave, peak frequency): pressure (Pa) at 1 m, averaged over directions, from muzzle exit t0.

    None if there is no jet.
    """
    prop = gun.propellant
    after = mf.t >= mf.exit_time
    t = mf.t[after]
    p, u, rho = mf.p_exit[after], mf.u_exit[after], mf.rho_exit[after]
    mdot = np.maximum(mf.mdot[after], 0.0)
    if t.size < 2 or mdot.max() <= 0:
        return None
    ok = (u > 1.0) & (rho > 0)
    u_j = np.where(ok, u + np.maximum(p - p_a, 0.0) / np.maximum(rho * u, 1e-9), 0.0)
    # Expanded isentropically to ambient pressure: its temperature, density and diameter.
    temp = p * (1 - prop.covolume * rho) / (np.maximum(rho, 1e-9) * prop.gas_constant)
    ratio = np.clip(p_a / np.maximum(p, p_a), 0.0, 1.0)
    t_j = np.maximum(temp * ratio ** ((prop.gamma - 1) / prop.gamma), 250.0)
    rho_j = p_a / (prop.gas_constant * t_j)
    d_j = np.sqrt(4 * mdot / (math.pi * rho_j * np.maximum(u_j, 1.0)))

    if device is not None and device.dims["type"] == "suppressor":
        # The gas leaves the suppressor slowly, at its own rate.
        mdot = np.maximum(np.gradient(np.interp(t, device.t, device.out_propellant), t), 0.0)
        u_j = u_j * device.momentum_ratio
        d_j = np.full_like(t, device.dims["outer_radius"])  # about its exit's spread

    mach = u_j / c0
    efficiency = np.minimum(1e-4 * mach**5, EFFICIENCY_MAX)
    power = efficiency * 0.5 * mdot * u_j**2
    if power.max() <= 0:
        return None
    # Intensity at 1 m over the sphere: p_rms^2 = rho c W / (4 pi).
    p_rms = np.sqrt(rho_air * c0 * power / (4 * math.pi))

    # The hump's peak frequency, weighted by when the jet is loudest.
    f_peak = STROUHAL * u_j / np.maximum(d_j, 1e-4)
    w = power * np.gradient(t)
    fp = float(np.exp(np.sum(w * np.log(np.maximum(f_peak, 50.0))) / np.sum(w)))
    fp = min(fp, 0.4 * fs)

    end = t[np.nonzero(p_rms >= 1e-3 * p_rms.max())[0][-1]]
    n = int(math.ceil((end - t[0]) * fs)) + 1
    tt = t[0] + np.arange(n) / fs
    env = np.interp(tt, t, p_rms)
    env *= np.minimum(1.0, (tt - t[0]) / 5e-5)  # the jet builds up over the first tens of microseconds

    rng = np.random.default_rng(seed)
    nfft = 1 << int(math.ceil(math.log2(n + 64)))
    f = np.fft.rfftfreq(nfft, 1 / fs)
    x = f / fp
    shape = x / (1 + x * x)  # amplitude: f below the peak, 1/f above (power f^2, f^-2)
    noise = np.fft.irfft(np.fft.rfft(rng.standard_normal(nfft)) * shape, nfft)[:n]
    noise /= np.sqrt(np.mean(noise**2)) or 1.0
    return float(t[0]), noise * env, fp
