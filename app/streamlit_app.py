"""Streamlit dashboard for the Automated Risk Register and Heatmap Dashboard.

The UI layer contains no scoring logic -- all scores, ratings, appetite checks
and aggregations are delegated to src/riskreg/.
"""
from __future__ import annotations

import datetime as _dt
import logging
from pathlib import Path

import pandas as pd
import streamlit as st

# Allow running both as ``streamlit run app/streamlit_app.py`` from the repo
# root and as ``python -m app.streamlit_app``.
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
import sys  # noqa: E402
for p in (SRC, ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from riskreg.config import load_config, Config  # noqa: E402
from riskreg.db import RiskDB, ValidationError  # noqa: E402
from riskreg.seed import seed  # noqa: E402
from riskreg import scoring  # noqa: E402
from riskreg import analytics  # noqa: E402
from riskreg import heatmap as heatmap_mod  # noqa: E402
from riskreg import reporting  # noqa: E402

logger = logging.getLogger(__name__)

PAGES = [
    "Dashboard",
    "Risk Register",
    "Add / Edit Risk",
    "Mitigation Actions",
    "Trends and Analytics",
    "Reports and Export",
    "Settings",
]

RATING_ORDER = ["Low", "Medium", "High", "Critical"]
RATING_EMOJI = {"Low": "🟢", "Medium": "🟡", "High": "🟠", "Critical": "🔴"}

# --------------------------------------------------------------------------- app state


def _get_db() -> RiskDB:
    """Open (and lazily seed) the database, stored in session state."""
    if "db" not in st.session_state:
        cfg = load_config()
        db = RiskDB(config=cfg)
        if db.is_empty():
            seed(db, reset=True)
        st.session_state.db = db
        st.session_state.cache_version = 0
    return st.session_state.db


def _bump_cache() -> None:
    """Invalidate cached reads so writes are immediately visible."""
    st.session_state.cache_version = st.session_state.get("cache_version", 0) + 1
    st.cache_data.clear()


@st.cache_data(show_spinner=False)
def _load_risks(cache_version: int) -> pd.DataFrame:
    return _get_db().list_risks()


@st.cache_data(show_spinner=False)
def _load_actions(cache_version: int) -> pd.DataFrame:
    return _get_db().list_actions()


@st.cache_data(show_spinner=False)
def _load_audit(cache_version: int, risk_id: str) -> pd.DataFrame:
    return _get_db().get_audit_log(risk_id)


@st.cache_data(show_spinner=False)
def _load_snapshots(cache_version: int) -> pd.DataFrame:
    return _get_db().get_snapshots()


def _config() -> dict:
    return load_config()


def _rating_badge(rating: str, config: dict) -> str:
    color = scoring.get_rating_color(rating, config)
    return (
        f"<span style='background:{color};color:#fff;padding:2px 8px;"
        f"border-radius:4px;font-size:11px;font-weight:bold;white-space:nowrap'>"
        f"{rating}</span>"
    )


def _scale_entry(config: dict, scale_name: str, lvl: int) -> dict:
    """Return a scale entry, tolerant of int or str YAML keys."""
    scale = config[scale_name]
    return scale.get(lvl) or scale.get(str(lvl))


# --------------------------------------------------------------------------- helpers


def risks_df() -> pd.DataFrame:
    return _load_risks(st.session_state.get("cache_version", 0))


def actions_df() -> pd.DataFrame:
    return _load_actions(st.session_state.get("cache_version", 0))


def kpi_cards() -> None:
    db = _get_db()
    config = _config()
    risks = risks_df()
    actions = actions_df()
    live = risks[risks["is_deleted"] == 0]
    outside = analytics.outside_appetite_table(live, config)
    overdue_rev = analytics.overdue_reviews(live, _dt.date.today())
    overdue_act = actions[actions["status"] == "Overdue"]
    reductions = [
        scoring.risk_reduction_pct(int(r["inherent_score"]), int(r["residual_score"]))
        for _, r in live.iterrows()
    ]
    avg_red = sum(reductions) / len(reductions) if reductions else 0.0
    cards = [
        ("Total open risks", len(live)),
        ("Critical", int((live["residual_rating"] == "Critical").sum())),
        ("High", int((live["residual_rating"] == "High").sum())),
        ("Outside appetite", len(outside)),
        ("Overdue reviews", len(overdue_rev)),
        ("Overdue actions", len(overdue_act)),
        ("Avg risk reduction", f"{avg_red:.1f}%"),
    ]
    cols = st.columns(len(cards))
    for col, (label, value) in zip(cols, cards):
        with col:
            st.metric(label, value)


def _top10_table(live: pd.DataFrame, config: dict) -> None:
    top = live.sort_values(["residual_score", "risk_id"],
                           ascending=[False, True]).head(10)
    show = top[["risk_id", "title", "category", "owner", "residual_score",
                "residual_rating"]].copy()
    show["residual_rating"] = show["residual_rating"].apply(
        lambda r: _rating_badge(str(r), config))
    st.write(show.to_html(escape=False, index=False), unsafe_allow_html=True)


def page_dashboard() -> None:
    config = _config()
    st.title("Dashboard")
    st.caption("Enterprise risk register — inherent vs residual view, "
               "computed from Likelihood × Impact (1×1 to 5×5).")
    risks = risks_df()
    db = _get_db()
    db.refresh_overdue_actions()
    live = risks[risks["is_deleted"] == 0]
    st.session_state["cache_version"] = st.session_state.get("cache_version", 0)

    kpi_cards()
    st.divider()

    col_inh, col_res = st.columns(2)
    with col_inh:
        st.plotly_chart(
            heatmap_mod.build_heatmap(live, config, "inherent",
                                      "Inherent Risk Heatmap"),
            use_container_width=True, key="heat_inherent")
    with col_res:
        st.plotly_chart(
            heatmap_mod.build_heatmap(live, config, "residual",
                                      "Residual Risk Heatmap"),
            use_container_width=True, key="heat_residual")

    st.subheader("Risks by category (stacked by residual rating)")
    breakdown = analytics.category_breakdown(live, config)
    fig = _category_bar(breakdown, config)
    st.plotly_chart(fig, use_container_width=True, key="cat_bar")

    st.subheader("Top 10 risks by residual score")
    _top10_table(live, config)


def _category_bar(breakdown: pd.DataFrame, config: dict):
    import plotly.graph_objects as go
    fig = go.Figure()
    colors = {"Low": scoring.get_rating_color("Low", config),
              "Medium": scoring.get_rating_color("Medium", config),
              "High": scoring.get_rating_color("High", config),
              "Critical": scoring.get_rating_color("Critical", config)}
    for band in RATING_ORDER:
        fig.add_trace(go.Bar(name=band, x=breakdown["category"],
                             y=breakdown[band],
                             marker_color=colors[band]))
    fig.update_layout(barmode="stack", xaxis_title="Category",
                      yaxis_title="Number of risks",
                      legend_title="Residual rating",
                      height=420, margin=dict(l=60, r=20, t=40, b=60))
    fig.update_xaxes(tickangle=-15)
    return fig


def _risk_detail_table(risk: dict, config: dict) -> None:
    from html import escape
    rows = [
        ("Risk ID", risk["risk_id"]), ("Title", risk["title"]),
        ("Category", risk["category"]), ("Owner", risk["owner"]),
        ("Department", risk["department"]),
        ("Inherent", f"{risk['inherent_likelihood']} × {risk['inherent_impact']} "
         f"= {risk['inherent_score']}  ({risk['inherent_rating']})"),
        ("Residual", f"{risk['residual_likelihood']} × {risk['residual_impact']} "
         f"= {risk['residual_score']}  ({risk['residual_rating']})"),
        ("Treatment", risk["treatment"]), ("Status", risk["status"]),
        ("Existing controls", risk["existing_controls"]),
        ("Identified date", risk["identified_date"]),
        ("Next review date", risk["next_review_date"] or "—"),
        ("Last updated", risk["last_updated"]),
        ("Outside appetite",
         "Yes" if scoring.is_outside_appetite(
             int(risk["residual_score"]), risk["category"], config) else "No"),
    ]
    st.write(
        "<table><tbody>" +
        "".join(f"<tr><td style='font-weight:bold'>{escape(k)}</td>"
                f"<td>{escape(str(v))}</td></tr>" for k, v in rows) +
        "</tbody></table>",
        unsafe_allow_html=True,
    )


def page_risk_register() -> None:
    from html import escape
    config = _config()
    risks = risks_df()
    live = risks[risks["is_deleted"] == 0].copy()
    st.title("Risk Register")
    st.caption("Soft-deleted risks are hidden. Select a risk to open its detail view.")

    with st.expander("Filters", expanded=True):
        c1, c2, c3, c4 = st.columns(4)
        cats = ["All"] + sorted(live["category"].unique().tolist())
        with c1:
            cat = st.selectbox("Category", cats)
        with c2:
            owners = ["All"] + sorted(live["owner"].unique().tolist())
            owner = st.selectbox("Owner", owners)
        with c3:
            rating = st.selectbox("Rating", ["All"] + RATING_ORDER)
        with c4:
            status = st.selectbox("Status", ["All"] +
                                  sorted(live["status"].unique().tolist()))
        c5, c6 = st.columns(2)
        with c5:
            outside_only = st.checkbox("Outside appetite only", value=False)
        with c6:
            search = st.text_input("Search (title / owner / controls)")

    filtered = live
    if cat != "All":
        filtered = filtered[filtered["category"] == cat]
    if owner != "All":
        filtered = filtered[filtered["owner"] == owner]
    if rating != "All":
        filtered = filtered[filtered["residual_rating"] == rating]
    if status != "All":
        filtered = filtered[filtered["status"] == status]
    if outside_only:
        filtered = filtered[
            filtered.apply(
                lambda r: scoring.is_outside_appetite(
                    int(r["residual_score"]), r["category"], config), axis=1)]
    if search:
        s = search.lower()
        mask = (filtered["title"].str.lower().str.contains(s, na=False)
                | filtered["owner"].str.lower().str.contains(s, na=False)
                | filtered["existing_controls"].str.lower().str.contains(s, na=False)
                | filtered["risk_id"].str.lower().str.contains(s, na=False))
        filtered = filtered[mask]

    st.write(f"{len(filtered)} risk(es)")
    if not filtered.empty:
        display = filtered[["risk_id", "title", "category", "owner",
                            "residual_score", "residual_rating", "status"]].copy()
        display["residual_rating"] = display["residual_rating"].apply(
            lambda r: _rating_badge(str(r), config))
        st.write(display.to_html(escape=False, index=False),
                 unsafe_allow_html=True)

    st.divider()
    st.subheader("Risk detail")
    if not filtered.empty:
        options = ["— Select a risk —"] + filtered["risk_id"].tolist()
        pick = st.selectbox("Risk", options, key="register_pick")
        if pick and pick != "— Select a risk —":
            st.session_state["selected_risk"] = pick
    rid = st.session_state.get("selected_risk")
    if rid:
        risk = _get_db().get_risk(rid)
        if risk is None:
            st.warning("Risk no longer available.")
            st.session_state.pop("selected_risk", None)
        else:
            _risk_detail_table(risk, config)
            c1, c2 = st.columns(2)
            with c1:
                st.caption("Inherent → Residual movement")
                reduction = scoring.risk_reduction_pct(
                    int(risk["inherent_score"]), int(risk["residual_score"]))
                st.write(
                    f"{risk['inherent_likelihood']}×{risk['inherent_impact']} = "
                    f"{risk['inherent_score']} ({risk['inherent_rating']})  →  "
                    f"{risk['residual_likelihood']}×{risk['residual_impact']} = "
                    f"{risk['residual_score']} ({risk['residual_rating']}) — "
                    f"{reduction}% reduction")
            with c2:
                if st.button("Close detail", key="close_detail"):
                    st.session_state.pop("selected_risk", None)
                    st.rerun()
            st.subheader("Mitigation actions")
            acts = _get_db().list_actions(rid)
            if acts.empty:
                st.caption("No mitigation actions.")
            else:
                acts_show = acts[["description", "action_owner", "due_date",
                                  "status", "completed_date"]].copy()
                st.write(acts_show.to_html(index=False, escape=False),
                         unsafe_allow_html=True)
            st.subheader("Audit history")
            audit = _load_audit(st.session_state.get("cache_version", 0), rid)
            if audit.empty:
                st.caption("No audit entries.")
            else:
                st.write(audit[["timestamp", "field_changed", "old_value",
                                "new_value", "changed_by", "action"]]
                         .to_html(index=False, escape=False),
                         unsafe_allow_html=True)


def _level_selector(label: str, scale: dict, value: int,
                    key: str, help_text: str = "") -> int:
    """Select box showing level, label and description; returns the level int."""
    options = []
    for lvl in range(1, 6):
        entry = scale.get(lvl) or scale.get(str(lvl))
        desc = entry.get("description") or entry.get("financial") or ""
        options.append((lvl, f"{lvl} — {entry['label']} — {desc}"))
    labels = [opt[1] for opt in options]
    default_idx = next((i for i, (lvl, _) in enumerate(options) if lvl == value), 0)
    choice = st.selectbox(label, labels, index=default_idx, key=key, help=help_text)
    return options[labels.index(choice)][0]


def _risk_form_defaults(risk: dict | None, config: dict) -> dict:
    if risk is None:
        return {
            "title": "", "category": config["categories"][0],
            "owner": "", "department": "",
            "inherent_likelihood": 3, "inherent_impact": 3,
            "residual_likelihood": 3, "residual_impact": 3,
            "treatment": config["treatment_options"][0],
            "status": config["status_values"][0],
            "existing_controls": "",
            "identified_date": _dt.date.today(),
            "next_review_date": None,
            "description": "",
        }
    return {
        "title": risk["title"], "category": risk["category"],
        "owner": risk["owner"], "department": risk["department"],
        "inherent_likelihood": int(risk["inherent_likelihood"]),
        "inherent_impact": int(risk["inherent_impact"]),
        "residual_likelihood": int(risk["residual_likelihood"]),
        "residual_impact": int(risk["residual_impact"]),
        "treatment": risk["treatment"], "status": risk["status"],
        "existing_controls": risk["existing_controls"],
        "identified_date": _dt.date.fromisoformat(risk["identified_date"]),
        "next_review_date": (_dt.date.fromisoformat(risk["next_review_date"])
                             if risk["next_review_date"] else None),
        "description": risk["description"],
    }


def page_add_edit_risk() -> None:
    config = _config()
    db = _get_db()
    edit_id = st.session_state.get("edit_risk_id")
    risk = db.get_risk(edit_id) if edit_id else None
    defaults = _risk_form_defaults(risk, config)
    is_edit = risk is not None

    st.title(("Edit risk" if is_edit else "Add risk"))
    st.caption("Scores and ratings are computed from Likelihood × Impact — "
               "they are not typed in.")

    c1, c2 = st.columns(2)
    with c1:
        f = {}
        f["title"] = st.text_input("Title *", value=defaults["title"],
                                   key="ar_title")
        f["category"] = st.selectbox("Category *", config["categories"],
                                     index=config["categories"].index(
                                         defaults["category"]),
                                     key="ar_category")
        f["owner"] = st.text_input("Owner *", value=defaults["owner"],
                                   key="ar_owner")
        f["department"] = st.text_input("Department *",
                                        value=defaults["department"],
                                        key="ar_department")
        f["description"] = st.text_area("Description",
                                        value=defaults["description"],
                                        key="ar_description")
        f["existing_controls"] = st.text_area("Existing controls",
                                              value=defaults["existing_controls"],
                                              key="ar_controls")
    with c2:
        f["inherent_likelihood"] = _level_selector(
            "Inherent likelihood *", config["likelihood_scale"],
            defaults["inherent_likelihood"], "ar_il")
        f["inherent_impact"] = _level_selector(
            "Inherent impact *", config["impact_scale"],
            defaults["inherent_impact"], "ar_ii")
        f["residual_likelihood"] = _level_selector(
            "Residual likelihood *", config["likelihood_scale"],
            defaults["residual_likelihood"], "ar_rl")
        f["residual_impact"] = _level_selector(
            "Residual impact *", config["impact_scale"],
            defaults["residual_impact"], "ar_ri")
        f["treatment"] = st.selectbox("Treatment *", config["treatment_options"],
                                      index=config["treatment_options"].index(
                                          defaults["treatment"]),
                                      key="ar_treatment")
        f["status"] = st.selectbox("Status *", config["status_values"],
                                   index=config["status_values"].index(
                                       defaults["status"]),
                                   key="ar_status")
    c3, c4 = st.columns(2)
    with c3:
        f["identified_date"] = st.date_input("Identified date *",
                                             value=defaults["identified_date"],
                                             key="ar_identified")
    with c4:
        f["next_review_date"] = st.date_input("Next review date",
                                              value=defaults["next_review_date"],
                                              key="ar_review")

    preview = None
    error = None
    try:
        probe = dict(f)
        probe["identified_date"] = (f["identified_date"].isoformat()
                                    if isinstance(f["identified_date"], _dt.date)
                                    else f["identified_date"])
        nr = f["next_review_date"]
        probe["next_review_date"] = (nr.isoformat()
                                     if isinstance(nr, _dt.date) else nr)
        cleaned = db.validate_risk(probe)
        preview = cleaned
    except ValidationError as exc:
        error = str(exc)

    st.subheader("Live preview (before saving)")
    if error:
        st.error(error)
    if preview:
        p1, p2, p3, p4 = st.columns(4)
        with p1:
            st.metric("Inherent score",
                      f"{preview['inherent_score']}  "
                      f"{preview['inherent_rating']}")
        with p2:
            st.metric("Residual score",
                      f"{preview['residual_score']}  "
                      f"{preview['residual_rating']}")
        with p3:
            st.write(_rating_badge(preview["residual_rating"], config),
                     "Residual rating", unsafe_allow_html=True)
        with p4:
            outside = scoring.is_outside_appetite(
                int(preview["residual_score"]), preview["category"], config)
            st.error("Outside appetite" if outside else "Within appetite")
        reduction = scoring.risk_reduction_pct(int(preview["inherent_score"]),
                                               int(preview["residual_score"]))
        st.caption(f"Risk reduction: {reduction}%")

    st.divider()
    with st.form("ar_save_form", clear_on_submit=False):
        cA, cB = st.columns([2, 2])
        with cA:
            save = st.form_submit_button(
                "Save risk" if not is_edit else "Update risk", type="primary")
        with cB:
            if st.form_submit_button("Cancel"):
                st.session_state.pop("edit_risk_id", None)
                st.rerun()
        if save:
            if error:
                st.error("Fix validation errors before saving.")
            else:
                try:
                    if is_edit:
                        db.update_risk(edit_id, preview, changed_by="streamlit")
                    else:
                        db.create_risk(preview, changed_by="streamlit")
                    _bump_cache()
                    st.session_state.pop("edit_risk_id", None)
                    st.success("Risk saved.")
                    st.rerun()
                except ValidationError as exc:
                    st.error(str(exc))

    if is_edit:
        st.divider()
        st.subheader("Soft delete")
        confirm = st.checkbox("I confirm I want to soft-delete this risk",
                              key="ar_delete_confirm")
        if st.button("Delete risk", disabled=not confirm, key="ar_delete"):
            db.delete_risk(edit_id, changed_by="streamlit")
            _bump_cache()
            st.session_state.pop("edit_risk_id", None)
            st.session_state.pop("selected_risk", None)
            st.warning("Risk soft-deleted.")
            st.rerun()


def _status_badge(status: str) -> str:
    color = {"Not Started": "#6c757d", "In Progress": "#17a2b8",
             "Completed": "#2e9e4f", "Overdue": "#d62f2f"}.get(status, "#6c757d")
    return (f"<span style='background:{color};color:#fff;padding:2px 8px;"
            f"border-radius:4px;font-size:11px;font-weight:bold;"
            f"white-space:nowrap'>{status}</span>")


def page_mitigation_actions() -> None:
    from html import escape
    config = _config()
    db = _get_db()
    db.refresh_overdue_actions()
    _bump_cache()
    risks = risks_df()
    live = risks[risks["is_deleted"] == 0]
    st.title("Mitigation Actions")
    st.caption("Actions linked to risks. Overdue actions are highlighted and "
               "auto-marked when their due date passes.")

    col_sel, col_add = st.columns([2, 1])
    with col_sel:
        options = ["— Select a risk —"] + live["risk_id"].tolist()
        pick = st.selectbox("View actions for risk", options, key="ma_pick")
    with col_add:
        st.write("")
        st.write("")

    rid = None
    if pick and pick != "— Select a risk —":
        rid = pick
        st.session_state["ma_risk"] = rid
    else:
        rid = st.session_state.get("ma_risk")

    actions = db.list_actions(rid) if rid else db.list_actions()
    if rid:
        risk_title = live[live["risk_id"] == rid]["title"].iloc[0]
        st.subheader(f"Actions for {escape(risk_title)} ({rid})")

    if actions.empty:
        st.caption("No actions.")
    else:
        acts = actions.copy()
        acts["status_badge"] = acts["status"].apply(_status_badge)
        overdue_mask = acts["status"] == "Overdue"
        st.write(acts[["action_id", "risk_id", "description", "action_owner",
                       "due_date", "status_badge", "completed_date"]]
                 .to_html(escape=False, index=False),
                 unsafe_allow_html=True)
        if overdue_mask.any():
            st.warning(f"{int(overdue_mask.sum())} overdue action(s).")

    st.divider()
    st.subheader("Add / edit action")
    action_options = ["— New action —"]
    if rid:
        action_options += [f"#{int(a.action_id)} {a.description}"
                           for _, a in actions.iterrows()]
    apick = st.selectbox("Action", action_options, key="ma_apick")
    edit_action_id = None
    action_defaults = {"description": "", "action_owner": "", "due_date": None,
                       "status": "Not Started", "completed_date": None}
    if apick and apick != "— New action —":
        edit_action_id = int(apick.split("#", 1)[1].split(" ", 1)[0])
        existing = db.get_action(edit_action_id)
        if existing:
            action_defaults = {
                "description": existing["description"],
                "action_owner": existing["action_owner"],
                "due_date": (_dt.date.fromisoformat(existing["due_date"])
                             if existing["due_date"] else None),
                "status": existing["status"],
                "completed_date": existing["completed_date"],
            }

    cfg_statuses = config.get("action_status_values",
                              ["Not Started", "In Progress", "Completed",
                               "Overdue"])
    with st.form("ma_form"):
        adesc = st.text_area("Description *", value=action_defaults["description"],
                             key="ma_desc")
        aowner = st.text_input("Action owner *", value=action_defaults["action_owner"],
                               key="ma_owner")
        adue = st.date_input("Due date *",
                             value=action_defaults["due_date"] or _dt.date.today(),
                             key="ma_due")
        astatus = st.selectbox("Status", cfg_statuses,
                               index=cfg_statuses.index(action_defaults["status"])
                               if action_defaults["status"] in cfg_statuses else 0,
                               key="ma_status")
        cS, cC = st.columns(2)
        with cS:
            save_act = st.form_submit_button("Save action", type="primary")
        with cC:
            do_complete = st.form_submit_button("Mark complete",
                                                disabled=edit_action_id is None)
        if save_act:
            try:
                data = {"description": adesc, "action_owner": aowner,
                        "due_date": adue.isoformat(), "status": astatus}
                if edit_action_id is None:
                    if not rid:
                        st.error("Select a risk first.")
                    else:
                        db.create_action(rid, data, changed_by="streamlit")
                else:
                    db.update_action(edit_action_id, data, changed_by="streamlit")
                _bump_cache()
                st.session_state.pop("ma_apick", None)
                st.success("Action saved.")
                st.rerun()
            except ValidationError as exc:
                st.error(str(exc))
        if do_complete and edit_action_id is not None:
            db.complete_action(edit_action_id, changed_by="streamlit")
            _bump_cache()
            st.session_state.pop("ma_apick", None)
            st.success("Action marked complete.")
            st.rerun()


def page_trends_analytics() -> None:
    import plotly.graph_objects as go
    config = _config()
    db = _get_db()
    st.title("Trends and Analytics")
    st.caption("Trend analysis is based on risk snapshots. Take a snapshot to "
               "record the current residual state of all open risks.")

    risks = risks_df()
    live = risks[risks["is_deleted"] == 0]
    snapshots = _load_snapshots(st.session_state.get("cache_version", 0))

    c1, c2 = st.columns([1, 3])
    with c1:
        if st.button("Take snapshot now", key="take_snapshot",
                     type="primary"):
            n = db.take_snapshot(_dt.date.today())
            _bump_cache()
            st.success(f"Snapshot taken for {n} risk(es).")
            st.rerun()
    with c2:
        st.write("")

    st.divider()
    st.subheader("Residual risk counts by rating over time")
    trend = analytics.snapshot_trends(snapshots, config)
    if trend.empty:
        st.caption("No snapshots yet. Click 'Take snapshot now' to begin.")
    else:
        fig = go.Figure()
        colors = {"Low": scoring.get_rating_color("Low", config),
                  "Medium": scoring.get_rating_color("Medium", config),
                  "High": scoring.get_rating_color("High", config),
                  "Critical": scoring.get_rating_color("Critical", config)}
        for band in RATING_ORDER:
            fig.add_trace(go.Scatter(x=trend["snapshot_date"],
                                     y=trend[band], name=band,
                                     mode="lines+markers",
                                     line=dict(color=colors[band])))
        fig.update_layout(xaxis_title="Snapshot date",
                          yaxis_title="Number of risks",
                          legend_title="Residual rating",
                          height=360, margin=dict(l=60, r=20, t=30, b=50))
        st.plotly_chart(fig, use_container_width=True, key="trend_counts")

        st.subheader("Average residual score over time")
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(x=trend["snapshot_date"],
                                  y=trend["avg_residual_score"],
                                  mode="lines+markers",
                                  line=dict(color="#1F3864")))
        fig2.update_layout(xaxis_title="Snapshot date",
                           yaxis_title="Average residual score",
                           height=300, margin=dict(l=60, r=20, t=30, b=50))
        st.plotly_chart(fig2, use_container_width=True, key="trend_avg")

    st.divider()
    st.subheader("Risk movement between last two snapshots")
    movement = analytics.risk_movement(snapshots)
    if movement.empty:
        st.caption("Need at least two snapshots with common risks.")
    else:
        show = movement[["risk_id", "previous_score", "previous_rating",
                         "recent_score", "recent_rating", "direction",
                         "status"]].copy()
        show["recent_rating"] = show["recent_rating"].apply(
            lambda r: _rating_badge(str(r), config))
        st.write(show.to_html(escape=False, index=False),
                 unsafe_allow_html=True)

    st.divider()
    st.subheader("Appetite breaches (residual score above appetite)")
    breaches = analytics.outside_appetite_table(live, config)
    if breaches.empty:
        st.caption("No appetite breaches.")
    else:
        show = breaches[["risk_id", "title", "category", "owner",
                         "residual_score", "appetite_threshold", "gap"]].copy()
        st.write(show.to_html(index=False, escape=False),
                 unsafe_allow_html=True)


