"""Propellant library: composition presets and grain geometries.

Two things a gun designer usually looks up rather than measures:

* The thermochemistry and burn law of a propellant family (COMPOSITIONS).
  Single-base (nitrocellulose), double-base (nitrocellulose + nitroglycerine)
  and triple-base (adds nitroguanidine) powders differ mainly in how much
  energy they release per kg, how hot and how "heavy" the gas is, and how
  fast they burn. The values here are generic and illustrative, drawn from
  textbook ranges. They are NOT data for any commercial product.

* Flash-suppressant additives (SUPPRESSANTS): potassium salts that keep the
  gas from reigniting in air outside the muzzle, at some cost in impetus and
  a smokier muzzle.

* The shape of the grain (GRAINS). The form function psi(z) gives the mass
  fraction burnt once a fraction z of the web has burnt away. A grain's shape
  fixes its coefficients.

Form function
-------------
Let e1 = web / 2 be the half web. Burning proceeds from both faces, so the
burnt depth is z * e1 and dz/dt = r / e1 = 2 r / web. Here r = a p^n is the
linear burn rate (Vieille's law). The burnt mass fraction is the classic
three-term geometric law

    phase 1, 0 <= z <= 1:      psi = chi * z * (1 + lambda z + mu z^2)

with chi (1 + lambda + mu) = 1 for a grain that burns out at z = 1.

Multi-perforated grains (7-perf, 19-perf) do not burn out at z = 1. The
webs between the perforations are gone, but thin slivers of the cylinder
remain. The slivers burn in a second phase,

    phase 2, 1 < z <= z_k:     psi = chi_s z (1 + lambda_s z),

chosen so psi is continuous at z = 1 and reaches 1 at z_k = (e1 + rho) / e1,
where the sliver thickness is rho = 0.1547 (e1 + d/2) and d is the
perforation diameter. The 3-term coefficients for a multi-perforated
cylinder of length L = 2c, outer diameter D and n perforations are

    Pi1 = (D + n d) / L,   Q1 = (D^2 - n d^2) / L^2,   beta = web / L
    chi    = (Q1 + 2 Pi1) / Q1 * beta
    lambda = (n - 1 - 2 Pi1) / (Q1 + 2 Pi1) * beta
    mu     = -(n - 1) beta^2 / (Q1 + 2 Pi1)

Shapes and their coefficients (web = full web, the thickness that burns from
both faces; for a sphere the web is the diameter):

* tube:   one central perforation, length L. beta = web / L,
          chi = 1 + beta, lambda = -beta / (1 + beta), mu = 0.
          As L grows, chi -> 1 and lambda -> 0, the neutral grain of the
          textbook examples.
* sphere: psi = 1 - (1 - z)^3, so chi = 3, lambda = -1, mu = 1/3 (degressive).
* flake:  square plate of side a and thickness web, alpha = beta = web / a,
          chi = 1 + alpha + beta, lambda = -(alpha + beta + alpha beta) / chi,
          mu = alpha beta / chi.
* 7-perf and 19-perf: cylinders with 7 or 19 holes in a hexagonal pattern.
  The outer diameter D sets the row of holes through the centre: 3 holes
  across for 7-perf, 5 for 19-perf, with a web between each neighbouring pair
  and one more web at each outer wall. So D = k d + (k + 1) web, k = 3 or 5.
  Either D or the web can be left out and worked out from the other.

Grain geometries are resolved to coefficients by grain_geometry and
form_coefficients. Propellant in config.py calls them when a grain is named.
"""

from __future__ import annotations

import numpy as np

# Generic propellant families. Units are SI: force J/kg, covolume m^3/kg,
# density kg/m^3, burn-rate coefficient (m/s)/Pa^n, molar mass kg/mol.
COMPOSITIONS: dict[str, dict[str, float]] = {
    # Nitrocellulose only: the lowest energy of the three, but a well-behaved,
    # slow-burning gas. The burn law matches the example rifle.
    "single_base": {
        "force": 0.98e6, "covolume": 1.0e-3, "gamma": 1.245, "density": 1600.0,
        "burn_rate_coeff": 7.0e-9, "burn_rate_exp": 0.9, "molar_mass": 0.025,
    },
    # Nitrocellulose plus nitroglycerine: more energy and a higher density,
    # with a slightly lower gamma and a more pressure-sensitive burn.
    "double_base": {
        "force": 1.10e6, "covolume": 1.0e-3, "gamma": 1.225, "density": 1620.0,
        "burn_rate_coeff": 6.0e-9, "burn_rate_exp": 0.85, "molar_mass": 0.024,
    },
    # Adds nitroguanidine to cool the flame. The gas is lighter (lower molar
    # mass), so the energy per kg stays similar while the burn is slower.
    "triple_base": {
        "force": 1.03e6, "covolume": 1.0e-3, "gamma": 1.22, "density": 1640.0,
        "burn_rate_coeff": 5.0e-9, "burn_rate_exp": 0.8, "molar_mass": 0.022,
    },
}

