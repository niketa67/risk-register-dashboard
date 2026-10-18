"""Deterministic demo-data generator for the risk register."""
from __future__ import annotations

import datetime as _dt
import logging
import random
from pathlib import Path
from typing import Any

from .config import load_config
from .db import RiskDB
from .scoring import calculate_score, get_rating

logger = logging.getLogger(__name__)

RANDOM_SEED = 42
SNAPSHOT_DATES = [
    "2025-02-01", "2025-03-01", "2025-04-01", "2025-05-01", "2025-06-01",
]
TODAY = "2025-06-15"

OWNERS_BY_DEPT = {
    "Information Security": ["A. Rahman", "S. Patel", "D. Okafor"],
    "IT Infrastructure": ["M. Chen", "L. Novak", "J. Ribeiro"],
    "Third Party Risk": ["E. Kowalski", "R. Singh"],
    "Compliance": ["H. Dubois", "F. Al-Mansour"],
    "Operations": ["P. Osei", "G. Ivanov"],
    "Finance": ["C. Laurent", "T. Becker"],
    "Data Protection": ["N. Volkova", "B. Murphy"],
    "Business Continuity": ["S. Nakamura", "K. Adebayo"],
}
RISK_TEMPLATES: list[tuple] = [
    ("Unpatched critical vulnerabilities on internet-facing servers",
     "Cyber Security", "Information Security", 5, 5, 4, 5, "Mitigate",
     "In Treatment", "Monthly patch cycle; WAF rules in place",
     "2025-01-12", "2025-06-30"),
    ("Ransomware attack encrypting production systems",
     "Cyber Security", "Information Security", 4, 5, 4, 5, "Mitigate",
     "Assessed", "EDR agents; immutable backups; segmented flat network",
     "2025-01-20", "2025-05-15"),
    ("Phishing campaign compromising employee credentials",
     "Cyber Security", "Information Security", 4, 4, 3, 4, "Mitigate",
     "In Treatment", "Gmail/Exchange native filtering; annual awareness",
     "2025-02-03", "2025-07-01"),
    ("Zero-day exploit in externally facing web application",
     "Cyber Security", "Information Security", 3, 5, 2, 3, "Transfer",
     "Monitoring", "Cyber insurance policy; WAF; bug bounty programme",
     "2025-02-18", "2025-05-01"),
    ("Insider threat exfiltrating sensitive data",
     "Cyber Security", "Information Security", 2, 5, 2, 3, "Mitigate",
     "Assessed", "DLP rules; least-privilege file shares",
     "2025-03-05", "2025-06-01"),
    ("Single cloud provider dependency for payment processing",
     "Technology / IT Operations", "IT Infrastructure", 4, 5, 4, 5,
     "Accept", "In Treatment", "Multi-region within one provider; no exit plan",
     "2025-01-10", "2025-04-10"),
    ("Database cluster failure during peak trading",
     "Technology / IT Operations", "IT Infrastructure", 3, 5, 3, 4, "Mitigate",
     "In Treatment", "Auto-failover; quarterly drills",
     "2025-01-15", "2025-08-01"),
    ("Legacy mainframe reaching end of vendor support",
     "Technology / IT Operations", "IT Infrastructure", 4, 4, 3, 3, "Avoid",
     "Identified", "Annual support contract; spare parts stockpile",
     "2025-02-01", "2025-09-01"),
    ("Network outage affecting branch connectivity",
     "Technology / IT Operations", "IT Infrastructure", 3, 4, 2, 3, "Mitigate",
     "Assessed", "SD-WAN with 4G failover",
     "2025-02-10", "2025-05-20"),
    ("Backup failure resulting in data loss",
     "Technology / IT Operations", "IT Infrastructure", 3, 5, 1, 3, "Mitigate",
     "Monitoring", "Nightly backups; restore test every six months",
     "2025-02-22", "2025-04-01"),
    ("Key vendor suffers ransomware attack",
     "Third Party / Vendor", "Third Party Risk", 4, 5, 4, 5, "Mitigate",
     "In Treatment", "Vendor SOC2 reports; right-to-audit clause",
     "2025-01-08", "2025-03-15"),
    ("Outsourced call centre data breach",
     "Third Party / Vendor", "Third Party Risk", 3, 4, 2, 3, "Transfer",
     "Assessed", "Contractual indemnity; cyber insurance",
     "2025-01-25", "2025-06-15"),
    ("Critical software supplier going out of business",
     "Third Party / Vendor", "Third Party Risk", 2, 5, 2, 4, "Avoid",
     "Identified", "Source code escrow; exit strategy drafted",
     "2025-03-01", "2025-07-01"),
    ("Cloud SaaS provider SLA breach",
     "Third Party / Vendor", "Third Party Risk", 4, 3, 3, 2, "Accept",
     "Monitoring", "SLA credits; monthly service reviews",
     "2025-03-10", "2025-05-10"),
    ("Third party with privileged access to production",
     "Third Party / Vendor", "Third Party Risk", 3, 4, 2, 3, "Mitigate",
     "In Treatment", "PAM; vendor MFA",
     "2025-03-18", "2025-06-20"),
    ("Regulatory fine for late breach notification",
     "Regulatory / Compliance", "Compliance", 3, 5, 3, 4, "Mitigate",
     "In Treatment", "Breach response playbook; 72-hour notification SLA",
     "2025-01-05", "2025-02-28"),
    ("Failure to complete mandatory training",
     "Regulatory / Compliance", "Compliance", 4, 3, 3, 2, "Mitigate",
     "Assessed", "LMS tracking; manager escalation",
     "2025-01-14", "2025-05-31"),
    ("Missing statutory reporting deadline",
     "Regulatory / Compliance", "Compliance", 2, 4, 2, 3, "Mitigate",
     "Monitoring", "Regulatory calendar; owned by compliance team",
     "2025-02-05", "2025-04-30"),
    ("GDPR data subject access request backlog",
     "Regulatory / Compliance", "Compliance", 4, 4, 3, 4, "Mitigate",
     "In Treatment", "DSAR intake form; 30-day target",
     "2025-02-14", "2025-06-10"),
    ("Audit finding: inadequate access reviews",
     "Regulatory / Compliance", "Compliance", 3, 4, 2, 2, "Mitigate",
     "Monitoring", "Quarterly user access recertification",
     "2025-03-03", "2025-07-15"),
    ("Loss of key personnel in infrastructure team",
     "Operational", "IT Infrastructure", 3, 4, 3, 4, "Mitigate",
     "Assessed", "Cross-training programme; documentation wiki",
     "2025-01-09", "2025-05-01"),
    ("Failure of disaster recovery test",
     "Operational", "IT Infrastructure", 3, 5, 3, 4, "Mitigate",
     "In Treatment", "Annual DR test; runbooks version-controlled",
     "2025-01-19", "2025-03-31"),
    ("Building access control system failure",
     "Operational", "Operations", 2, 4, 1, 2, "Accept",
     "Monitoring", "Security guards; manual sign-in log",
     "2025-02-07", "2025-08-15"),
    ("Supply chain disruption of critical hardware",
     "Operational", "Operations", 4, 4, 3, 4, "Mitigate",
     "Assessed", "Dual sourcing for key components; safety stock",
     "2025-02-16", "2025-06-30"),
    ("Power failure in primary data centre",
     "Operational", "IT Infrastructure", 2, 5, 1, 3, "Mitigate",
     "Identified", "UPS and generator; N+1 cooling",
     "2025-03-02", "2025-09-30"),
    ("Fraudulent payment to vendor account",
     "Financial", "Finance", 3, 4, 2, 3, "Mitigate",
     "In Treatment", "Two-person authorisation; callback verification",
     "2025-01-11", "2025-05-15"),
    ("Currency volatility impacting margins",
     "Financial", "Finance", 4, 3, 3, 2, "Accept",
     "Monitoring", "Monthly FX hedging review",
     "2025-01-22", "2025-06-30"),
    ("Credit default by major customer",
     "Financial", "Finance", 2, 5, 1, 3, "Transfer",
     "Assessed", "Credit insurance; debt monitoring",
     "2025-02-04", "2025-07-31"),
    ("Investment portfolio loss beyond tolerance",
     "Financial", "Finance", 3, 4, 2, 2, "Accept",
     "Monitoring", "Investment policy; quarterly board review",
     "2025-02-20", "2025-08-01"),
    ("Liquidity shortfall in stress scenario",
     "Financial", "Finance", 2, 5, 1, 2, "Mitigate",
     "Identified", "Revolving credit facility; 13-week cash forecast",
     "2025-03-08", "2025-05-20"),
    ("Excessive privileged access in production database",
     "Data Privacy", "Data Protection", 4, 5, 4, 5, "Mitigate",
     "In Treatment", "PAM tool; quarterly access recertification",
     "2025-01-06", "2025-04-01"),
    ("Customer data exposed via misconfigured bucket",
     "Data Privacy", "Data Protection", 3, 5, 1, 3, "Mitigate",
     "Assessed", "S3 block public access; CloudTrail alerts",
     "2025-01-17", "2025-06-15"),
    ("Unauthorised sharing of personal data with vendor",
     "Data Privacy", "Data Protection", 3, 4, 2, 2, "Mitigate",
     "Monitoring", "Data processing agreements; vendor questionnaire",
     "2025-02-12", "2025-07-01"),
    ("Data retention beyond mandated period",
     "Data Privacy", "Data Protection", 4, 3, 3, 2, "Mitigate",
     "In Treatment", "Retention schedule; automated deletion jobs",
     "2025-02-24", "2025-04-15"),
    ("Biometric data breach",
     "Data Privacy", "Data Protection", 2, 5, 1, 2, "Transfer",
     "Assessed", "Encryption at rest; cyber insurance",
     "2025-03-14", "2025-08-15"),
    ("Prolonged loss of headquarters building",
     "Business Continuity", "Business Continuity", 2, 5, 1, 3, "Avoid",
     "Identified", "Alternate worksite agreement; remote work policy",
     "2025-01-03", "2025-09-01"),
    ("Pandemic-related staff absenteeism",
     "Business Continuity", "Business Continuity", 3, 4, 2, 3, "Mitigate",
     "Monitoring", "Minimum staffing levels; cross-training",
     "2025-01-13", "2025-06-01"),
    ("Critical IT outage during disaster declaration",
     "Business Continuity", "Business Continuity", 3, 5, 3, 4, "Mitigate",
     "In Treatment", "BCP invoked annually; crisis comms tree",
     "2025-02-09", "2025-05-10"),
    ("Loss of sole-source supplier for key product",
     "Business Continuity", "Business Continuity", 3, 5, 3, 4, "Avoid",
     "Identified", "Qualifying alternate supplier in progress",
     "2025-02-21", "2025-07-20"),
    ("Terrorism event near regional office",
     "Business Continuity", "Business Continuity", 1, 5, 1, 2, "Accept",
     "Monitoring", "Building security; evacuation drills",
     "2025-03-06", "2025-10-01"),
]

