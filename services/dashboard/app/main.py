"""Streamlit dashboard (BO6). Config-driven: no dataset-specific code. Run: streamlit run app/main.py"""
import streamlit as st

from app.data import loader
from app.tabs import data_quality, explain, insights, kpi_explorer, lineage, overview

st.set_page_config(page_title="BIFlow", page_icon="📊", layout="wide")
st.title("BIFlow")

runs = loader.list_runs()
choice = st.sidebar.selectbox("Run", ["(demo fixtures)"] + runs)
bundle = loader.load(None if choice.startswith("(") else choice)
st.sidebar.caption(f"data source: {bundle.source}")

tabs = st.tabs(["Overview", "KPI explorer", "Insights and actions", "Data quality", "Lineage", "Explain"])
for tab, mod in zip(tabs, [overview, kpi_explorer, insights, data_quality, lineage, explain], strict=True):
    with tab:
        mod.render(bundle)
