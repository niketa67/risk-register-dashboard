"""Tests for analytics and heatmap matrix logic."""
import pandas as pd

from riskreg.analytics import (category_breakdown, heatmap_matrix,
                               outside_appetite_table, overdue_reviews,
                               risk_movement, snapshot_trends)
from riskreg.scoring import calculate_score, get_rating


def _make_cfg():
    return {
        "likelihood_scale": {lvl: {"label": "L", "description": "d"}
                             for lvl in range(1, 6)},
        "impact_scale": {lvl: {"label": "I", "financial": "f",
                               "operational": "o", "regulatory": "r",
                               "reputational": "p"} for lvl in range(1, 6)},
        "rating_bands": [
            {"name": "Low", "min": 1, "max": 4, "color": "#2e9e4f"},
            {"name": "Medium", "min": 5, "max": 9, "color": "#f2c230"},
            {"name": "High", "min": 10, "max": 15, "color": "#f08a24"},
            {"name": "Critical", "min": 16, "max": 25, "color": "#d62f2f"},
        ],
        "risk_appetite": {"max_residual_score": 9,
                          "category_overrides": {"Cyber Security": 6}},
        "categories": ["Cyber Security", "Operational"],
        "treatment_options": ["Mitigate"],
        "status_values": ["Identified"],
    }


def _risk(rid, category, l, i, rating, status="Identified", **over):
    score = calculate_score(l, i)
    return {"risk_id": rid, "title": f"Risk {rid}", "category": category,
            "owner": "O", "department": "D", "inherent_likelihood": l,
            "inherent_impact": i, "inherent_score": score,
            "inherent_rating": rating, "residual_likelihood": l,
            "residual_impact": i, "residual_score": score,
            "residual_rating": rating, "treatment": "Mitigate",
            "status": status, "existing_controls": "",
            "identified_date": "2025-01-01", "next_review_date": "2025-12-01",
            "last_updated": "2025-01-01", "is_deleted": 0, **over}


def test_heatmap_matrix_counts(cfg=None):
    cfg = _make_cfg()
    df = pd.DataFrame([
        _risk("RSK-1", "Cyber Security", 3, 4, get_rating(12, cfg)),
        _risk("RSK-2", "Cyber Security", 3, 4, get_rating(12, cfg)),
        _risk("RSK-3", "Operational", 1, 1, get_rating(1, cfg)),
    ])
    counts, details, matrix = heatmap_matrix(df, cfg, "residual")
    assert counts[3][4] == 2
    assert counts[1][1] == 1
    assert len(details[(3, 4)]) == 2
    assert {d["risk_id"] for d in details[(3, 4)]} == {"RSK-1", "RSK-2"}
    # rating index: High=2 at (3,4)->score12, Low=0 at (1,1)->score1
    assert matrix[2][3] == 2  # likelihood 3 (idx2), impact 4 (idx3)
    assert matrix[0][0] == 0


def test_category_breakdown(cfg=None):
    cfg = _make_cfg()
    df = pd.DataFrame([
        _risk("RSK-1", "Cyber Security", 3, 4, get_rating(12, cfg)),
        _risk("RSK-2", "Cyber Security", 1, 1, get_rating(1, cfg)),
        _risk("RSK-3", "Operational", 3, 4, get_rating(12, cfg)),
    ])
    tbl = category_breakdown(df, cfg)
    cyber = tbl[tbl["category"] == "Cyber Security"].iloc[0]
    assert int(cyber["High"]) == 1 and int(cyber["Low"]) == 1
    assert set(tbl["category"]) == {"Cyber Security", "Operational"}


def test_outside_appetite_table(cfg=None):
    cfg = _make_cfg()
    df = pd.DataFrame([
        _risk("RSK-1", "Cyber Security", 3, 4, get_rating(12, cfg)),
        _risk("RSK-2", "Operational", 1, 1, get_rating(1, cfg)),
    ])
    tbl = outside_appetite_table(df, cfg)
    assert len(tbl) == 1
    assert tbl.iloc[0]["risk_id"] == "RSK-1"
    assert tbl.iloc[0]["gap"] == 12 - 6


def test_overdue_reviews():
    cfg = _make_cfg()
    df = pd.DataFrame([
        _risk("RSK-1", "Cyber Security", 3, 4, get_rating(12, cfg),
              next_review_date="2025-01-01"),
        _risk("RSK-2", "Cyber Security", 1, 1, get_rating(1, cfg),
              next_review_date="2026-01-01"),
    ])
    import datetime as dt
    tbl = overdue_reviews(df, dt.date(2025, 6, 1))
    assert len(tbl) == 1 and tbl.iloc[0]["risk_id"] == "RSK-1"


def test_snapshot_trends_and_movement(cfg=None):
    cfg = _make_cfg()
    snaps = pd.DataFrame([
        {"snapshot_date": "2025-03-01", "risk_id": "RSK-1",
         "residual_score": 8, "residual_rating": "Medium", "status": "Assessed"},
        {"snapshot_date": "2025-03-01", "risk_id": "RSK-2",
         "residual_score": 4, "residual_rating": "Low", "status": "Assessed"},
        {"snapshot_date": "2025-06-01", "risk_id": "RSK-1",
         "residual_score": 12, "residual_rating": "High", "status": "Assessed"},
        {"snapshot_date": "2025-06-01", "risk_id": "RSK-2",
         "residual_score": 4, "residual_rating": "Low", "status": "Assessed"},
    ])
    trend = snapshot_trends(snaps, cfg)
    assert len(trend) == 2
    june = trend[trend["snapshot_date"] == "2025-06-01"].iloc[0]
    assert int(june["High"]) == 1 and float(june["avg_residual_score"]) == 8.0
    mov = risk_movement(snaps)
    assert len(mov) == 1
    assert mov.iloc[0]["risk_id"] == "RSK-1"
    assert mov.iloc[0]["direction"] == "Up"
