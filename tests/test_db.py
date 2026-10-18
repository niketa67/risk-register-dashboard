"""Tests for the SQLite data layer."""
from datetime import date, timedelta

import pytest

from riskreg.config import load_config
from riskreg.db import RiskDB, ValidationError


@pytest.fixture()
def db(tmp_path):
    return RiskDB(tmp_path / "test.db", load_config())


def make_risk(**over):
    base = dict(title="Unpatched servers", category="Cyber Security",
                owner="CISO", department="Security",
                inherent_likelihood=4, inherent_impact=5,
                residual_likelihood=2, residual_impact=4,
                treatment="Mitigate", status="Assessed",
                existing_controls="Patch cycle",
                identified_date="2025-01-10", next_review_date="2025-07-01")
    base.update(over)
    return base


def test_create_and_read(db):
    rid = db.create_risk(make_risk(), "alice")
    assert rid == "RSK-001"
    r = db.get_risk(rid)
    assert r["inherent_score"] == 20 and r["inherent_rating"] == "Critical"
    assert r["residual_score"] == 8 and r["residual_rating"] == "Medium"
    assert db.create_risk(make_risk(title="Second")) == "RSK-002"
    assert len(db.list_risks()) == 2


def test_create_audit_entries(db):
    rid = db.create_risk(make_risk(), "alice")
    log = db.get_audit_log(rid)
    assert set(log["action"]) == {"CREATE"}
    assert (log["changed_by"] == "alice").all()
    assert "title" in set(log["field_changed"])


def test_update_audit_old_new(db):
    rid = db.create_risk(make_risk())
    changed = db.update_risk(rid, {"owner": "CTO", "residual_likelihood": 1},
                             "bob")
    assert "owner" in changed and "residual_score" in changed
    log = db.get_audit_log(rid)
    row = log[(log["field_changed"] == "owner") & (log["action"] == "UPDATE")]
    assert row.iloc[0]["old_value"] == "CISO"
    assert row.iloc[0]["new_value"] == "CTO"
    assert row.iloc[0]["changed_by"] == "bob"
    row = log[(log["field_changed"] == "residual_score")
              & (log["action"] == "UPDATE")]
    assert row.iloc[0]["old_value"] == "8" and row.iloc[0]["new_value"] == "4"
    assert db.update_risk(rid, {"owner": "CTO"}) == []


def test_soft_delete(db):
    rid = db.create_risk(make_risk())
    db.delete_risk(rid, "carol")
    assert db.get_risk(rid) is None
    assert db.get_risk(rid, include_deleted=True)["is_deleted"] == 1
    assert db.list_risks().empty
    assert len(db.list_risks(include_deleted=True)) == 1
    log = db.get_audit_log(rid)
    assert log.iloc[0]["action"] == "DELETE"


def test_residual_cannot_exceed_inherent(db):
    with pytest.raises(ValidationError):
        db.create_risk(make_risk(residual_likelihood=5, residual_impact=5,
                                 inherent_likelihood=2, inherent_impact=2))
    rid = db.create_risk(make_risk())
    with pytest.raises(ValidationError):
        db.update_risk(rid, {"residual_likelihood": 5, "residual_impact": 5})


@pytest.mark.parametrize("over", [
    {"title": " "}, {"owner": ""}, {"inherent_likelihood": 6},
    {"category": "Nope"}, {"identified_date": "not-a-date"},
    {"next_review_date": "2025-13-45"}])
def test_validation(db, over):
    with pytest.raises(ValidationError):
        db.create_risk(make_risk(**over))


def test_actions_and_overdue(db):
    rid = db.create_risk(make_risk())
    past = (date.today() - timedelta(days=5)).isoformat()
    a1 = db.create_action(rid, {"description": "Patch", "action_owner": "Ops",
                                "due_date": past, "status": "In Progress"})
    a2 = db.create_action(rid, {"description": "Scan", "action_owner": "Ops",
                                "due_date": "2999-01-01"})
    assert db.refresh_overdue_actions() == 1
    assert db.get_action(a1)["status"] == "Overdue"
    db.complete_action(a1)
    act = db.get_action(a1)
    assert act["status"] == "Completed" and act["completed_date"]
    assert db.refresh_overdue_actions() == 0
    assert db.get_action(a2)["status"] == "Not Started"
    with pytest.raises(ValidationError):
        db.create_action("RSK-999", {"description": "x", "action_owner": "y",
                                     "due_date": "2030-01-01"})


def test_snapshots(db):
    rid = db.create_risk(make_risk())
    db.create_risk(make_risk(title="Other"))
    assert db.take_snapshot("2025-03-01") == 2
    db.update_risk(rid, {"residual_likelihood": 1})
    db.take_snapshot("2025-04-01")
    db.take_snapshot("2025-04-01")  # same date replaces
    snaps = db.get_snapshots()
    assert len(snaps) == 4
    assert set(snaps["snapshot_date"]) == {"2025-03-01", "2025-04-01"}
    db.delete_risk(rid)
    assert db.take_snapshot("2025-05-01") == 1
