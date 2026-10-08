import math
from pathlib import Path

import numpy as np
import pytest

from gun_sim import Gun, fluid
from gun_sim.sound import SoundSettings, synthesize, write_wav
from gun_sim.sound import ballistic, propagation
from gun_sim.sound.blast import BlastSource, simulate_blast

RIFLE = Path(__file__).parent.parent / "configs" / "example_rifle.toml"


@pytest.fixture(scope="module")
def gun():
    return Gun.load(RIFLE)


@pytest.fixture(scope="module")
def blowdown(gun):
    return fluid.simulate(gun, blowdown_time=0.025)


def test_blowdown_empties_the_bore(gun, blowdown):
    mf = blowdown.muzzle_flow
    assert mf is not None
    assert mf.exit_pressure > 10e6               # gas still at tens of MPa when the projectile leaves
    # Back to ambient on average: the bore still rings as a closed-open pipe.
    late = mf.t > mf.t[-1] - 0.01
    assert abs(mf.p_breech[late].mean() - 101325) < 0.15 * 101325
    gas = gun.propellant.charge_mass
    assert 0.8 * gas < mf.ejected_mass < 1.05 * gas


def test_gas_jet_adds_to_recoil(gun, blowdown):
    projectile_momentum = gun.projectile.mass * blowdown.muzzle_velocity
    # The jet typically adds a third to a half again on top of the projectile.
    assert 1.2 * projectile_momentum < blowdown.recoil_impulse < 2.0 * projectile_momentum


def test_blowdown_does_not_change_in_bore_results(gun, blowdown):
    plain = fluid.simulate(gun)
    assert plain.muzzle_flow is None
    assert blowdown.muzzle_velocity == pytest.approx(plain.muzzle_velocity, rel=1e-12)


def test_still_air_stays_still():
    """With no source, the spherical solver must keep uniform air exactly at rest."""
    src = BlastSource(t=np.array([0.0, 1.0]), mass=np.zeros(2), energy=np.zeros(2), propellant=np.zeros(2))
    r = simulate_blast(src, 330.0, 1.24, 101325.0, 288.15, radius=1.0, cells=100, t_end=1e-3,
                       source_radius=0.02, probes=[0.1, 0.5])
    assert np.max(np.abs(r.pressure)) < 1e-6


def test_blast_decays_with_distance(gun):
    s = SoundSettings().resolved(gun.barrel.travel)
    from gun_sim.sound.synth import _physics
    phys = _physics(gun, s)
    peaks = phys.probes.max(axis=1)
    arrivals = [phys.t[np.argmax(p >= 0.5 * p.max())] for p in phys.probes]
    assert np.all(np.diff(peaks) < 0)
    assert np.all(np.diff(arrivals) > 0)
    # Close in, the front outruns sound (a shock); further out it tends to the speed of sound.
    r = phys.blast.radii
    speed_far = (r[-1] - r[-3]) / (arrivals[-1] - arrivals[-3])
    speed_near = (r[2] - r[0]) / (arrivals[2] - arrivals[0])
    assert speed_near > speed_far > 0.99 * s.sound_speed
    # Well-known order of magnitude for a full-power rifle: about 160-175 dB at 1 m.
    k = int(np.argmin(np.abs(r - 1.0)))
    level = 20 * math.log10(peaks[k] * r[k] / 20e-6)
    assert 160 < level < 178


