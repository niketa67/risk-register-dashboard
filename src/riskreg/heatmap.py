"""Plotly 5x5 likelihood x impact heatmap figures."""
from __future__ import annotations

from typing import Any

import plotly.graph_objects as go

from .analytics import heatmap_matrix
from .config import Config


def _band_colors(config: Config) -> dict[str, str]:
    return {str(b["name"]): str(b["color"]) for b in config["rating_bands"]}


def _scale_labels(config: Config, key: str) -> list[str]:
    scale = config[key]
    out = []
    for lvl in range(1, 6):
        entry = scale.get(lvl) or scale.get(str(lvl))
        out.append(f"{lvl} {entry['label']}")
    return out


def build_heatmap(df, config: Config, score_type: str = "residual",
                  title: str | None = None) -> go.Figure:
    """Return a 5x5 heatmap figure coloured by rating band.

    Each cell shows the count of risks in that likelihood/impact cell and a
    hover tooltip listing the risk IDs and titles. Empty cells are shown as 0.
    """
    counts, details, matrix = heatmap_matrix(df, config, score_type)
    band_colors = _band_colors(config)
    order = ["Low", "Medium", "High", "Critical"]
    colors = [band_colors[n] for n in order]
    # Discrete colourscale so each rating index maps to its exact band colour.
    colorscale = []
    n = len(order)
    for idx, color in enumerate(colors):
        start = idx / n
        end = (idx + 1) / n
        colorscale.extend([[start, color], [end, color]])

    z_text = [[counts[l][i] for i in range(1, 6)] for l in range(1, 6)]
    hover = []
    for l in range(1, 6):
        row = []
        for i in range(1, 6):
            items = details.get((l, i), [])
            if items:
                lines = "<br>".join(
                    f"{d['risk_id']}: {d['title']} (score {d['score']})"
                    for d in items)
                row.append(f"Count: {len(items)}<br>{lines}")
            else:
                row.append("Count: 0")
        hover.append(row)

    fig = go.Figure(data=go.Heatmap(
        z=matrix,
        x=_scale_labels(config, "impact_scale"),
        y=_scale_labels(config, "likelihood_scale"),
        colorscale=colorscale,
        showscale=True,
        colorbar=dict(title="Rating", tickvals=[0.125, 0.375, 0.625, 0.875],
                      ticktext=order),
        text=z_text,
        texttemplate="%{text}",
        hovertemplate="%{hover}<extra></extra>",
        customdata=hover,
        hoverongaps=False,
    ))
    fig.update_traces(hovertemplate="%{customdata}<extra></extra>")
    fig.update_layout(
        title=title or f"{score_type.capitalize()} Risk Heatmap",
        xaxis_title="Impact",
        yaxis_title="Likelihood",
        xaxis=dict(tickmode="array"),
        yaxis=dict(tickmode="array"),
        height=520,
        width=620,
        margin=dict(l=80, r=40, t=60, b=80),
    )
    return fig
