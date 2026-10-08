"""2D axisymmetric solver, muzzle devices, and their sound."""

import math
from pathlib import Path

import numpy as np
import pytest

from gun_sim import Gun, action, devices, fluid, lumped, sound
from gun_sim.axisym import Axisymmetric

CONFIGS = Path(__file__).parent.parent / "configs"
RIFLE = CONFIGS / "example_rifle.toml"
GAS_RIFLE = CONFIGS / "example_gas_rifle.toml"
BLOWDOWN = 0.025


def open_faces(solid):
    nx, nr = solid.shape
    ox, orr = np.ones((nx + 1, nr)), np.ones((nx, nr + 1))
    devices._shut(solid, ox, orr)
    return ox, orr


def test_gas_at_rest_stays_at_rest_round_walls_and_holes():
    solid = np.zeros((60, 20), bool)
    solid[30:32, 4:16] = True
    ox, orr = open_faces(solid)
    orr[45, 8] = 0.2   # a perforated face
    ox[50, 2:6] = 0.3
    s = Axisymmetric(1e-3, 0.0, solid, ox, orr, 330.0, 1.24, 101325.0, 288.15)
    for _ in range(40):
        s.step(1.0)
    p = s.pressure()[s.fluid]
    assert np.abs(p - 101325.0).max() < 1e-3 * 101325.0
    assert np.abs(s.primitives()[1]).max() < 1e-3


def test_shock_tube_speed():
    """Hot-driver shock tube along the axis: p4/p1 = 10, T4/T1 = 10 gives a Mach 2.15 shock."""
    nx, nr = 200, 4
    solid = np.zeros((nx, nr), bool)
    ox, orr = open_faces(solid)
    s = Axisymmetric(1e-3, 0.0, solid, ox, orr, 287.05, 1.4, 101325.0, 288.15, wall_heat=False)
    s.U[3, :50] *= 10
    while s.t < 1e-4:
        s.step(1.0)
    p = s.pressure()[:, 1]
    front = np.argmax(p < 1.5 * 101325.0) * 1e-3
    expected = 0.05 + 2.145 * 340.3 * s.t
    assert front == pytest.approx(expected, abs=4e-3)


def test_device_conserves_propellant():
    gun = Gun.load(RIFLE)
    gun.muzzle_device.type = "suppressor"
    c = devices.DeviceCoupling(gun, 101325.0)
    s, g = c.solver, c.grid
    vol = s.volume[None, :]
    inside = lambda k: float(np.sum(s.U[k] * vol * ~g.inlet * ~g.solid, dtype=np.float64))
    p0, m0 = inside(4), inside(0)
    rho, u = 100.0, 1200.0
    for k in range(60):
        c.step(k * 3e-6, 3e-6, rho, u, 1.2e6)
    fed = rho * u * gun.barrel.bore_area * 60 * 3e-6
    assert inside(4) - p0 + s.out[4] == pytest.approx(fed, rel=0.02)
    assert inside(0) - m0 + s.out[0] == pytest.approx(fed, rel=0.02)


@pytest.fixture(scope="module")
def shots():
    """The example rifle bare, with a brake and with a suppressor (fluid model, with blowdown)."""
    out = {}
    for kind in ("none", "brake", "suppressor"):
        gun = Gun.load(RIFLE)
        gun.muzzle_device.type = kind
        out[kind] = (gun, fluid.simulate_cached(gun, blowdown_time=BLOWDOWN))
    return out


def test_brake_cuts_recoil(shots):
    bare = shots["none"][1].recoil_impulse
    braked = shots["brake"][1]
    assert braked.device.impulse > 1.0               # the gas pulls the brake forwards
    assert braked.recoil_impulse < 0.9 * bare
    assert braked.loads.impulse == pytest.approx(braked.recoil_impulse, rel=1e-3)


def test_devices_balance_mass_and_energy(shots):
    charge = Gun.load(RIFLE).propellant.charge_mass
    bare_energy = shots["none"][1].muzzle_flow.ejected_energy
    for kind in ("brake", "suppressor"):
        d = shots[kind][1].device
        assert 0.75 * charge < d.out_propellant[-1] < 1.02 * charge
        assert d.out_energy[-1] + d.heat < 1.15 * bare_energy
    # The suppressor holds the gas longer and gives more of its heat to the steel.
    assert shots["suppressor"][1].device.heat > 2 * shots["brake"][1].device.heat
    assert shots["suppressor"][1].device.stored_mass > 0.3e-3


def test_suppressor_back_pressure_reaches_the_bore(shots):
    """A can holds the bore's pressure up after exit: the breech stays pressurised longer."""
    late = lambda r: float(np.interp(r.muzzle_time + 4e-3, r.muzzle_flow.t, r.muzzle_flow.p_breech))
    assert late(shots["suppressor"][1]) > 2 * late(shots["none"][1])


def test_suppressor_is_quieter_and_brake_is_louder_for_the_shooter(shots):
    level = {}
    for kind, (gun, _) in shots.items():
        snd = sound.synthesize(gun, sound.SoundSettings.from_dict({"preset": "shooter"}))
        level[kind] = (snd.stats["peak_db"], snd.stats["blast_1m_db"])
    assert level["suppressor"][1] < level["none"][1] - 10
    assert level["brake"][0] > level["none"][0]


def test_lumped_model_borrows_the_device(shots):
    gun, f = shots["brake"]
    l = lumped.simulate(gun, blowdown_time=BLOWDOWN)
    before = l.loads.impulse
    loads = devices.with_device(l.loads, f.device, l.muzzle_time - f.muzzle_time)
    assert before - loads.impulse == pytest.approx(f.device.impulse, rel=0.05)


def test_device_adds_mass_to_the_gun(shots):
    gun, r = shots["suppressor"]
    m = devices.device_mass(gun)
    assert 0.1 < m < 1.5
    assert action.simulate(gun, r).gun_mass == pytest.approx(gun.action.gun_mass + m)


def test_action_sounds_follow_the_cycle():
    gun = Gun.load(GAS_RIFLE)
    snd = sound.synthesize(gun, sound.SoundSettings.from_dict({"preset": "bystander"}))
    names = [e["name"] for e in snd.events]
    for name in ("action: hammer falls", "action: bolt hits the rear stop", "action: bolt slams home",
                 "action: case lands"):
        assert name in names
    t = {e["name"]: e["time"] for e in snd.events}
    assert t["action: bolt hits the rear stop"] < t["action: bolt slams home"] < t["action: case lands"]
    # Quieter than the blast, by a lot.
    blast = next(e["peak_db"] for e in snd.events if e["name"] == "muzzle blast (direct)")
    assert all(e["peak_db"] < blast - 30 for e in snd.events if e["name"].startswith("action"))


def test_bad_device_rejected():
    gun = Gun.load(RIFLE)
    gun.muzzle_device.type = "flash hider"
    with pytest.raises(ValueError, match="muzzle_device.type"):
        gun.validate()
    gun = Gun.load(RIFLE)
    gun.muzzle_device.type = "suppressor"
    gun.muzzle_device.outer_diameter = 0.01
    with pytest.raises(ValueError, match="too small"):
        gun.validate()