def page_reports_export() -> None:
    from html import escape
    config = _config()
    db = _get_db()
    risks = risks_df()
    live = risks[risks["is_deleted"] == 0]
    st.title("Reports and Export")
    st.caption("Export the register to Excel, CSV or a self-contained HTML "
               "executive report.")

    xlsx = reporting.build_excel_report(db)
    csv = reporting.build_csv(db)
    html = reporting.build_html_report(db)

    c1, c2, c3 = st.columns(3)
    with c1:
        st.download_button("Download Excel (xlsx)", data=xlsx,
                           file_name="risk_register.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           key="dl_xlsx", use_container_width=True)
    with c2:
        st.download_button("Download CSV", data=csv,
                           file_name="risk_register.csv",
                           mime="text/csv", key="dl_csv",
                           use_container_width=True)
    with c3:
        st.download_button("Download HTML report", data=html,
                           file_name="risk_report.html",
                           mime="text/html", key="dl_html",
                           use_container_width=True)

    st.divider()
    with st.expander("Methodology — scales, rating bands and appetite", expanded=False):
        st.subheader("Likelihood scale")
        st.table(pd.DataFrame([
            {"Level": l, "Label": _scale_entry(config, "likelihood_scale", l)["label"],
             "Description": _scale_entry(config, "likelihood_scale", l)["description"]}
            for l in range(1, 6)]))
        st.subheader("Impact scale")
        st.table(pd.DataFrame([
            {"Level": l, "Label": _scale_entry(config, "impact_scale", l)["label"],
             "Financial": _scale_entry(config, "impact_scale", l)["financial"],
             "Operational": _scale_entry(config, "impact_scale", l)["operational"],
             "Regulatory": _scale_entry(config, "impact_scale", l)["regulatory"],
             "Reputational": _scale_entry(config, "impact_scale", l)["reputational"]}
            for l in range(1, 6)]))
        st.subheader("Rating bands (score = likelihood × impact)")
        st.table(pd.DataFrame([
            {"Band": str(b["name"]), "Score range": f"{b['min']}–{b['max']}",
             "Color": str(b["color"])}
            for b in sorted(config["rating_bands"], key=lambda b: b["min"])]))
        st.subheader("Risk appetite")
        st.write("Maximum acceptable residual score: "
                 f"{config['risk_appetite']['max_residual_score']}")
        if config["risk_appetite"].get("category_overrides"):
            st.write("Per-category overrides:")
            st.write(config["risk_appetite"]["category_overrides"])
        st.write("Treatment options: " + ", ".join(config["treatment_options"]))
        st.write("Status values: " + ", ".join(config["status_values"]))
        st.caption("Scores are computed as Likelihood × Impact. Residual risk "
                   "must not exceed inherent risk. Risk reduction % = "
                   "(inherent − residual) / inherent × 100. A risk is outside "
                   "appetite when its residual score exceeds the threshold.")


def page_settings() -> None:
    config = _config()
    st.title("Settings")
    st.caption("Read-only configuration. Change config/risk_config.yaml and "
               "restart the app to adjust scales, bands and appetite.")
    st.subheader("Risk appetite")
    st.write("Maximum acceptable residual score:",
             config["risk_appetite"]["max_residual_score"])
    st.write("Category overrides:", config["risk_appetite"].get("category_overrides") or {})
    st.subheader("Rating bands")
    st.table(pd.DataFrame([
        {"Band": str(b["name"]), "Min": b["min"], "Max": b["max"],
         "Color": str(b["color"])}
        for b in sorted(config["rating_bands"], key=lambda b: b["min"])]))
    st.subheader("Categories")
    st.write(", ".join(config["categories"]))
    st.subheader("Treatment options")
    st.write(", ".join(config["treatment_options"]))
    st.subheader("Status values")
    st.write(", ".join(config["status_values"]))

    st.divider()
    st.subheader("Reset demo data")
    st.warning("This deletes all risks, actions, audit entries and snapshots "
               "and replaces them with the deterministic demo dataset.")
    confirm_reset = st.checkbox("I confirm I want to reset the demo database",
                                key="reset_confirm")
    if st.button("Reset demo data", disabled=not confirm_reset, type="primary",
                 key="reset_btn"):
        db = _get_db()
        seed(db, reset=True)
        _bump_cache()
        st.session_state.pop("edit_risk_id", None)
        st.session_state.pop("selected_risk", None)
        st.session_state.pop("ma_risk", None)
        st.session_state.pop("ma_apick", None)
        st.success("Database re-seeded.")
        st.rerun()


def main() -> None:
    st.set_page_config(page_title="Risk Register & Heatmap Dashboard",
                       page_icon="🛡️", layout="wide")
    _get_db()  # ensure DB (and seed) is ready
    with st.sidebar:
        st.header("Risk Register")
        page = st.radio("Navigation", PAGES, key="nav")
        st.divider()
        st.caption("Automated Risk Register & Heatmap Dashboard — MVP v1")

    if page == "Dashboard":
        page_dashboard()
    elif page == "Risk Register":
        page_risk_register()
    elif page == "Add / Edit Risk":
        page_add_edit_risk()
    elif page == "Mitigation Actions":
        page_mitigation_actions()
    elif page == "Trends and Analytics":
        page_trends_analytics()
    elif page == "Reports and Export":
        page_reports_export()
    elif page == "Settings":
        page_settings()


if __name__ == "__main__":
    main()

