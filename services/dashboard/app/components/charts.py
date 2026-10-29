"""Chart components (Plotly). Every chart carries a data-source label (spec BO6)."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from ..theme import CORAL, SEQ, TEAL


def trend(df: pd.DataFrame, title: str, unit: str, anomalies: list[str] | None = None, source: str = "") -> go.Figure:
    fig = go.Figure()
    for i, (dv, g) in enumerate(df.groupby("dimension_value")):
        fig.add_scatter(x=g["period"], y=g["value"], mode="lines+markers", name=str(dv), line=dict(color=SEQ[i % len(SEQ)]))
    if anomalies:
        a = df[(df["dimension"] == "total") & (df["period"].isin(anomalies))]
        fig.add_scatter(x=a["period"], y=a["value"], mode="markers", name="anomaly", marker=dict(color=CORAL, size=13, symbol="x"))
    fig.update_layout(title=title, yaxis_title=unit, margin=dict(l=10, r=10, t=50, b=40), height=340,
                      annotations=[dict(text=f"source: {source}", xref="paper", yref="paper", x=0, y=-0.2, showarrow=False, font=dict(size=10))])
    return fig


def bars(labels: list[str], values: list[float], title: str, source: str = "") -> go.Figure:
    fig = go.Figure(go.Bar(x=labels, y=values, marker_color=TEAL))
    fig.update_layout(title=title, margin=dict(l=10, r=10, t=50, b=40), height=300,
                      annotations=[dict(text=f"source: {source}", xref="paper", yref="paper", x=0, y=-0.25, showarrow=False, font=dict(size=10))])
    return fig
