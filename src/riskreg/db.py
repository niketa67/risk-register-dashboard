"""SQLite persistence: schema, CRUD, audit logging and snapshots."""
from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterator, Optional

import pandas as pd

from .config import PROJECT_ROOT, load_config
from .scoring import calculate_score, get_rating

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "risk_register.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS risks (
    risk_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    category TEXT NOT NULL,
    owner TEXT NOT NULL,
    department TEXT NOT NULL,
    inherent_likelihood INTEGER NOT NULL,
    inherent_impact INTEGER NOT NULL,
    inherent_score INTEGER NOT NULL,
    inherent_rating TEXT NOT NULL,
    residual_likelihood INTEGER NOT NULL,
    residual_impact INTEGER NOT NULL,
    residual_score INTEGER NOT NULL,
    residual_rating TEXT NOT NULL,
    treatment TEXT NOT NULL,
    status TEXT NOT NULL,
    existing_controls TEXT DEFAULT '',
    identified_date TEXT NOT NULL,
    next_review_date TEXT,
    last_updated TEXT NOT NULL,
    is_deleted INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS mitigation_actions (
    action_id INTEGER PRIMARY KEY AUTOINCREMENT,
    risk_id TEXT NOT NULL REFERENCES risks(risk_id),
    description TEXT NOT NULL,
    action_owner TEXT NOT NULL,
    due_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Not Started',
    completed_date TEXT
);
CREATE TABLE IF NOT EXISTS audit_log (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    risk_id TEXT NOT NULL,
    field_changed TEXT,
    old_value TEXT,
    new_value TEXT,
    changed_by TEXT NOT NULL,
    action TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS risk_snapshots (
    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date TEXT NOT NULL,
    risk_id TEXT NOT NULL,
    residual_score INTEGER NOT NULL,
    residual_rating TEXT NOT NULL,
    status TEXT NOT NULL
);
"""

# Fields supplied by the user (scores/ratings are derived).
INPUT_FIELDS = (
    "title", "description", "category", "owner", "department",
    "inherent_likelihood", "inherent_impact",
    "residual_likelihood", "residual_impact",
    "treatment", "status", "existing_controls",
    "identified_date", "next_review_date",
)
COMPUTED_FIELDS = ("inherent_score", "inherent_rating",
                   "residual_score", "residual_rating")
TRACKED_FIELDS = INPUT_FIELDS + COMPUTED_FIELDS
ACTION_FIELDS = ("description", "action_owner", "due_date", "status",
                 "completed_date")


class ValidationError(ValueError):
    """Raised when user input fails validation."""


def _check_date(value: Any, name: str, required: bool) -> Optional[str]:
    """Normalise a date-like value to ISO text, or raise ValidationError."""
    if value in (None, ""):
        if required:
            raise ValidationError(f"{name} is required")
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError as exc:
        raise ValidationError(f"{name} is not a valid date (YYYY-MM-DD)") from exc


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class RiskDB:
    """Data-access layer for the risk register."""

    def __init__(self, path: Path | str | None = None,
                 config: Optional[dict[str, Any]] = None) -> None:
        self.path = Path(path) if path else DEFAULT_DB_PATH
        self.config = config or load_config()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    # ------------------------------------------------------------ plumbing
    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_schema(self) -> None:
        """Create tables if they do not exist."""
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    def reset(self) -> None:
        """Drop all data and recreate the schema."""
        with self._conn() as conn:
            conn.executescript(
                "DROP TABLE IF EXISTS risk_snapshots;"
                "DROP TABLE IF EXISTS audit_log;"
                "DROP TABLE IF EXISTS mitigation_actions;"
                "DROP TABLE IF EXISTS risks;")
        self.init_schema()
        logger.info("Database reset: %s", self.path)

    def is_empty(self) -> bool:
        """True when no risks have ever been stored."""
        with self._conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM risks").fetchone()[0] == 0

    @staticmethod
    def _log(conn: sqlite3.Connection, risk_id: str, field: Optional[str],
             old: Any, new: Any, user: str, action: str) -> None:
        conn.execute(
            "INSERT INTO audit_log (timestamp, risk_id, field_changed, "
            "old_value, new_value, changed_by, action) VALUES (?,?,?,?,?,?,?)",
            (_now(), risk_id, field,
             None if old is None else str(old),
             None if new is None else str(new), user, action))

    # ---------------------------------------------------------- validation
    def validate_risk(self, data: dict[str, Any]) -> dict[str, Any]:
        """Validate raw input and return a cleaned, score-enriched dict."""
        cfg = self.config
        clean: dict[str, Any] = {}
        for req in ("title", "category", "owner", "department"):
            if not str(data.get(req, "") or "").strip():
                raise ValidationError(f"{req} is required")
            clean[req] = str(data[req]).strip()
        if clean["category"] not in cfg["categories"]:
            raise ValidationError(f"Invalid category: {clean['category']}")
        clean["description"] = str(data.get("description") or "")
        clean["existing_controls"] = str(data.get("existing_controls") or "")
        clean["treatment"] = data.get("treatment") or cfg["treatment_options"][0]
        if clean["treatment"] not in cfg["treatment_options"]:
            raise ValidationError(f"Invalid treatment: {clean['treatment']}")
        clean["status"] = data.get("status") or cfg["status_values"][0]
        if clean["status"] not in cfg["status_values"]:
            raise ValidationError(f"Invalid status: {clean['status']}")
        for key in ("inherent_likelihood", "inherent_impact",
                    "residual_likelihood", "residual_impact"):
            try:
                clean[key] = int(data[key])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValidationError(f"{key} must be an integer 1-5") from exc
            if not 1 <= clean[key] <= 5:
                raise ValidationError(f"{key} must be between 1 and 5")
        clean["inherent_score"] = calculate_score(
            clean["inherent_likelihood"], clean["inherent_impact"])
        clean["residual_score"] = calculate_score(
            clean["residual_likelihood"], clean["residual_impact"])
        if clean["residual_score"] > clean["inherent_score"] or \
                clean["residual_likelihood"] > clean["inherent_likelihood"] or \
                clean["residual_impact"] > clean["inherent_impact"]:
            raise ValidationError("Residual risk cannot exceed inherent risk")
        clean["inherent_rating"] = get_rating(clean["inherent_score"], cfg)
        clean["residual_rating"] = get_rating(clean["residual_score"], cfg)
        clean["identified_date"] = _check_date(
            data.get("identified_date") or date.today(), "identified_date", True)
        clean["next_review_date"] = _check_date(
            data.get("next_review_date"), "next_review_date", False)
        return clean


    # ---------------------------------------------------------------- risks
    @staticmethod
    def _next_risk_id(conn: sqlite3.Connection) -> str:
        row = conn.execute(
            "SELECT MAX(CAST(SUBSTR(risk_id, 5) AS INTEGER)) FROM risks").fetchone()
        return f"RSK-{(row[0] or 0) + 1:03d}"

    def create_risk(self, data: dict[str, Any], changed_by: str = "system") -> str:
        """Validate and insert a risk; return its generated risk_id."""
        clean = self.validate_risk(data)
        with self._conn() as conn:
            risk_id = self._next_risk_id(conn)
            row = {"risk_id": risk_id, **clean,
                   "last_updated": _now(), "is_deleted": 0}
            cols = ", ".join(row)
            marks = ", ".join("?" for _ in row)
            conn.execute(f"INSERT INTO risks ({cols}) VALUES ({marks})",
                         tuple(row.values()))
            for field in TRACKED_FIELDS:
                self._log(conn, risk_id, field, None, clean[field],
                          changed_by, "CREATE")
        logger.info("Created %s", risk_id)
        return risk_id

    def get_risk(self, risk_id: str, include_deleted: bool = False
                 ) -> Optional[dict[str, Any]]:
        """Return a risk as a dict, or None if absent/deleted."""
        sql = "SELECT * FROM risks WHERE risk_id = ?"
        if not include_deleted:
            sql += " AND is_deleted = 0"
        with self._conn() as conn:
            row = conn.execute(sql, (risk_id,)).fetchone()
        return dict(row) if row else None

    def list_risks(self, include_deleted: bool = False) -> pd.DataFrame:
        """Return all risks as a DataFrame ordered by risk_id."""
        sql = "SELECT * FROM risks"
        if not include_deleted:
            sql += " WHERE is_deleted = 0"
        sql += " ORDER BY risk_id"
        with self._conn() as conn:
            return pd.read_sql_query(sql, conn)

    def update_risk(self, risk_id: str, data: dict[str, Any],
                    changed_by: str = "system") -> list[str]:
        """Update a risk, auditing each changed field. Returns changed fields."""
        existing = self.get_risk(risk_id)
        if existing is None:
            raise KeyError(f"Risk not found: {risk_id}")
        merged = {k: existing.get(k) for k in INPUT_FIELDS}
        merged.update({k: v for k, v in data.items() if k in INPUT_FIELDS})
        clean = self.validate_risk(merged)

        def norm(v: Any) -> str:
            return "" if v is None else str(v)

        changed = [f for f in TRACKED_FIELDS
                   if norm(existing.get(f)) != norm(clean[f])]
        if not changed:
            return []
        with self._conn() as conn:
            sets = ", ".join(f"{f} = ?" for f in changed)
            conn.execute(
                f"UPDATE risks SET {sets}, last_updated = ? WHERE risk_id = ?",
                (*[clean[f] for f in changed], _now(), risk_id))
            for f in changed:
                self._log(conn, risk_id, f, existing.get(f), clean[f],
                          changed_by, "UPDATE")
        logger.info("Updated %s: %s", risk_id, changed)
        return changed

    def delete_risk(self, risk_id: str, changed_by: str = "system") -> None:
        """Soft-delete a risk and write an audit entry."""
        if self.get_risk(risk_id) is None:
            raise KeyError(f"Risk not found: {risk_id}")
        with self._conn() as conn:
            conn.execute(
                "UPDATE risks SET is_deleted = 1, last_updated = ? "
                "WHERE risk_id = ?", (_now(), risk_id))
            self._log(conn, risk_id, "is_deleted", 0, 1, changed_by, "DELETE")
        logger.info("Soft-deleted %s", risk_id)


    # -------------------------------------------------------------- actions
    def _validate_action(self, data: dict[str, Any]) -> dict[str, Any]:
        statuses = self.config.get(
            "action_status_values",
            ["Not Started", "In Progress", "Completed", "Overdue"])
        for req in ("description", "action_owner"):
            if not str(data.get(req, "") or "").strip():
                raise ValidationError(f"{req} is required")
        status = data.get("status") or "Not Started"
        if status not in statuses:
            raise ValidationError(f"Invalid action status: {status}")
        completed = _check_date(data.get("completed_date"),
                                "completed_date", False)
        if status == "Completed" and not completed:
            completed = date.today().isoformat()
        if status != "Completed":
            completed = None
        return {
            "description": str(data["description"]).strip(),
            "action_owner": str(data["action_owner"]).strip(),
            "due_date": _check_date(data.get("due_date"), "due_date", True),
            "status": status,
            "completed_date": completed,
        }

    def create_action(self, risk_id: str, data: dict[str, Any],
                      changed_by: str = "system") -> int:
        """Create a mitigation action for an existing risk."""
        if self.get_risk(risk_id) is None:
            raise ValidationError(f"Unknown risk: {risk_id}")
        clean = self._validate_action(data)
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO mitigation_actions (risk_id, description, "
                "action_owner, due_date, status, completed_date) "
                "VALUES (?,?,?,?,?,?)",
                (risk_id, clean["description"], clean["action_owner"],
                 clean["due_date"], clean["status"], clean["completed_date"]))
            action_id = int(cur.lastrowid)
            self._log(conn, risk_id, f"action #{action_id}", None,
                      clean["description"], changed_by, "CREATE")
        return action_id


    def get_action(self, action_id: int) -> Optional[dict[str, Any]]:
        """Return one action as a dict."""
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM mitigation_actions "
                               "WHERE action_id = ?", (action_id,)).fetchone()
        return dict(row) if row else None

    def update_action(self, action_id: int, data: dict[str, Any],
                      changed_by: str = "system") -> list[str]:
        """Update an action, auditing changed fields."""
        existing = self.get_action(action_id)
        if existing is None:
            raise KeyError(f"Action not found: {action_id}")
        merged = {k: existing[k] for k in ACTION_FIELDS}
        merged.update({k: v for k, v in data.items() if k in ACTION_FIELDS})
        clean = self._validate_action(merged)
        changed = [f for f in ACTION_FIELDS
                   if str(existing[f] or "") != str(clean[f] or "")]
        if not changed:
            return []
        with self._conn() as conn:
            sets = ", ".join(f"{f} = ?" for f in changed)
            conn.execute(
                f"UPDATE mitigation_actions SET {sets} WHERE action_id = ?",
                (*[clean[f] for f in changed], action_id))
            for f in changed:
                self._log(conn, existing["risk_id"],
                          f"action #{action_id} {f}", existing[f], clean[f],
                          changed_by, "UPDATE")
        return changed


    def complete_action(self, action_id: int,
                        changed_by: str = "system") -> None:
        """Mark an action Completed as of today."""
        self.update_action(
            action_id, {"status": "Completed",
                        "completed_date": date.today().isoformat()},
            changed_by)

    def refresh_overdue_actions(self, today: Optional[date] = None) -> int:
        """Auto-mark open actions past their due date as Overdue."""
        today = today or date.today()
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE mitigation_actions SET status = 'Overdue' "
                "WHERE status IN ('Not Started', 'In Progress') "
                "AND due_date < ? AND risk_id IN "
                "(SELECT risk_id FROM risks WHERE is_deleted = 0)",
                (today.isoformat(),))
            return cur.rowcount

    def list_actions(self, risk_id: Optional[str] = None,
                     include_deleted_risks: bool = False) -> pd.DataFrame:
        """Return actions (joined with risk title) as a DataFrame."""
        sql = ("SELECT a.*, r.title AS risk_title FROM mitigation_actions a "
               "JOIN risks r ON r.risk_id = a.risk_id WHERE 1=1")
        params: list[Any] = []
        if not include_deleted_risks:
            sql += " AND r.is_deleted = 0"
        if risk_id:
            sql += " AND a.risk_id = ?"
            params.append(risk_id)
        sql += " ORDER BY a.due_date, a.action_id"
        with self._conn() as conn:
            return pd.read_sql_query(sql, conn, params=params)

    # ---------------------------------------------------------------- audit
    def get_audit_log(self, risk_id: Optional[str] = None) -> pd.DataFrame:
        """Return audit entries, newest first, optionally for one risk."""
        sql = "SELECT * FROM audit_log"
        params: list[Any] = []
        if risk_id:
            sql += " WHERE risk_id = ?"
            params.append(risk_id)
        sql += " ORDER BY log_id DESC"
        with self._conn() as conn:
            return pd.read_sql_query(sql, conn, params=params)


    # ------------------------------------------------------------ snapshots
    def take_snapshot(self, snapshot_date: Optional[date | str] = None) -> int:
        """Store residual state of all live risks; returns rows written.

        Re-snapshotting the same date replaces the earlier snapshot.
        """
        snap = _check_date(snapshot_date or date.today(),
                           "snapshot_date", True)
        with self._conn() as conn:
            conn.execute("DELETE FROM risk_snapshots WHERE snapshot_date = ?",
                         (snap,))
            cur = conn.execute(
                "INSERT INTO risk_snapshots (snapshot_date, risk_id, "
                "residual_score, residual_rating, status) "
                "SELECT ?, risk_id, residual_score, residual_rating, status "
                "FROM risks WHERE is_deleted = 0", (snap,))
            return cur.rowcount

    def insert_snapshot_rows(
            self, rows: list[tuple[str, str, int, str, str]]) -> None:
        """Bulk insert (date, risk_id, score, rating, status) rows (seeding)."""
        with self._conn() as conn:
            conn.executemany(
                "INSERT INTO risk_snapshots (snapshot_date, risk_id, "
                "residual_score, residual_rating, status) "
                "VALUES (?,?,?,?,?)", rows)

    def get_snapshots(self) -> pd.DataFrame:
        """Return every snapshot row."""
        with self._conn() as conn:
            return pd.read_sql_query(
                "SELECT * FROM risk_snapshots "
                "ORDER BY snapshot_date, risk_id", conn)