ACTION_TEMPLATES: list[tuple] = [
    ("Deploy critical patches to all internet-facing servers",
     "Information Security", -10, "In Progress", False),
    ("Validate offline backup restore for production databases",
     "IT Infrastructure", 45, "Not Started", False),
    ("Rewrite vendor security questionnaire and require attestation",
     "Third Party Risk", 60, "Not Started", False),
    ("Update breach notification playbook and run tabletop exercise",
     "Compliance", -20, "Overdue", False),
    ("Complete mandatory regulatory training for all staff",
     "Compliance", 30, "In Progress", False),
    ("Implement privileged access management for database admins",
     "Data Protection", -5, "Overdue", False),
    ("Disaster recovery full-scale test and document results",
     "IT Infrastructure", 90, "Not Started", False),
    ("Identify and qualify alternate cloud provider for payments",
     "IT Infrastructure", 120, "Not Started", False),
]

def _make_risk(row: tuple, rng: random.Random,
               cfg: dict[str, Any]) -> dict[str, Any]:
    (title, category, dept, il, ii, rl, ri, treatment, status, controls,
     ident, review) = row
    return {
        "title": title,
        "category": category,
        "owner": rng.choice(OWNERS_BY_DEPT[dept]),
        "department": dept,
        "inherent_likelihood": il,
        "inherent_impact": ii,
        "residual_likelihood": rl,
        "residual_impact": ri,
        "treatment": treatment,
        "status": status,
        "existing_controls": controls,
        "identified_date": ident,
        "next_review_date": review,
        "__inherent_score__": calculate_score(il, ii),
        "__residual_score__": calculate_score(rl, ri),
    }


