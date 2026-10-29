"""Streamlit dashboard (BO6). Config-driven: no dataset-specific code. Run: streamlit run app/main.py"""
import streamlit as st

from app.api import gateway
from app.data import loader
from app.tabs import data_quality, explain, insights, kpi_explorer, lineage, overview

st.set_page_config(page_title="BIFlow", page_icon="📊", layout="wide")

runs = loader.runs_with_kpis()
with st.sidebar:
    st.title("BIFlow")
    choice = st.selectbox("Run", (runs + ["(demo fixtures)"]) if runs else ["(demo fixtures)"])
    with st.expander("Start a new run"):
        ds = st.text_input("Dataset", "olist_sample")
        if st.button("Run pipeline"):
            rid = gateway.start_run(ds)
            if rid:
                st.success(f"started run {rid}: refresh in a minute")
            else:
                st.error("gateway not reachable")
bundle = loader.load(None if choice.startswith("(") else choice)
st.sidebar.caption(f"data source: {bundle.source}" + (f" · run {bundle.run_id}" if bundle.run_id else ""))

st.title(bundle.config.get("title", "BIFlow"))
tabs = st.tabs(["Overview", "KPI explorer", "Insights and actions", "Data quality", "Lineage", "Explain"])
for tab, mod in zip(tabs, [overview, kpi_explorer, insights, data_quality, lineage, explain], strict=True):
    with tab:
        mod.render(bundle)