# What in each family's product gas can still burn in air: mass fractions of
# CO and H2. Gun propellants are oxygen-poor, so their gas is fuel-rich; once it
# mixes with air outside the muzzle it can reignite (the secondary flash).
# Nitroglycerine adds oxygen, so double-base gas is leaner; nitroguanidine
# adds hydrogen and nitrogen. Illustrative, like the families above.
PRODUCTS: dict[str, dict[str, float]] = {
    "single_base": {"co": 0.42, "h2": 0.012},
    "double_base": {"co": 0.32, "h2": 0.008},
    "triple_base": {"co": 0.26, "h2": 0.014},
}
_HEATING = {"co": 10.1e6, "h2": 120.0e6}  # J/kg, lower heating values
_OXYGEN = {"co": 0.571, "h2": 7.94}       # kg O2 per kg burnt


# Flash suppressants: potassium salts mixed into the grains at a percent or two.
# They don't stop the gas being fuel-rich. Potassium freed into the hot gas
# (K, KOH) recombines the H and OH radicals that carry the CO/H2 flame, so the
# gas has to be hotter before it reignites in air; the secondary flash is put
# out, or starts later and smaller. The price: the salt is mass that makes no
# gas and soaks up heat (less impetus, a cooler flame), and it ends up as fine
# particles, so the muzzle smokes more.
#
#   potassium: mass fraction of K, which sets how much inhibitor a kg frees
#   sink:      J/kg the salt takes from the flame to heat, melt and come apart
#              (negative: it gives heat)
#   oxygen:    kg O2 a kg of it gives up to burn the gas's fuel in the bore
#   residue:   kg of particles (sulfate, carbonate, fluoride) left per kg
#
# Potassium nitrate is an oxidizer: it burns some of the CO in the bore,
# so it costs no impetus and leaves less to afterburn, but it draws water.
# Illustrative values, like the families above.
SUPPRESSANTS: dict[str, dict[str, float]] = {
    "potassium_sulfate": {"potassium": 0.449, "sink": 2.5e6, "oxygen": 0.0, "residue": 1.0},
    "potassium_nitrate": {"potassium": 0.387, "sink": -2.4e6, "oxygen": 0.396, "residue": 0.68},
    "potassium_cryolite": {"potassium": 0.454, "sink": 2.8e6, "oxygen": 0.0, "residue": 1.0},
}
# Afterburning is slowed by 1 + INHIBITION * (kg of K per kg of gas) * (share of
# propellant gas in the cell): the inhibitor thins out as the gas mixes with air.
# Set so that about 1 % of potassium sulfate puts out the example rifle's
# secondary flash, as a percent or two does in practice. Reignition is all or
# nothing: half as much hardly helps.
INHIBITION = 1.2e5
# Particles and condensate already in the smoke of a plain propellant, kg per kg
# of gas (what the 3D view's smoke is scaled to).
BASE_SMOKE = 0.004


def suppressant(name: str | None) -> dict[str, float]:
    """The data of a flash suppressant (zeros for None)."""
    if name is None:
        return {"potassium": 0.0, "sink": 0.0, "oxygen": 0.0, "residue": 0.0}
    if name not in SUPPRESSANTS:
        raise ValueError(f"unknown flash_suppressant {name!r}; choose from {', '.join(SUPPRESSANTS)}")
    return SUPPRESSANTS[name]


def combustibles(composition: str | None, additive: str | None = None,
                 fraction: float = 0.0) -> tuple[float, float, float]:
    """(fuel fraction of the gas, J released per kg of fuel, kg O2 needed per kg of fuel).

    A propellant without a named composition burns like single-base. A share
    `fraction` of the charge that is the flash suppressant `additive` makes no
    fuel, and an oxidizing one burns some of the rest before it leaves the bore.
    """
    gas = PRODUCTS.get(composition or "single_base", PRODUCTS["single_base"])
    fuel = sum(gas.values())
    heat = sum(gas[k] * _HEATING[k] for k in gas) / fuel
    oxygen = sum(gas[k] * _OXYGEN[k] for k in gas) / fuel
    salt = suppressant(additive)
    fuel = max((1 - fraction) * fuel - fraction * salt["oxygen"] / oxygen, 0.0)
    return fuel, heat, oxygen


def inhibition(additive: str | None, fraction: float) -> float:
    """How strongly the suppressant slows afterburning in pure propellant gas (0 = not at all)."""
    return INHIBITION * suppressant(additive)["potassium"] * fraction


def smokiness(additive: str | None, fraction: float) -> float:
    """The smoke's density relative to the same propellant without the suppressant."""
    return 1.0 + suppressant(additive)["residue"] * fraction / BASE_SMOKE