def _make_action(risk_id: str, row: tuple, rng: random.Random,
                 cfg: dict[str, Any]) -> dict[str, Any]:
    desc, dept, offset, status, completed = row
    due = (_dt.date.fromisoformat(TODAY) + _dt.timedelta(days=offset)).isoformat()
    return {
        "risk_id": risk_id,
        "description": desc,
        "action_owner": rng.choice(OWNERS_BY_DEPT[dept]),
        "due_date": due,
        "status": status,
        "completed_date": TODAY if completed else None,
    }


def seed(db: RiskDB | None = None,
         config: dict[str, Any] | None = None,
         reset: bool = False) -> RiskDB:
    """Populate the database with deterministic demo data."""
    cfg = config or load_config()
    db = db or RiskDB(config=cfg)
    if reset:
        db.reset()
    if not db.is_empty():
        logger.info("Database already populated; skipping seed")
        return db

    rng = random.Random(RANDOM_SEED)
    order = list(range(len(RISK_TEMPLATES)))
    rng.shuffle(order)

    created: list[str] = []
    for idx in order:
        risk = _make_risk(RISK_TEMPLATES[idx], rng, cfg)
        meta = {k: risk.pop(k) for k in list(risk) if k.startswith("__")}
        rid = db.create_risk(risk, "seed")
        created.append(rid)

    for rid in created:
        for _ in range(rng.randint(1, 3)):
            db.create_action(rid, _make_action(rid, rng.choice(ACTION_TEMPLATES),
                                               rng, cfg), "seed")

    rows: list[tuple[str, str, int, str, str]] = []
    for snap_date in SNAPSHOT_DATES:
        for rid in created:
            risk = db.get_risk(rid)
            base = int(risk["residual_score"])
            score = max(1, min(25, base + rng.choice([-1, 0, 0, 1])))
            rows.append((snap_date, rid, score,
                         get_rating(score, cfg), risk["status"]))
    db.insert_snapshot_rows(rows)
    logger.info("Seeded %d risks, %d snapshot rows", len(created), len(rows))
    return db


def seed_demo_data() -> None:
    """CLI-friendly entry point that reseeds the default database."""
    db = RiskDB(config=load_config())
    seed(db, reset=True)
    print(f"Seeded demo database at {db.path}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    seed_demo_data()

