"""Aggregations for the dashboard (pure functions over pandas DataFrames)."""
from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from .config import Config
from .scoring import is_outside_appetite, is_review_overdue



def _rating_order(config: Config) -> list[str]:
    return [str(b["name"]) for b in sorted(config["rating_bands"], key=lambda b: b["min"])]


def heatmap_matrix(df: pd.DataFrame, config: Config, score_type: str = "residual"):
    """Build a 5x5 cell matrix for a heatmap.

    Returns ``(counts, details, matrix)`` where ``counts[l][i]`` is the number
    of risks at likelihood ``l`` and impact ``i`` (1-based), ``details`` maps
    ``(likelihood, impact) -> list[dict]`` of risks in the cell, and ``matrix``
    is the 5x5 colour index (one per rating band) for each cell.
    """
    l_key = f"{score_type}_likelihood"
    i_key = f"{score_type}_impact"
    order = _rating_order(config)
    rating_index = {name: idx for idx, name in enumerate(order)}
    counts = [[0 for _ in range(6)] for _ in range(6)]
    details: dict[tuple[int, int], list[dict[str, Any]]] = {}
    cell_rating: dict[tuple[int, int], int] = {}
    for _, row in df.iterrows():
        l = int(row[l_key])
        i = int(row[i_key])
        counts[l][i] += 1
        details.setdefault((l, i), []).append(
            {"risk_id": str(row["risk_id"]), "title": str(row["title"]),
             "score": int(row[f"{score_type}_score"])})
        cell_rating[(l, i)] = rating_index[str(row[f"{score_type}_rating"])]
    matrix = [[cell_rating.get((l, i)) for i in range(1, 6)] for l in range(1, 6)]
    return counts, details, matrix

def category_breakdown(df: pd.DataFrame, config: Config) -> pd.DataFrame:
    """Risk counts by category stacked by residual rating (includes all bands)."""
    order = _rating_order(config)
    tmp = df.copy()
    tmp["residual_rating"] = pd.Categorical(
        tmp["residual_rating"], categories=order, ordered=True)
    tbl = (tmp.groupby(["category", "residual_rating"])
             .size().unstack(fill_value=0))
    for band in order:
        if band not in tbl.columns:
            tbl[band] = 0
    return tbl[order].reset_index().sort_values("category")


def outside_appetite_table(df: pd.DataFrame, config: Config) -> pd.DataFrame:
    """Risks whose residual score exceeds appetite, with the gap."""
    from .scoring import get_appetite_threshold

    rows = []
    for _, row in df.iterrows():
        score = int(row["residual_score"])
        if is_outside_appetite(score, row["category"], config):
            threshold = int(get_appetite_threshold(row["category"], config))
            rows.append({
                "risk_id": row["risk_id"], "title": row["title"],
                "category": row["category"], "owner": row["owner"],
                "residual_score": score, "residual_rating": row["residual_rating"],
                "appetite_threshold": threshold, "gap": score - threshold,
            })
    if not rows:
        return pd.DataFrame(columns=["risk_id", "title", "category", "owner",
                                     "residual_score", "residual_rating",
                                     "appetite_threshold", "gap"])
    return pd.DataFrame(rows).sort_values("gap", ascending=False)


def overdue_reviews(df: pd.DataFrame, today: date) -> pd.DataFrame:
    """Risks whose next review date is strictly before ``today``."""
    rows = []
    for _, row in df.iterrows():
        if is_review_overdue(row["next_review_date"], today):
            rows.append({
                "risk_id": row["risk_id"], "title": row["title"],
                "category": row["category"], "owner": row["owner"],
                "residual_score": int(row["residual_score"]),
                "residual_rating": row["residual_rating"],
                "next_review_date": row["next_review_date"],
            })
    if not rows:
        return pd.DataFrame(columns=["risk_id", "title", "category", "owner",
                                     "residual_score", "residual_rating",
                                     "next_review_date"])
    return pd.DataFrame(rows)


def snapshot_trends(snapshots: pd.DataFrame, config: Config):
    """Per-snapshot rating counts and average residual score."""
    order = _rating_order(config)
    snapshots = snapshots.copy()
    snapshots["residual_rating"] = pd.Categorical(
        snapshots["residual_rating"], categories=order, ordered=True)
    counts = (snapshots.groupby(["snapshot_date", "residual_rating"])
              .size().unstack(fill_value=0))
    for band in order:
        if band not in counts.columns:
            counts[band] = 0
    counts = counts[order].reset_index()
    avg = (snapshots.groupby("snapshot_date")["residual_score"]
           .mean().rename("avg_residual_score").reset_index())
    return counts.merge(avg, on="snapshot_date")


def risk_movement(snapshots: pd.DataFrame) -> pd.DataFrame:
    """Risks whose residual rating changed between the last two snapshots."""
    if snapshots.empty:
        return pd.DataFrame()
    dates = sorted(snapshots["snapshot_date"].unique())
    if len(dates) < 2:
        return pd.DataFrame()
    recent, previous = dates[-1], dates[-2]
    cur = snapshots[snapshots["snapshot_date"] == recent].set_index("risk_id")
    prev = snapshots[snapshots["snapshot_date"] == previous].set_index("risk_id")
    common = cur.index.intersection(prev.index)
    rows = []
    for rid in common:
        c, p = cur.loc[rid], prev.loc[rid]
        if c["residual_rating"] != p["residual_rating"] or \
                c["residual_score"] != p["residual_score"]:
            rows.append({
                "risk_id": rid,
                "previous_date": previous,
                "previous_score": int(p["residual_score"]),
                "previous_rating": p["residual_rating"],
                "recent_date": recent,
                "recent_score": int(c["residual_score"]),
                "recent_rating": c["residual_rating"],
                "status": c["status"],
                "direction": "Up" if c["residual_score"] > p["residual_score"] else
                             ("Down" if c["residual_score"] < p["residual_score"] else "Unchanged"),
            })
    return pd.DataFrame(rows)

