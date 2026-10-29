import streamlit as st

from ..api import gateway
from ..data.loader import Bundle


def render(b: Bundle) -> None:
    st.subheader("Explain this KPI")
    names = {d["id"]: d["name"] for d in b.kpi_defs}
    q = st.text_input("Ask in your own words (optional)", placeholder="e.g. why did sales change in March?")
    if q and b.run_id and st.session_state.get("_asked") != q:
        st.session_state["_asked"] = q
        r = gateway.ask(b.run_id, q)
        if r and r.get("status") == "ok" and r["metrics"].get("kpi_id") in names:
            st.session_state["ex_kpi"] = r["metrics"]["kpi_id"]
            st.caption(f"understood as **{names[r['metrics']['kpi_id']]}** ({r['metrics'].get('method')})")
    c1, c2 = st.columns(2)
    kid = c1.selectbox("KPI", list(names), format_func=names.get, key="ex_kpi")
    periods = sorted(b.values[(b.values.kpi_id == kid) & (b.values.dimension == "total")].period.unique())
    period = c2.selectbox("Month", periods, index=len(periods) - 1, key="ex_period")
    if st.button("Explain"):
        resp = gateway.explain(b.run_id, kid, period) if b.run_id else None
        if not resp or resp.get("status") not in ("ok", "partial"):
            msg = ((resp or {}).get("error") or {}).get("message")
            st.warning(msg or "Gateway or run not available (demo fixtures have no run to explain).")
            return
        m = resp.get("metrics", {})
        st.write(m.get("answer", "(no answer)"))
        st.caption("written by the Auditor from logged facts only (definition, lineage, driver decomposition); numbers fact-checked")
        for item in m.get("citations") or []:
            with st.expander(item.get("sentence") or item.get("frame") or "Logged fact"):
                for fact in item.get("facts") or []:
                    value = fact.get("value")
                    st.markdown(f"`{fact.get('fact_id')}` = {value if value is not None else 'not logged'}")
                    if fact.get("sql"):
                        st.code(fact["sql"], language="sql")
                    tables = fact.get("source_tables") or []
                    if tables:
                        st.write("Source tables: " + ", ".join(map(str, tables)))
