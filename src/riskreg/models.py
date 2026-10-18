"""Dataclasses representing the core domain entities."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional


@dataclass
class Risk:
    """A single risk register entry (scores are computed, never typed in)."""

    title: str
    category: str
    owner: str
    department: str
    inherent_likelihood: int
    inherent_impact: int
    residual_likelihood: int
    residual_impact: int
    description: str = ""
    treatment: str = "Mitigate"
    status: str = "Identified"
    existing_controls: str = ""
    identified_date: str = ""
    next_review_date: str = ""
    risk_id: Optional[str] = None
    inherent_score: int = 0
    inherent_rating: str = ""
    residual_score: int = 0
    residual_rating: str = ""
    last_updated: str = ""
    is_deleted: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Return the risk as a plain dictionary."""
        return asdict(self)


@dataclass
class MitigationAction:
    """A mitigation action linked to a risk."""

    risk_id: str
    description: str
    action_owner: str
    due_date: str
    status: str = "Not Started"
    completed_date: Optional[str] = None
    action_id: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        """Return the action as a plain dictionary."""
        return asdict(self)


@dataclass
class AuditEntry:
    """One row of the audit trail."""

    risk_id: str
    field_changed: str
    old_value: Optional[str]
    new_value: Optional[str]
    changed_by: str
    action: str
    timestamp: str = ""
    log_id: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        """Return the entry as a plain dictionary."""
        return asdict(self)
