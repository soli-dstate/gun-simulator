"""External ballistics: vacuum parabola, drag, zeroing, published .308 numbers, wind."""

import math

import numpy as np
import pytest

from gun_sim import exterior as ex
from gun_sim.config import Gun

FPS = 0.3048
YD = 0.9144
GRAIN = 6.479891e-5
BC_308 = 0.243 * ex.LB_IN2  # 175 gr Sierra MatchKing, G7
M_308 = 175 * GRAIN
V_308 = 2600 * FPS


def match_bullet(**kw):
    args = dict(drag_model="G7", zero_range=100 * YD, sight_height=0.0508, max_range=1000 * YD)
    args.update(kw)
    return ex.fly(V_308, BC_308, M_308, **args)


def test_vacuum_matches_parabola():
    v0, angle = 800.0, math.radians(2.0)
    traj = ex.fly(v0, math.inf, 0.01, launch_angle=angle, sight_height=0.0, max_range=500.0, dt=1e-3)
    x = traj.x
    # No drag: x = v0 cos(a) t, y = v0 sin(a) t - g t^2 / 2 (to RK4 round-off).
    assert np.allclose(x, v0 * math.cos(angle) * traj.time, rtol=1e-9)
    assert np.allclose(traj.y, v0 * math.sin(angle) * traj.time - 0.5 * ex.G * traj.time**2, atol=1e-6)
    assert np.allclose(traj.velocity[0], v0)


def test_drag_only_decelerates():
    traj = match_bullet()
    assert np.all(np.diff(traj.velocity[:50]) < 0)  # flat start, gravity not yet adding speed
    assert traj.velocity[-1] < V_308
    assert np.all(np.diff(traj.energy) <= 1e-9)
    assert np.all(np.diff(traj.x) > 0)


def test_zero_crosses_line_of_sight():
    for zero in (50.0, 100 * YD, 300.0):
        traj = match_bullet(zero_range=zero)
        assert abs(traj.at(zero)["drop"]) < 1e-4
        # Starts below the line of sight (sight height), rises through it, then falls below again.
        assert traj.y[0] == pytest.approx(-0.0508)
        assert traj.at(1.0)["drop"] < 0 and traj.at(zero * 3)["drop"] < 0
        assert traj.y.max() > 0


def test_308_match_bullet_1000_yards():
    traj = match_bullet()
    r = traj.at(1000 * YD)
    # Published solutions for a 175 gr SMK at 2600 fps (100 yd zero): drop about 40 MOA
    # (~420 in), roughly 1090 fps and 1.8 s time of flight at 1000 yd.
    assert 36 <= -r["drop_moa"] <= 44
    assert 380 <= -r["drop"] / 0.0254 <= 460
    assert r["velocity"] / FPS == pytest.approx(1090, rel=0.08)
    assert r["time"] == pytest.approx(1.8, rel=0.08)


def test_higher_bc_drops_less_and_keeps_speed():
    low = ex.fly(V_308, 0.2 * ex.LB_IN2, M_308, zero_range=100.0, max_range=800.0)
    high = ex.fly(V_308, 0.3 * ex.LB_IN2, M_308, zero_range=100.0, max_range=800.0)
    assert high.at(800.0)["drop"] > low.at(800.0)["drop"]
    assert high.at(800.0)["velocity"] > low.at(800.0)["velocity"]


def test_g1_and_g7_tables_sane():
    for model in ("G1", "G7"):
        ms, cs = ex.DRAG_TABLES[model]
        assert len(ms) > 60 and ms == sorted(ms)
        peak = ms[int(np.argmax(cs))]
        assert 1.0 <= peak <= 1.5  # drag peaks in the transonic/low supersonic range
    assert ex.drag_coefficient(1.0, "G7") == pytest.approx(0.3803)
    assert ex.drag_coefficient(10.0, "G1") == ex.drag_coefficient(5.0, "G1")


def test_wind_along_the_line_of_fire():
    calm = match_bullet().at(800.0)
    head = match_bullet(headwind=10.0).at(800.0)
    tail = match_bullet(headwind=-10.0).at(800.0)
    # Headwind adds drag (more drop, slower, longer flight); tailwind does the reverse.
    assert head["drop"] < calm["drop"] < tail["drop"]
    assert head["velocity"] < calm["velocity"] < tail["velocity"]
    assert head["time"] > calm["time"] > tail["time"]
    assert abs(calm["windage"]) < 1e-9


