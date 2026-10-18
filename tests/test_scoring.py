"""Tests for scoring logic."""
from datetime import date

import pytest

from riskreg.config import ConfigError, load_config, validate_config
from riskreg.scoring import (calculate_score, get_rating, get_rating_color,
                             is_outside_appetite, is_review_overdue,
                             risk_reduction_pct)


@pytest.fixture(scope="module")
def cfg():
    return load_config()


@pytest.mark.parametrize("score,rating", [
    (1, "Low"), (4, "Low"), (5, "Medium"), (9, "Medium"),
    (10, "High"), (15, "High"), (16, "Critical"), (25, "Critical")])
def test_rating_boundaries(cfg, score, rating):
    assert get_rating(score, cfg) == rating


def test_calculate_score():
    assert calculate_score(3, 4) == 12


@pytest.mark.parametrize("l,i", [(0, 3), (6, 1), (3, 0), (1, 9), (-1, 2)])
def test_invalid_inputs_raise(l, i):
    with pytest.raises(ValueError):
        calculate_score(l, i)


def test_non_int_raises():
    with pytest.raises(TypeError):
        calculate_score(2.5, 3)  # type: ignore[arg-type]


def test_out_of_band_score(cfg):
    with pytest.raises(ValueError):
        get_rating(26, cfg)


def test_colors(cfg):
    assert get_rating_color("Critical", cfg).startswith("#")
    with pytest.raises(ValueError):
        get_rating_color("Nope", cfg)


def test_appetite_default_and_override(cfg):
    assert not is_outside_appetite(9, "Operational", cfg)
    assert is_outside_appetite(10, "Operational", cfg)
    # Cyber Security override is 6 in the shipped config
    assert is_outside_appetite(8, "Cyber Security", cfg)
    assert not is_outside_appetite(6, "Cyber Security", cfg)


def test_risk_reduction():
    assert risk_reduction_pct(20, 5) == 75.0
    assert risk_reduction_pct(10, 10) == 0.0
    assert risk_reduction_pct(0, 0) == 0.0


def test_review_overdue():
    today = date(2025, 6, 1)
    assert is_review_overdue("2025-05-31", today)
    assert not is_review_overdue("2025-06-01", today)
    assert not is_review_overdue(None, today)


def test_config_validation_errors(cfg):
    with pytest.raises(ConfigError):
        validate_config({})
    bad = dict(cfg)
    bad["rating_bands"] = [{"name": "X", "min": 1, "max": 10, "color": "#000"}]
    with pytest.raises(ConfigError):
        validate_config(bad)
