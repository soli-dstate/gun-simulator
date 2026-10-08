"""From the source to the eardrum: everything that happens on the way.

* Directivity of the muzzle blast: the gas cloud is thrown forward, so the blast
  behaves like a source moving down the bore. Ahead of the muzzle the wave is
  compressed (louder, shorter); behind it, it is stretched (quieter, duller).
  The effect fades as the cloud slows.
* Weak-shock theory: far from the muzzle a blast wave still steepens as it
  travels, so its positive phase grows longer and its peak falls a little faster
  than 1/r.
* Air absorption: ISO 9613-1 (classical, plus oxygen and nitrogen relaxation),
  which depends on temperature, humidity and pressure. Applied as a
  minimum-phase filter, so nothing arrives before the wave front.
* Ground: a mirror-image path with a reflection coefficient from the
  Delany-Bazley impedance of porous ground (grass, snow and so on).
* The listener's head: a rigid sphere (Brown and Duda). It gives the interaural
  delay and the high-frequency shadow on the far ear.
"""

from __future__ import annotations

import math

import numpy as np

HEAD_RADIUS = 0.0875  # m


def absorption_db_per_m(f, temperature_k: float, humidity: float, pressure: float):
    """ISO 9613-1 atmospheric absorption coefficient (dB/m) at frequencies f (Hz)."""
    pr = 101325.0
    t0, t01 = 293.15, 273.16
    f = np.asarray(f, dtype=float)
    psat = pr * 10 ** (-6.8346 * (t01 / temperature_k) ** 1.261 + 4.6151)
    h = humidity * psat / pressure  # molar concentration of water vapour, %
    pa = pressure / pr
    tr = temperature_k / t0
    fr_o = pa * (24 + 4.04e4 * h * (0.02 + h) / (0.391 + h))
    fr_n = pa * tr ** -0.5 * (9 + 280 * h * math.exp(-4.170 * (tr ** (-1 / 3) - 1)))
    return 8.686 * f**2 * (
        1.84e-11 / pa * tr**0.5
        + tr**-2.5 * (0.01275 * math.exp(-2239.1 / temperature_k) / (fr_o + f**2 / fr_o)
                      + 0.1068 * math.exp(-3352.0 / temperature_k) / (fr_n + f**2 / fr_n))
    )