# Grain shapes and a one-line description of each.
GRAINS: dict[str, str] = {
    "tube": "single-perforation tube (web = wall thickness, grain_length = tube length)",
    "sphere": "ball powder (web = diameter)",
    "ball": "alias of sphere",
    "flake": "square flake (web = thickness, grain_length = side)",
    "7-perf": "seven-perforation cylinder (grain_diameter, perforation_diameter, grain_length)",
    "19-perf": "nineteen-perforation cylinder (grain_diameter, perforation_diameter, grain_length)",
}

# Holes across the centre row of a hexagonal perforation pattern.
_PERF_ROW = {7: 3, 19: 5}
_PERF_COUNT = {"7-perf": 7, "19-perf": 19}
_SLIVER_RATIO = 0.1547  # rho / (e1 + d/2), sliver thickness factor


def _canonical(grain: str) -> str:
    if grain not in GRAINS:
        raise ValueError(f"unknown grain {grain!r}; choose from {', '.join(GRAINS)}")
    return "sphere" if grain == "ball" else grain


def is_multi_perf(grain: str) -> bool:
    """True for grains that leave sliver phase behind (z_k > 1)."""
    return _canonical(grain) in _PERF_COUNT


def grain_geometry(grain: str, web: float | None = None, length: float | None = None,
                   diameter: float | None = None, perforation_diameter: float | None = None
                   ) -> tuple[float, float | None]:
    """Fill in the web and outer diameter of a grain from what was given.

    Returns (web, diameter). The diameter is None for grains whose shape does
    not use one. Raises ValueError naming any dimension that is missing.
    """
    shape = _canonical(grain)

    def need(**given: float | None) -> None:
        missing = [name for name, value in given.items() if not value]
        if missing:
            raise ValueError(f"grain {grain!r} needs {', '.join(missing)}")

    if shape == "sphere":
        web = web or diameter
        if not web:
            raise ValueError(f"grain {grain!r} needs web (its diameter) or grain_diameter")
        return web, None
    if shape in ("tube", "flake"):
        need(web=web, grain_length=length)
        return web, None

    # Multi-perforated cylinder: web and diameter are tied by D = k d + (k + 1) web.
    k = _PERF_ROW[_PERF_COUNT[shape]]
    need(perforation_diameter=perforation_diameter)
    if not web:
        need(grain_diameter=diameter)
        web = (diameter - k * perforation_diameter) / (k + 1)
        if web <= 0:
            raise ValueError("grain_diameter is too small for its perforations")
    if not diameter:
        diameter = k * perforation_diameter + (k + 1) * web
    return web, diameter


def form_coefficients(grain: str, web: float, length: float | None = None,
                      diameter: float | None = None, perforation_diameter: float | None = None
                      ) -> tuple[float, float, float]:
    """Return (chi, lambda, mu) of the phase-1 form function for a grain shape."""
    shape = _canonical(grain)
    if shape == "sphere":
        return 3.0, -1.0, 1.0 / 3.0
    if shape == "tube":
        beta = web / length
        chi = 1 + beta
        return chi, -beta / chi, 0.0
    if shape == "flake":
        alpha = web / length  # beta = alpha for a square plate
        chi = 1 + 2 * alpha
        return chi, -(2 * alpha + alpha**2) / chi, alpha**2 / chi

    n = _PERF_COUNT[shape]
    pi1 = (diameter + n * perforation_diameter) / length
    q1 = (diameter**2 - n * perforation_diameter**2) / length**2
    beta = web / length
    denom = q1 + 2 * pi1
    chi = denom / q1 * beta
    lam = (n - 1 - 2 * pi1) / denom * beta
    mu = -(n - 1) * beta**2 / denom
    return chi, lam, mu


def sliver_phase(web: float, perforation_diameter: float, psi_1: float) -> tuple[float, float, float]:
    """Second-phase coefficients (chi_s, lambda_s, z_k) of a multi-perforated grain.

    psi_1 is the phase-1 burnt fraction at z = 1. The slivers then burn from
    psi_1 to 1 over 1 < z <= z_k, with psi continuous at z = 1.
    """
    if not 0.0 < psi_1 < 1.0:
        raise ValueError(f"multi-perforated grain must leave slivers: psi(1) = {psi_1:.4g} is not in (0, 1)")
    e1 = web / 2
    rho = _SLIVER_RATIO * (e1 + perforation_diameter / 2)
    z_k = (e1 + rho) / e1
    # With u = chi_s * lambda_s: chi_s + u = psi_1 and z_k chi_s + z_k^2 u = 1.
    chi_s, u = np.linalg.solve(np.array([[1.0, 1.0], [z_k, z_k**2]]), np.array([psi_1, 1.0]))
    return float(chi_s), float(u / chi_s), float(z_k)
