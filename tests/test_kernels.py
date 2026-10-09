"""The compiled kernels compute what the NumPy code they stand in for does."""

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("numba")

from gun_sim import Gun, devices, fluid, kernels  # noqa: E402
from gun_sim.axisym import Afterburn, Axisymmetric  # noqa: E402
from gun_sim.chamber import ChamberProfile  # noqa: E402

RIFLE = Path(__file__).parent.parent / "configs" / "example_rifle.toml"


def bore_state(n=40, seed=1):
    rng = np.random.default_rng(seed)
    x = np.linspace(0, 1, n)
    q = 200 * (1 + 0.3 * np.sin(5 * x)) + rng.uniform(0, 5, n)
    u = 300 * x + rng.uniform(-20, 20, n)
    p = 2e8 * (1 - 0.5 * x) + rng.uniform(0, 1e7, n)
    e = 3e6 * (1 + 0.1 * np.cos(3 * x))
    c = 1000 + rng.uniform(0, 100, n)
    w = np.linspace(0, 1, n + 1) * 250.0
    return q, u, p, e, c, w


@pytest.mark.parametrize("ghost", [None, (150.0, 400.0, 1e8, 2.5e6, 900.0)])
def test_bore_fluxes(ghost):
    q, u, p, e, c, w = bore_state()
    want = fluid._faces(q, u, p, e, c, w, ghost)
    got = kernels.bore_fluxes(q, u, p, e, c, w, ghost is None, np.array(ghost or np.zeros(5), dtype=float))
    for a, b in zip(got, want):
        np.testing.assert_allclose(a, b, rtol=1e-12, atol=1e-6)


def test_bore_rhs_through_a_bottleneck_chamber():
    gun = Gun.load(RIFLE)
    chamber = ChamberProfile.from_case(gun)
    q, u, p, e, c, w = bore_state()
    nodes = np.linspace(0, chamber.length * 1.6, q.size + 1)  # into the bore too
    want = fluid._bore_rhs(q, u, p, e, c, w, nodes, None, chamber)
    got = kernels.bore_rhs(q, u, p, e, c, w, nodes, True, np.zeros(5), chamber.edges, chamber.area, chamber.bore_area)
    for a, b in zip(got, want):
        np.testing.assert_allclose(a, b, rtol=1e-12, atol=1e-6)


def stirred_device():
    """A small device with walls, perforated faces, held inlet cells and afterburning, mid-flow."""
    solid = np.zeros((40, 12), bool)
    solid[20:22, 3:10] = True
    ox, orr = np.ones((41, 12)), np.ones((40, 13))
    devices._shut(solid, ox, orr)
    orr[30, 5] = 0.2
    ox[25, 1:4] = 0.3
    s = Axisymmetric(1e-3, 0.0, solid, ox, orr, 330.0, 1.24, 101325.0, 288.15, force_from=0.01,
                     afterburn=Afterburn(0.3, 1e7, 0.6, inhibition=2.0))
    inlet = np.zeros_like(solid)
    inlet[:2, :3] = True
    s.set_fixed(inlet, 20.0, 600.0, 2.5e6)
    for _ in range(30):
        s.step(1.0)
    return s


@pytest.mark.parametrize("rhs", [kernels.axisym_rhs, kernels.axisym_rhs_parallel])
def test_axisym_rhs(rhs):
    s = stirred_device()
    dU, flows, force, prims = s._rhs_numpy(s.U)
    got = rhs(s.U, s.open_x, s.open_r, s.solid, s.fixed, s.area_x, s.area_r, s.d_area_r, s.volume,
              s.force_faces, s.out_right, s.out_left, s.out_top, s.size, float(s.p0), float(s.cva),
              float(s.cvp), float(s.rp))
    # NumPy works in float32 throughout; the kernel in float64.
    for k in range(s.nv):
        assert np.abs(got[0][k] - dU[k]).max() <= 1e-4 * np.abs(dU[k]).max() + 1e-12
    np.testing.assert_allclose(got[1], flows, rtol=1e-4, atol=1e-4 * np.abs(flows).max())
    assert got[2] == pytest.approx(force, rel=1e-4, abs=1e-6)
    assert s.cfl / got[3] == pytest.approx(s.max_dt(prims), rel=1e-5)


def test_axisym_sources():
    s = stirred_device()
    heat, burnt = s.heat, s.burnt
    U = s.U.copy()
    s._cool(U, 1e-6)
    s._burn(U, 1e-6)
    a = s.afterburn
    V = s.U.copy()
    lost, released = kernels.axisym_sources(
        V, 1e-6, s.solid, s.fixed, s.volume, float(s.cva), float(s.cvp), float(s.rp), s.wall_ratio, 0.004, 300.0,
        True, a.fuel, a.heat, a.oxygen, a.inhibition, a.rate, a.activation, a.ceiling, 0.232)
    for k in range(s.nv):
        assert np.abs(V[k] - U[k]).max() <= 1e-5 * np.abs(U[k]).max()
    assert lost == pytest.approx(s.heat - heat, rel=1e-4)
    assert released == pytest.approx(s.burnt - burnt, rel=1e-4)


def test_whole_shot_matches(monkeypatch):
    gun = Gun.load(RIFLE)
    gun.barrel.chamber_shape = "case"
    compiled = fluid.simulate(gun, blowdown_time=0.002)
    monkeypatch.setattr(kernels, "ENABLED", False)
    plain = fluid.simulate(gun, blowdown_time=0.002)
    assert compiled.muzzle_velocity == pytest.approx(plain.muzzle_velocity, rel=1e-9)
    assert compiled.peak_breech_pressure == pytest.approx(plain.peak_breech_pressure, rel=1e-9)
    assert compiled.recoil_impulse == pytest.approx(plain.recoil_impulse, rel=1e-6)