def minimum_phase(magnitude: np.ndarray, nfft: int) -> np.ndarray:
    """Minimum-phase response (rfft bins) with the given magnitude, by the real cepstrum."""
    cep = np.fft.irfft(np.log(np.maximum(magnitude, 1e-12)), nfft)
    fold = np.zeros(nfft)
    fold[0] = cep[0]
    fold[1:nfft // 2] = 2 * cep[1:nfft // 2]
    fold[nfft // 2] = cep[nfft // 2]
    return np.exp(np.fft.rfft(fold))


def ground_reflection(f, resistivity: float | None, grazing: float, rho_air: float):
    """Plane-wave reflection coefficient of the ground (rfft bins). grazing in radians."""
    f = np.asarray(f, dtype=float)
    if resistivity is None:
        return np.zeros_like(f, dtype=complex)
    x = rho_air * np.maximum(f, 1.0) / resistivity
    z = 1 + 0.0571 * x**-0.754 - 1j * 0.087 * x**-0.732  # Delany-Bazley, normalised by rho c
    s = math.sin(max(grazing, 1e-4))
    r = (z * s - 1) / (z * s + 1)
    r[f == 0] = 1.0
    return r


def head_responses(f, direction, facing_deg: float, c0: float):
    """(left, right) ear transfer functions for sound travelling along `direction`.

    `direction` is the unit propagation vector at the listener. The responses
    include the interaural delay (relative to the head centre, made causal).
    """
    phi = math.radians(facing_deg)
    # x downrange, y to the left; facing 90 deg (to the right) looks along -y, so the left ear points along +x.
    left_axis = np.array([math.sin(phi), math.cos(phi), 0.0])
    towards_source = -np.asarray(direction, dtype=float)
    w = 2 * np.pi * np.asarray(f, dtype=float)
    w0 = c0 / HEAD_RADIUS
    out = []
    for axis in (left_axis, -left_axis):
        theta = math.acos(float(np.clip(towards_source @ axis, -1.0, 1.0)))  # 0 = source at this ear
        alpha = 1.05 + 0.95 * math.cos(theta * 180 / 150)
        shadow = (1 + 1j * alpha * w / (2 * w0)) / (1 + 1j * w / (2 * w0))
        # Woodworth delay around a sphere, shifted so the earliest ear is at >= 0.
        if theta < math.pi / 2:
            delay = -HEAD_RADIUS / c0 * math.cos(theta)
        else:
            delay = HEAD_RADIUS / c0 * (theta - math.pi / 2)
        delay += HEAD_RADIUS / c0
        out.append(shadow * np.exp(-1j * w * delay))
    return out[0], out[1]


def shock_fit(t: np.ndarray, p: np.ndarray) -> np.ndarray:
    """Restore the sharp front of a numerically smeared shock.

    Finds the main shock (the steepest rise before the global peak), extrapolates
    the decay behind it back to the shock's midpoint and puts a jump there.
    """
    p = p.copy()
    k = int(np.argmax(p))
    peak = p[k]
    if peak <= 0 or k < 3:
        return p
    # Start of the rise: walk back from the peak to 10 % of it.
    i10 = k
    while i10 > 0 and p[i10] > 0.1 * peak:
        i10 -= 1
    # Midpoint (50 %) of the rise.
    i50 = i10 + int(np.argmax(p[i10:k + 1] >= 0.5 * peak))
    # Fit the decay over the first third of the positive phase after the peak.
    zero = k + int(np.argmax(p[k:] <= 0))
    j = slice(k, k + max((zero - k) // 3, 3))
    if zero <= k or p[j].size < 3:
        return p
    slope, icpt = np.polyfit(t[j], p[j], 1)
    fitted = slope * t[i50:k + 1] + icpt
    p[i10:i50] = p[i10]
    p[i50:k + 1] = np.maximum(fitted, p[i50:k + 1])
    return p


def directivity_warp(t: np.ndarray, p: np.ndarray, t_arrival: float, cos_theta: float,
                     mach: float, t_relax: float):
    """Muzzle-blast directivity as a source convecting along the bore.

    Near the start of the wave, time is compressed by k = 1 / (1 - M cos(theta))
    and the amplitude scaled by k^2 (Doppler on a monopole whose strength is a
    rate). Both relax to 1 over t_relax as the gas cloud slows down.
    Returns the warped signal sampled on t.
    """
    k = 1 / (1 - mach * cos_theta)
    tau = np.maximum(t - t_arrival, 0.0)
    relax = np.exp(-tau / t_relax)
    # Source time: integral of the compression rate 1 + (k - 1) exp(-tau / t_relax).
    src_tau = tau + (k - 1) * t_relax * (1 - relax)
    gain = 1 + (k * k - 1) * relax
    warped = np.interp(t_arrival + src_tau, t, p) * gain
    return np.where(t >= t_arrival, warped, p)


def weak_shock_stretch(peak: float, positive_phase: float, r_ref: float, r: float,
                       rho0: float, c0: float, gamma: float = 1.4) -> float:
    """Factor by which a blast wave's duration grows (and its peak falls) from r_ref to r."""
    if r <= r_ref or peak <= 0 or positive_phase <= 0:
        return 1.0
    beta = (gamma + 1) / 2
    sigma = beta * peak * r_ref / (rho0 * c0**3 * positive_phase) * math.log(r / r_ref)
    return math.sqrt(1 + sigma)


def decimate(x: np.ndarray, factor: int) -> np.ndarray:
    """Low-pass (windowed sinc, 0.45 of the output rate) and keep every factor-th sample."""
    if factor == 1:
        return x
    taps = 32 * factor + 1
    n = np.arange(taps) - taps // 2
    cutoff = 0.9 / (2 * factor)  # fraction of the input rate
    h = 2 * cutoff * np.sinc(2 * cutoff * n) * np.blackman(taps)
    h /= h.sum()
    nfft = 1 << int(math.ceil(math.log2(len(x) + taps)))
    y = np.fft.irfft(np.fft.rfft(x, nfft) * np.fft.rfft(h, nfft), nfft)[taps // 2: taps // 2 + len(x)]
    return y[::factor]
