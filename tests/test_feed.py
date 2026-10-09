"""Magazines, belts, the feed angle and running dry (gun_sim/feed.py, through action.simulate)."""

import math
from pathlib import Path

import pytest

from gun_sim import action, feed, lumped
from gun_sim.config import Gun

CONFIGS = Path(__file__).resolve().parents[1] / "configs"


@pytest.fixture(scope="module")
def m4():
    gun = Gun.load(CONFIGS / "m4a1.toml")
    return gun, lumped.simulate(gun, blowdown_time=0.025)


def with_feed(gun, **kw):
    for k, v in kw.items():
        setattr(gun.feed, k, v)
    return gun


@pytest.fixture
def gun(m4):
    g, _ = m4
    saved = dict(vars(g.feed))
    yield g
    vars(g.feed).update(saved)


def test_full_magazine_cycles_and_counts(gun, m4):
    a = action.simulate(gun, m4[1], shots=3)
    assert a.status == "cycled" and a.shots == 3
    assert a.rounds == [30, 29, 28] and a.rounds_left == 27 and a.chambered
    strips = [e for e in a.events if e["name"] == "strips the next round"]
    assert [e["rounds"] for e in strips] == [29, 28, 27]
    assert a.feed.max() == pytest.approx(1.0)   # the spring lifted the top round all the way each time


def test_runs_dry_and_holds_the_bolt_open(gun, m4):
    a = action.simulate(gun, m4[1], shots=10, rounds=2)
    assert a.shots == 3 and a.rounds == [2, 1, 0]
    assert a.status == "empty, bolt held open" and a.held_open and not a.chambered
    assert not any("burst stopped" in w for w in a.warnings)
    assert a.bolt[-1] > 0.04                    # still back on the bolt catch
    with_feed(gun, hold_open=False)
    a = action.simulate(gun, m4[1], shots=10, rounds=0)
    assert a.status == "empty" and abs(a.bolt[-1]) < 1e-9
    assert any(e["name"] == "closes on an empty chamber" for e in a.events)


def test_feed_angle_window(gun):
    geo = feed.geometry(gun)
    # Aimed at the bore by default: the tip meets the axis.
    assert feed.check(geo)["jam"] is None and abs(feed.check(geo)["tip"]) < 1e-6
    for deg, jam in ((-10, "nosedive"), (0, None), (5, None), (25, "stub")):
        with_feed(gun, feed_angle=deg)
        assert feed.check(feed.geometry(gun))["jam"] == jam, deg
    # A steep ramp met squarely digs the nose in.
    with_feed(gun, feed_angle=0, ramp_angle=80)
    out = feed.check(feed.geometry(gun))
    assert out["jam"] == "nosedive" and "dug into the feed ramp" in out["detail"]


def test_jam_stops_the_bolt_and_the_burst(gun, m4):
    with_feed(gun, feed_angle=25)
    a = action.simulate(gun, m4[1], shots=5)
    assert a.status == "jammed: stub" and a.shots == 1 and a.jam["shot"] == 1
    jam = next(e for e in a.events if e["name"] == "jams")
    assert a.bolt[-1] == pytest.approx(a.jam["travel_at"]) and a.bolt[-1] > 0.03
    assert a.rounds_left == 29                  # the jammed round left the magazine
    assert jam["angle"] == pytest.approx(math.radians(25))


def test_weak_spring_lets_the_bolt_ride_over(gun, m4):
    with_feed(gun, spring_empty=1.0, spring_full=3.0)   # less than the stack weighs
    a = action.simulate(gun, m4[1], shots=3)
    assert a.status == "failed to feed" and a.shots == 1
    assert any("rode over the next round" in w for w in a.warnings)
    assert a.rounds_left == 30


def test_lift_needs_more_time_with_a_heavier_stack(gun):
    # The spring force per kilogram it lifts falls as rounds are added (preload dominates).
    assert feed.spring(gun, 30) / feed.stack_mass(gun, 30) < feed.spring(gun, 5) / feed.stack_mass(gun, 5)


def test_magazine_types_and_capacities(gun, m4):
    for kind, cap in feed.CAPACITY.items():
        if kind == "cylinder":
            continue   # a revolver's (tests/test_handguns.py)
        with_feed(gun, type=kind, capacity=None)
        a = action.simulate(gun, m4[1], shots=2)
        assert a.status == "cycled", kind
        assert a.capacity == cap and a.rounds == [cap, cap - 1]


def test_belt_hanging_weight_slows_the_carrier(gun, m4):
    with_feed(gun, type="belt", belt_hang=0.0)
    light = action.simulate(gun, m4[1], shots=1)
    with_feed(gun, belt_hang=1.5)
    heavy = action.simulate(gun, m4[1], shots=1)
    assert light.status == heavy.status == "cycled"
    assert heavy.cycle_time > light.cycle_time
    assert heavy.feed.max() == pytest.approx(1.0)   # the belt was drawn a whole link


def test_belt_short_stroke_misses_the_round(gun, m4):
    stroke = action.strokes(gun)["stroke"]
    with_feed(gun, type="belt", belt_cam_start=0.9 * stroke, belt_cam=0.5 * stroke)
    a = action.simulate(gun, m4[1], shots=2)
    assert a.status == "failed to feed"
    assert any("feed cam drew the belt" in w for w in a.warnings)


def test_round_mass_is_about_right(gun):
    assert 0.011 < feed.round_mass(gun) < 0.014     # M855: about 12.3 g


def test_feed_config_validation():
    base = Gun.load(CONFIGS / "m4a1.toml")
    from dataclasses import asdict
    for bad in ({"type": "clip"}, {"capacity": 0}, {"capacity": 2.5}, {"feed_angle": 60},
                {"spring_empty": 30.0, "spring_full": 10.0}, {"ramp_angle": 90}):
        data = asdict(base)
        data["feed"].update(bad)
        with pytest.raises(ValueError):
            Gun.from_dict(data)


def test_belt_fed_preset_cycles():
    gun = Gun.load(CONFIGS / "example_belt_fed.toml")
    a = action.simulate(gun, lumped.simulate(gun, blowdown_time=0.025), shots=3)
    assert a.status == "cycled" and a.rounds == [100, 99, 98]
