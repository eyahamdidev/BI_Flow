import streamlit as st

from ..components.charts import trend
from ..data.loader import Bundle


def render(b: Bundle) -> None:
    st.subheader("KPI explorer")
    names = {d["id"]: d["name"] for d in b.kpi_defs}
    kid = st.selectbox("KPI", list(names), format_func=names.get)
    d = next(x for x in b.kpi_defs if x["id"] == kid)
    st.write(d.get("description", ""))
    dims = ["total"] + [x for x in d.get("dimensions", []) if x in set(b.values.dimension)]
    dim = st.radio("Break down by", dims, horizontal=True)
    v = b.values[(b.values.kpi_id == kid) & (b.values.dimension == dim)]
    periods = sorted(v.period.unique())
    lo, hi = st.select_slider("Period range", options=periods, value=(periods[0], periods[-1]))
    v = v[(v.period >= lo) & (v.period <= hi)]
    anomalies = [i["period"] for i in b.insights if i["kpi_id"] == kid and i["type"] == "anomaly"]
    st.plotly_chart(trend(v, d["name"], d.get("unit", ""), anomalies, b.source), use_container_width=True)