def test_crack_geometry():
    traj = ballistic.fly(850.0, 9.7e-3, 7.82e-3, 1.225, 340.0, 300.0)
    assert np.all(np.diff(traj.v) <= 0)  # drag only slows it down
    # Behind the muzzle (the shooter) and well to the side: never inside the Mach cone.
    assert ballistic.crack(traj, (-0.8, 0.05, 0.0), 340.0, 101325.0, 7.82e-3, 28.6e-3) is None
    assert ballistic.crack(traj, (0.0, 10.0, 0.0), 340.0, 101325.0, 7.82e-3, 28.6e-3) is None
    # Downrange beside the path: heard before the muzzle blast, with Whitham's amplitude.
    cr = ballistic.crack(traj, (100.0, 3.0, 0.0), 340.0, 101325.0, 7.82e-3, 28.6e-3)
    assert cr is not None
    assert cr.time < math.hypot(100.0, 3.0) / 340.0
    m2 = cr.mach**2 - 1
    expected = 0.53 * 101325.0 * m2**0.125 * 7.82e-3 / (3.0**0.75 * 28.6e-3**0.25)
    assert cr.overpressure == pytest.approx(expected)
    assert 100e-6 < cr.duration < 400e-6


def test_subsonic_projectile_has_no_crack():
    traj = ballistic.fly(300.0, 15e-3, 9e-3, 1.225, 340.0, 200.0)
    assert ballistic.crack(traj, (100.0, 3.0, 0.0), 340.0, 101325.0, 9e-3, 15e-3) is None


def test_iso9613_absorption():
    # ISO 9613-1 table: 20 °C, 70 % RH, 101.325 kPa -> about 4.99 dB/km at 1 kHz, 22.9 dB/km at 4 kHz.
    a = propagation.absorption_db_per_m([1000.0, 4000.0], 293.15, 70.0, 101325.0)
    assert a[0] == pytest.approx(4.99e-3, rel=0.03)
    assert a[1] == pytest.approx(22.9e-3, rel=0.03)


def test_ground_reflection_limits():
    f = np.array([0.0, 100.0, 1000.0, 10000.0])
    hard = propagation.ground_reflection(f, 1e12, math.radians(10), 1.2)
    assert np.allclose(np.abs(hard), 1.0, atol=1e-3)
    soft = propagation.ground_reflection(f, 2e4, math.radians(10), 1.2)
    assert np.all(np.abs(soft[1:]) < 1.0)
    assert np.all(propagation.ground_reflection(f, None, 0.1, 1.2) == 0)


