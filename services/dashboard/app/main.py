"""Streamlit dashboard (BO6). Config-driven: no dataset-specific code. Run: streamlit run app/main.py"""
import streamlit as st

from app.api import gateway
from app.data import loader
from app.tabs import data_quality, explain, insights, kpi_explorer, lineage, overview

st.set_page_config(page_title="BIFlow", page_icon="📊", layout="wide")

runs = loader.runs_with_kpis()
with st.sidebar:
    st.title("BIFlow")
    options = (runs + ["(demo fixtures)"]) if runs else ["(demo fixtures)"]
    choice = st.selectbox("Run", options, format_func=lambda r: r if r.startswith("(") else loader.run_label(r),
                          help="Each run is a frozen result: the data, the config and every number at that time. "
                               "Switch runs to see another dataset or an earlier result.")
    sets = gateway.datasets()
    with st.expander("Add a dataset (same structure as an existing one)"):
        bases = [d["name"] for d in sets if d.get("available") and not d.get("uploaded")]
        if not bases:
            st.caption("gateway not reachable")
        else:
            base = st.selectbox("Same structure as", bases, index=bases.index("olist") if "olist" in bases else 0, key="up_base")
            tmpl = gateway.template(base)
            st.caption(f"Upload these {len(tmpl)} CSV files, with the same names and columns as '{base}':")
            st.code("\n".join(v["file"] for v in tmpl.values()), language=None)
            new_name = st.text_input("Name of the new dataset", placeholder="e.g. my_shop", key="up_name")
            files = st.file_uploader("CSV files", type="csv", accept_multiple_files=True, key="up_files")
            if st.button("Add dataset", disabled=not (new_name and files)):
                with st.spinner("checking and saving the files..."):
                    r = gateway.add_dataset(new_name.strip(), base, files)
                if r.get("ok"):
                    st.session_state["_new_ds"] = r["name"]
                    st.success(f"Added '{r['name']}' ({r['files']} files). It is now selected in 'Start a new run' below.")
                    st.rerun()
                else:
                    for err in r.get("errors", ["unknown error"]):
                        st.error(err)
    with st.expander("Start a new run", expanded=bool(st.session_state.get("_new_ds"))):
        if not sets:
            st.caption("gateway not reachable")
        else:
            names = [d["name"] for d in sets]
            info = {d["name"]: d for d in sets}
            default = st.session_state.get("_new_ds") or "olist_sample"
            ds = st.selectbox("Dataset", names, index=names.index(default) if default in names else 0,
                              format_func=lambda n: f"{n} ({info[n].get('domain')})" + (" · uploaded" if info[n].get("uploaded") else "")
                              + ("" if info[n]["available"] else " · data missing"),
                              help="One entry per configs/datasets/<name>.yaml: the config says where the files are, "
                                   "their columns, cleaning rules and KPIs.")
            if not info[ds]["available"]:
                st.warning(info[ds]["note"])
            if st.button("Run pipeline", disabled=not info[ds]["available"]):
                rid = gateway.start_run(ds)
                if rid:
                    st.success(f"started: refresh in a minute or two (run {rid})")
                else:
                    st.error("gateway not reachable")
bundle = loader.load(None if choice.startswith("(") else choice)
st.sidebar.caption(f"data source: {bundle.source}" + (f" · run {bundle.run_id}" if bundle.run_id else ""))

st.title(bundle.config.get("title", "BIFlow"))
tabs = st.tabs(["Overview", "KPI explorer", "Insights and actions", "Data quality", "Lineage", "Explain"])
for tab, mod in zip(tabs, [overview, kpi_explorer, insights, data_quality, lineage, explain], strict=True):
    with tab:
        mod.render(bundle)
