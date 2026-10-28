"""Smoke tests for the camera-free parts of flowtrack."""
import pytest

from flowtrack.control import Rule, scale
from flowtrack.source import DemoSource
from flowtrack.tracker import Calibration, OneEuro, Tracker


def test_scale_maps_and_clamps():
    assert scale(0.5, [0, 1], [0, 10]) == 5
    assert scale(2.0, [0, 1], [0, 10]) == 10
    assert scale(0.25, [0, 1], [0, 1], invert=True) == 0.75


def test_one_euro_converges_to_constant_input():
    f = OneEuro(min_cutoff=1.0, beta=0.0)
    f(0.0, 0.0)
    out = 0.0
    for i in range(1, 200):
        out = f(1.0, i / 60)
    assert out == pytest.approx(1.0, abs=1e-3)


def test_rule_fires_once_after_hold():
    r = Rule({"when": "speed > 1.0", "for": 0.2, "do": {"effect": "next"}})
    assert not r.step({"present": True, "speed": 2.0}, 0.0)
    assert r.step({"present": True, "speed": 2.0}, 0.3)
    assert not r.step({"present": True, "speed": 2.0}, 0.4)
    assert not r.step({"present": True, "speed": 0.5}, 0.5)


def test_rule_rejects_unknown_condition():
    with pytest.raises(ValueError):
        Rule({"when": "speed ~ 1", "do": {}}).condition({"present": True, "speed": 1})


def test_tracker_finds_demo_points():
    src = DemoSource(640, 360, 60)
    tracker = Tracker({"detect": "brightness", "threshold": 200}, Calibration())
    found = 0
    for i in range(60):
        f = tracker.update(src.read(), now=i / 60)
        if f["present"]:
            found += 1
            assert 0 <= f["blobs"][0][0] <= 1 and 0 <= f["blobs"][0][1] <= 1
    assert found > 50
