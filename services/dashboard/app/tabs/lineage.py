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
    else:
        kinds = sorted({n.get("kind", "dataset") for n in nodes})
        keep = st.multiselect("Show", kinds, default=kinds)
        nodes = [n for n in nodes if n.get("kind", "dataset") in keep]
        per_layer: dict[int, int] = {}
        pos = {}
        for n in nodes:
            y = per_layer.get(n["layer"], 0)
            per_layer[n["layer"]] = y + 1
            pos[n["id"]] = (n["layer"], -y)
        fig = go.Figure()
        for e in edges:
            if e["from"] in pos and e["to"] in pos:
                (x0, y0), (x1, y1) = pos[e["from"]], pos[e["to"]]
                fig.add_scatter(x=[x0, x1], y=[y0, y1], mode="lines", line=dict(color="#bbb", width=1), hoverinfo="text",
                                text=f"{e.get('step')}: {e.get('rule', '')}", showlegend=False)
        fig.add_scatter(x=[pos[n["id"]][0] for n in nodes], y=[pos[n["id"]][1] for n in nodes], mode="markers+text",
                        text=[n["label"] for n in nodes], textposition="middle right", textfont=dict(size=10),
                        marker=dict(size=12, color=[LAYER_COLOR[n["layer"] % 5] for n in nodes]), showlegend=False,
                        hovertext=[str(n.get("metadata", {}).get("rules", ""))[:200] for n in nodes], hoverinfo="text")
        fig.update_layout(height=max(420, 22 * max(per_layer.values() or [1])), xaxis=dict(visible=False),
                          yaxis=dict(visible=False), margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, width="stretch")
        st.caption(f"raw → clean → dbt → KPI → insight · {len(g.get('nodes', []))} nodes, {len(edges)} edges · source: {b.source}")
    if b.trace_md:
        with st.expander("Trace report (Auditor)"):
            st.markdown(b.trace_md)