def test_crosswind_drift_sign_and_growth():
    right = match_bullet(crosswind=5.0)
    left = match_bullet(crosswind=-5.0)
    # Wind from the left pushes the bullet right (positive), and drift grows faster than range.
    assert right.at(500.0)["windage"] > 0 > left.at(500.0)["windage"]
    assert right.at(500.0)["windage"] == pytest.approx(-left.at(500.0)["windage"], rel=1e-6)
    assert right.at(800.0)["windage"] > 2 * right.at(400.0)["windage"]
    # Drift is a fraction of the wind's displacement over the flight time (lag rule).
    r = right.at(800.0)
    assert 0 < r["windage"] < 5.0 * r["time"]


def test_table_rows_and_stop_conditions():
    traj = match_bullet(max_range=500.0)
    rows = traj.table(100.0)
    assert [r["range"] for r in rows] == [100, 200, 300, 400, 500]
    assert rows[0]["drop_mil"] == pytest.approx(rows[0]["drop"] / 100 * 1000, rel=1e-3)
    assert traj.stop_reason == "max range"
    slow = ex.fly(300.0, 0.1 * ex.LB_IN2, 0.01, zero_range=None, launch_angle=0.0, max_range=5000.0, min_velocity=100.0)
    assert slow.stop_reason == "minimum velocity" and slow.x[-1] < 5000.0
    timed = ex.fly(300.0, 1.0 * ex.LB_IN2, 0.01, zero_range=None, launch_angle=0.0, max_time=0.5)
    assert timed.stop_reason == "max time" and timed.time[-1] >= 0.5


def test_atmosphere():
    std = ex.Atmosphere()
    assert std.density == pytest.approx(1.225, abs=0.002)
    assert std.speed_of_sound == pytest.approx(340.3, abs=0.2)
    assert ex.Atmosphere(humidity=100).density < std.density            # moist air is lighter
    assert ex.Atmosphere(humidity=100).speed_of_sound > std.speed_of_sound
    high = ex.Atmosphere.standard(2000.0)
    assert high.density == pytest.approx(1.007, abs=0.005)               # ISA at 2000 m
    thin = ex.fly(V_308, BC_308, M_308, zero_range=100.0, max_range=800.0, atmosphere=high)
    sea = ex.fly(V_308, BC_308, M_308, zero_range=100.0, max_range=800.0)
    assert thin.at(800.0)["drop"] > sea.at(800.0)["drop"]               # thinner air, less drop


def test_bc_estimate_from_shape():
    gun = Gun.load("configs/example_rifle.toml")
    p = gun.projectile
    bc = ex.ballistic_coefficient(gun)
    sd = p.mass / gun.barrel.bore_diameter**2
    assert 0.8 * sd < bc < 1.25 * sd  # form factor between ~0.8 and 1.25
    i7 = ex.g7_form_factor(p.length, p.ogive_length, p.meplat_diameter, p.boat_tail_length, gun.barrel.bore_diameter)
    d = gun.barrel.bore_diameter
    flat = ex.g7_form_factor(p.length, p.ogive_length, p.meplat_diameter, 0.0, d)
    blunt = ex.g7_form_factor(p.length, 0.5 * d, 0.5 * d, p.boat_tail_length, d)
    vld = ex.g7_form_factor(p.length, 3.2 * d, 0.05 * d, 0.6 * d, d)
    assert vld < i7 < flat < blunt
    assert 1.0 < i7 < 1.2
    p.ballistic_coefficient = 123.0
    assert ex.ballistic_coefficient(gun) == 123.0


def test_gun_trajectory_from_muzzle_velocity():
    gun = Gun.load("configs/example_rifle.toml")
    traj = ex.trajectory(gun, 830.0, zero_range=100.0, max_range=600.0)
    assert traj.drag_model == "G7" and abs(traj.at(100.0)["drop"]) < 1e-4
    assert traj.at(600.0)["drop"] < -0.5
    with pytest.raises(ValueError):
        ex.fly(830.0, BC_308, M_308, drag_model="G9")