def test_minimum_phase_is_causal():
    nfft = 4096
    f = np.fft.rfftfreq(nfft, 1 / 48000)
    h = np.fft.irfft(propagation.minimum_phase(1 / (1 + (f / 2000) ** 2), nfft), nfft)
    assert np.sum(h[nfft // 2:] ** 2) < 1e-6 * np.sum(h**2)


def test_synthesize_listeners(gun, tmp_path):
    shooter = synthesize(gun, SoundSettings.from_dict({"preset": "shooter"}))
    assert len(shooter.left) == len(shooter.right) == len(shooter.pressure) == len(shooter.reference)
    assert np.all(np.isfinite(shooter.left)) and np.all(np.isfinite(shooter.right))
    assert 150 < shooter.stats["peak_db"] < 175
    assert shooter.stats["crack"] is None  # the shooter is behind the Mach cone

    bystander = synthesize(gun, SoundSettings.from_dict({"preset": "bystander"}))
    assert bystander.stats["peak_db"] < shooter.stats["peak_db"]
    # The preset faces the gun: sound from straight ahead reaches both ears alike.
    assert bystander.stats["peak_left_db"] == pytest.approx(bystander.stats["peak_right_db"], abs=0.1)
    # Looking downrange from the shooter's right, the gun is on the left.
    looking = synthesize(gun, SoundSettings.from_dict({"preset": "bystander", "facing": 0.0}))
    assert looking.stats["peak_left_db"] > looking.stats["peak_right_db"] + 3

    downrange = synthesize(gun, SoundSettings.from_dict({"preset": "downrange"}))
    names = [e["name"] for e in downrange.events]
    assert names[0].startswith("supersonic crack")  # the crack beats the muzzle blast
    assert any(n.startswith("muzzle blast") for n in names)

    path = tmp_path / "shot.wav"
    write_wav(shooter, path)
    assert path.stat().st_size > 44


def test_blast_is_louder_ahead_of_the_muzzle(gun):
    front = synthesize(gun, SoundSettings(distance=5.0, angle=30.0, ground="none", facing=180.0))
    back = synthesize(gun, SoundSettings(distance=5.0, angle=150.0, ground="none", facing=0.0))
    side = synthesize(gun, SoundSettings(distance=5.0, angle=90.0, ground="none", facing=-90.0))

    def blast_db(snd):
        return max(e["peak_db"] for e in snd.events if e["name"].startswith("muzzle blast"))

    assert blast_db(front) > blast_db(side) > blast_db(back)


def test_sound_settings_validation():
    with pytest.raises(ValueError, match="unknown sound settings"):
        SoundSettings.from_dict({"colour": 1})
    with pytest.raises(ValueError, match="unknown ground"):
        SoundSettings.from_dict({"ground": "lava"})
    s = SoundSettings.from_dict({"preset": "bystander", "distance": 20.0})
    assert s.distance == 20.0 and s.angle == 90.0


def test_stems_partition_the_mix(gun):
    snd = synthesize(gun, SoundSettings.from_dict({"preset": "downrange"}))
    assert snd.stems
    blasts = [m for m in snd.stems if m["kind"] == "blast"]
    assert len(blasts) == 1 and blasts[0]["reference"] is not None
    assert len(blasts[0]["reference"]) == len(blasts[0]["left"])
    assert all(m["reference"] is None for m in snd.stems if m["kind"] != "blast")
    end = snd.start_time + len(snd.left) / snd.sample_rate
    assert all(snd.start_time - 1e-9 <= m["time"] <= end for m in snd.stems)
    assert len({m["name"] for m in snd.stems}) == len(snd.stems)
    total = np.zeros(len(snd.left))
    for m in snd.stems:
        i = int(round((m["time"] - snd.start_time) * snd.sample_rate))
        total[i:i + len(m["left"])] += m["left"]
    assert np.max(np.abs(total - snd.left)) < 1e-3 * np.max(np.abs(snd.left))


def test_echo_feeds(gun):
    """The echo references follow the blast's directivity; the crack source describes a supersonic flight."""
    snd = synthesize(gun, SoundSettings.from_dict({"preset": "shooter"}))
    peaks = {k: np.max(np.abs(v)) for k, v in snd.references.items()}
    assert peaks["front"] > 1.5 * peaks["side"]
    assert peaks["side"] > 1.3 * peaks["rear"]
    assert np.array_equal(snd.reference, snd.references["side"])
    blast = next(m for m in snd.stems if m["kind"] == "blast")
    assert set(blast["references"]) == {"front", "side", "rear"}
    src = snd.crack_source
    assert src is not None
    assert src["mach"][0] > src["mach"][-1] > 1.0
    assert np.all(np.diff(src["x"]) > 0) and np.all(np.diff(src["t"]) > 0)
    # Whitham at 100 m from a rifle bullet: some tens of pascals.
    assert 5 < src["kp"][0] / 100**0.75 < 100
    assert snd.stats["listener"][0] < 0  # the shooter's ear is behind the muzzle


def test_suppressor_bare_peak_and_ring():
    sup = Gun.load(RIFLE.parent / "example_suppressed.toml")
    snd = synthesize(sup, SoundSettings.from_dict({"preset": "shooter"}))
    peak = max(np.max(np.abs(snd.left)), np.max(np.abs(snd.right)))
    assert snd.stats["bare_peak"] > 3 * peak           # the can takes well over 10 dB off
    kinds = {m["name"]: m["kind"] for m in snd.stems}
    assert kinds["suppressor ring"] == "device"
    ring = next(m for m in snd.stems if m["name"] == "suppressor ring")
    assert 15 < 20 * math.log10(peak / ring["peak"]) < 45
    plain = synthesize(Gun.load(RIFLE), SoundSettings.from_dict({"preset": "shooter"}))
    assert plain.stats["bare_peak"] is None
    assert all(m["name"] != "suppressor ring" for m in plain.stems)
