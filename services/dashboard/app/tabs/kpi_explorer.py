import pandas as pd
import streamlit as st

from ..components.charts import bars, trend
from ..components.kpi_tile import fmt
from ..data.loader import Bundle


def render(b: Bundle) -> None:
    st.subheader("KPI explorer")
    names = {d["id"]: d["name"] for d in b.kpi_defs}
    kid = st.selectbox("KPI", list(names), format_func=names.get)
    d = next(x for x in b.kpi_defs if x["id"] == kid)
    unit = d.get("unit", "")
    st.write(d.get("description", ""))
    if d.get("caveats"):
        st.caption(f"Caveat: {d['caveats']}")
    chart = next((c for c in b.config.get("charts", []) if c["type"] == "trend" and c["kpi_id"] == kid), {})
    kv = b.values[b.values.kpi_id == kid]
    dims = ["total"] + [x for x in d.get("dimensions", []) if x in set(kv.dimension)]
    dim = st.radio("Break down by", dims, horizontal=True)
    v = kv[kv.dimension == dim]
    if dim != "total":  # keep the chart readable: top 6 segments by size
        top = v.groupby("dimension_value")["value"].sum().abs().nlargest(6).index
        v = v[v.dimension_value.isin(top)]
    periods = sorted(v.period.unique())
    if not periods:
        st.info("No values.")
        return
    lo, hi = st.select_slider("Period range", options=periods, value=(periods[0], periods[-1]))
    v = v[(v.period >= lo) & (v.period <= hi)]
    anomalies = chart.get("anomaly_periods") or [i["period"] for i in b.insights if i["kpi_id"] == kid and i["type"] == "anomaly"]
    st.plotly_chart(trend(v, d["name"], unit, anomalies, b.source), use_container_width=True)
    if chart.get("incomplete_periods"):
        st.caption("Incomplete months (too few orders, excluded from trends and anomalies): " + ", ".join(chart["incomplete_periods"]))

    rows = [r for r in (b.drivers.get("drivers") or []) if r["kpi_id"] == kid]
    if not rows:
        return
    st.markdown("**Why did it move?** Change vs the previous complete month, split by segment (the parts sum to the total change).")
    per = sorted({r["period"] for r in rows})
    p = st.selectbox("Month", per, index=len(per) - 1, key="drv_period")
    opts = [r for r in rows if r["period"] == p]
    pick = st.radio("Split by", [x["dimension"] for x in opts], horizontal=True, key="drv_dim")
    r = next(x for x in opts if x["dimension"] == pick)
    st.write(f"{d['name']}: {fmt(r['value_prev'], unit)} in {r['compare_to']} → {fmt(r['value_t'], unit)} in {p} "
             f"(change {fmt(r['total_delta'], unit)})")
    c = pd.DataFrame(r["contributions"])
    st.plotly_chart(bars(c["dimension_value"].astype(str).tolist()[:10], c["delta"].tolist()[:10],
                         f"Contribution to the change, by {r['dimension']}", b.source), use_container_width=True)
    with st.expander("table"):
        st.dataframe(c, hide_index=True, use_container_width=True)
