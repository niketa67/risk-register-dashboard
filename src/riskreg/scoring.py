"""Pure scoring and rating functions."""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

Config = dict[str, Any]


def _validate_level(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if not 1 <= value <= 5:
        raise ValueError(f"{name} must be between 1 and 5, got {value}")


def calculate_score(likelihood: int, impact: int) -> int:
    """Return likelihood x impact after validating both are in 1..5."""
    _validate_level(likelihood, "likelihood")
    _validate_level(impact, "impact")
    return likelihood * impact


def get_rating(score: int, config: Config) -> str:
    """Map a score to its rating band name using the configured bands."""
    for band in config["rating_bands"]:
        if band["min"] <= score <= band["max"]:
            return str(band["name"])
    raise ValueError(f"Score {score} is outside all rating bands")


def get_rating_color(rating: str, config: Config) -> str:
    """Return the hex color configured for a rating name."""
    for band in config["rating_bands"]:
        if band["name"] == rating:
            return str(band["color"])
    raise ValueError(f"Unknown rating: {rating}")


def get_appetite_threshold(category: Optional[str], config: Config) -> int:
    """Return the maximum acceptable residual score for a category."""
    appetite = config["risk_appetite"]
    overrides = appetite.get("category_overrides") or {}
    if category in overrides:
        return int(overrides[category])
    return int(appetite["max_residual_score"])


def is_outside_appetite(residual_score: int, category: Optional[str],
                        config: Config) -> bool:
    """True when the residual score exceeds the category's appetite."""
    return residual_score > get_appetite_threshold(category, config)


def risk_reduction_pct(inherent_score: int, residual_score: int) -> float:
    """Percentage reduction from inherent to residual score (0 if no inherent)."""
    if inherent_score <= 0:
        return 0.0
    return round((inherent_score - residual_score) / inherent_score * 100, 1)


def is_review_overdue(next_review_date: Optional[date | str],
                      today: date) -> bool:
    """True when a review date exists and is strictly before ``today``."""
    if not next_review_date:
        return False
    if isinstance(next_review_date, str):
        next_review_date = date.fromisoformat(next_review_date)
    return next_review_date < today
