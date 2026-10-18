# Automated Risk Register & Heatmap Dashboard

**A lightweight, config-driven GRC tool for enterprise / technology risk management.** Log risks, score them on a 5×5 likelihood × impact matrix (inherent and residual), track mitigation actions, and view auto-generated heatmaps, ratings, and exportable reports — all stored in SQLite with a full audit trail.

## The problem

Risk registers in most organisations live in scattered spreadsheets with inconsistent scoring, no audit trail of who changed what, and no visibility into appetite breaches. This MVP gives a risk team a single source of truth: computed scores (never hand-typed), inherent vs residual movement, per-category risk appetite, soft deletes with audit logging, trend snapshots, and one-click Excel / CSV / HTML exports.

## Feature list

- **Risk register** — log risks with title, description, category, owner, department, existing controls, treatment and status.
- **Scoring** — Likelihood × Impact on a 1–5 scale; inherent and residual scores/ratings computed automatically (never typed in by the user).
- **5×5 heatmaps** — inherent vs residual, coloured by rating band, with per-cell counts and hover tooltips listing risk IDs and titles.
- **Risk appetite** — configurable maximum residual score, with per-category overrides; appetite-breach table with gap.
- **Mitigation actions** — add/edit/complete actions linked to risks; overdue actions auto-flagged.
- **Audit trail** — every create/update/delete (including soft deletes) writes old and new values per changed field.
- **Trends** — snapshot-based trend lines (rating counts and average residual score over time) and risk movement between snapshots.
- **Reports & export** — Excel workbook (Risk Register, Mitigation Actions, Summary, Heatmap data), CSV, and a self-contained HTML executive report with embedded heatmaps and methodology.
- **Settings** — read-only config view and a one-click demo-data reset.

## Architecture

```mermaid
flowchart TD
    subgraph UI [app/ — Streamlit UI]
        D[Dashboard] --> L[Logic]
        R[Risk Register] --> L
        A[Add / Edit Risk] --> L
        M[Mitigation Actions] --> L
        T[Trends & Analytics] --> L
        E[Reports & Export] --> L
    end
    subgraph SRC [src/riskreg/ — business logic]
        L[scoring.py]:::pure
        C[config.py]:::pure
        DB[(db.py — SQLite + audit)]
        S[seed.py — demo data]
        AN[analytics.py]
        H[heatmap.py]
        REP[reporting.py]
    end
    subgraph DATA [data/ — risk_register.db (gitignored)]
        DB
    end
    L --> C
    AN --> L
    H --> AN
    REP --> AN
    DB --> L
    S --> DB
    class L,C,AN,H,REP pure;
```

## Scoring methodology

Scores are **computed** (`likelihood × impact`) and mapped to rating bands — users never type a score or rating.

### Likelihood scale (1–5)

| Level | Label | Description |
|-------|-------|-------------|
| 1 | Rare | Less than 5% chance in 12 months; exceptional circumstances only |
| 2 | Unlikely | 5–20% chance in 12 months; could occur but not expected |
| 3 | Possible | 20–50% chance in 12 months; might occur at some point |
| 4 | Likely | 50–80% chance in 12 months; will probably occur |
| 5 | Almost Certain | Over 80% chance in 12 months; expected to occur |

### Impact scale (1–5)

Impact is described across financial, operational, regulatory and reputational dimensions, e.g. **Severe (5)** = loss over 10M / prolonged loss of critical capability / loss of licence / sustained loss of public trust.

### Rating bands (score = likelihood × impact)

| Band | Score | Colour |
|------|-------|--------|
| Low | 1–4 | #2e9e4f |
| Medium | 5–9 | #f2c230 |
| High | 10–15 | #f08a24 |
| Critical | 16–25 | #d62f2f |

### Risk appetite

Default maximum acceptable residual score is **9**. Per-category overrides exist (e.g. Cyber Security 6, Data Privacy 6, Regulatory / Compliance 4). A risk is *outside appetite* when its residual score exceeds its category threshold.

All of the above lives in `config/risk_config.yaml` — change scales, bands or appetite in YAML without touching any code.


## Quick start

Prerequisites: Python 3.10+.

```bash
# 1. Create the virtual environment
python -m venv .venv

# 2. Activate it (Windows PowerShell)
.venv\Scripts\Activate.ps1

# 3. Install dependencies
pip install -r requirements.txt

# 4. Seed the demo database (40 risks, actions and snapshots)
python run_seed.py

# 5. Run the dashboard
streamlit run app/streamlit_app.py
```

The app auto-seeds on first run if the database is empty, so you can skip step 4 for a quick demo.

To run the test suite:

```bash
pytest
```

## Config-driven design

`config/risk_config.yaml` drives likelihood and impact scales, rating bands, risk appetite (default + per-category overrides), risk categories, treatment options and status values. Edit the YAML and restart the app — no code changes required.

## Screenshots

Place screenshots under `docs/screenshots/` and reference them here:

- `docs/screenshots/dashboard.png` — KPI cards, inherent vs residual heatmaps, category chart, top 10 risks
- `docs/screenshots/risk-register.png` — filterable register with colour-coded ratings
- `docs/screenshots/add-edit-risk.png` — live score/rating preview before saving
- `docs/screenshots/reports.png` — Excel / CSV / HTML export

## Design decisions

- **Computed, not typed, scores** — risk teams cannot enter a rating that contradicts the matrix.
- **Inherent vs residual** — shows the effect of controls and treatment; risk reduction % tracked per risk.
- **Audit log on every write** — who changed which field, old vs new values, and when.
- **Soft deletes** — records disappear from views but remain, with audit, for history and compliance.
- **Risk snapshots** — stored on demand (and during seeding) so Trends is populated from first launch.
- **Config-driven scales, bands and appetite** — adapt to any risk framework without code changes.
- **SQLite, zero external services** — runs offline; trivial to back up or reset.

## Limitations and future improvements (MVP v1)

- User authentication and role-based access control
- Monte Carlo / FAIR quantitative risk analysis
- Key Risk Indicator (KRI) integration
- Email reminders for overdue reviews
- Jira / ServiceNow ticket integration
- Docker deployment

---

Built as a portfolio project for a Risk Technology internship. Business logic (`src/riskreg/`) is fully separated from the UI (`app/`), with type hints, docstrings and test coverage throughout.

