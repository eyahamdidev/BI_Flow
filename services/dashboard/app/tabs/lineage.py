import plotly.graph_objects as go
import streamlit as st

from ..data.loader import Bundle
from ..theme import AMBER, BLUE, CORAL, TEAL

LAYER_COLOR = [CORAL, AMBER, BLUE, TEAL, TEAL]


def render(b: Bundle) -> None:
    st.subheader("Lineage")
    g = b.lineage or {}
    nodes, edges = g.get("nodes", []), g.get("edges", [])
    if not nodes:
        st.info("No lineage graph yet.")
        return
    per_layer: dict[int, int] = {}
    pos = {}
    for n in nodes:
        y = per_layer.get(n["layer"], 0)
        per_layer[n["layer"]] = y + 1
        pos[n["id"]] = (n["layer"], -y)
    fig = go.Figure()
    for e in edges:
        (x0, y0), (x1, y1) = pos[e["from"]], pos[e["to"]]
        fig.add_scatter(x=[x0, x1], y=[y0, y1], mode="lines", line=dict(color="#aaa"), hoverinfo="text", text=e["step"], showlegend=False)
    fig.add_scatter(
        x=[pos[n["id"]][0] for n in nodes], y=[pos[n["id"]][1] for n in nodes], mode="markers+text",
        text=[n["label"] for n in nodes], textposition="top center",
        marker=dict(size=22, color=[LAYER_COLOR[n["layer"] % 5] for n in nodes]), showlegend=False)
    fig.update_layout(height=420, xaxis=dict(visible=False), yaxis=dict(visible=False), margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig, use_container_width=True)
    st.caption("raw -> clean -> dbt -> KPI -> insight. Hover an edge to see the transformation. (BO2 provides the real graph JSON.)")
