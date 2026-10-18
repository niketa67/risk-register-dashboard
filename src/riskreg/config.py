"""Load and validate the YAML risk configuration."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "risk_config.yaml"

Config = dict[str, Any]


REQUIRED_KEYS = (
    "likelihood_scale",
    "impact_scale",
    "rating_bands",
    "risk_appetite",
    "categories",
    "treatment_options",
    "status_values",
)


class ConfigError(ValueError):
    """Raised when the configuration file is missing or invalid."""


def validate_config(cfg: dict[str, Any]) -> None:
    """Validate structure of a loaded config; raise ConfigError on problems."""
    missing = [k for k in REQUIRED_KEYS if k not in cfg]
    if missing:
        raise ConfigError(f"Missing config keys: {', '.join(missing)}")
    for scale in ("likelihood_scale", "impact_scale"):
        if sorted(cfg[scale]) != [1, 2, 3, 4, 5]:
            raise ConfigError(f"{scale} must define levels 1 to 5")
    bands = cfg["rating_bands"]
    if not bands:
        raise ConfigError("rating_bands must not be empty")
    expected = 1
    for band in sorted(bands, key=lambda b: b["min"]):
        for key in ("name", "min", "max", "color"):
            if key not in band:
                raise ConfigError(f"rating band missing '{key}'")
        if band["min"] != expected or band["max"] < band["min"]:
            raise ConfigError("rating bands must be contiguous starting at 1")
        expected = band["max"] + 1
    if expected - 1 != 25:
        raise ConfigError("rating bands must cover scores 1 to 25")
    appetite = cfg["risk_appetite"]
    if "max_residual_score" not in appetite:
        raise ConfigError("risk_appetite.max_residual_score is required")
    overrides = appetite.get("category_overrides") or {}
    unknown = [c for c in overrides if c not in cfg["categories"]]
    if unknown:
        raise ConfigError(f"Appetite overrides for unknown categories: {unknown}")


def load_config(path: Path | str | None = None) -> dict[str, Any]:
    """Load, validate and return the risk configuration dictionary."""
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not cfg_path.exists():
        raise ConfigError(f"Config file not found: {cfg_path}")
    with cfg_path.open("r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    if not isinstance(cfg, dict):
        raise ConfigError("Config file must contain a mapping")
    validate_config(cfg)
    cfg.setdefault("action_status_values",
                   ["Not Started", "In Progress", "Completed", "Overdue"])
    cfg["risk_appetite"].setdefault("category_overrides", {})
    cfg["risk_appetite"]["category_overrides"] = (
        cfg["risk_appetite"]["category_overrides"] or {})
    logger.debug("Loaded config from %s", cfg_path)
    return cfg
