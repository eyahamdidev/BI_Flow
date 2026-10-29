import streamlit as st

from ..api import gateway
from ..data.loader import Bundle


def render(b: Bundle) -> None:
    st.subheader("Explain this KPI")
    names = {d["id"]: d["name"] for d in b.kpi_defs}
    c1, c2 = st.columns(2)
    kid = c1.selectbox("KPI", list(names), format_func=names.get, key="ex_kpi")
    periods = sorted(b.values[b.values.kpi_id == kid].period.unique())
    period = c2.selectbox("Period", periods, index=len(periods) - 1, key="ex_period")
    if st.button("Explain"):
        resp = gateway.explain(b.run_id, kid, period) if b.run_id else None
        if resp and resp.get("status") in ("ok", "partial"):
            m = resp.get("metrics", {})
            st.write(m.get("answer", "(no answer)"))
            st.caption("answered by the Auditor from logged facts only")
        else:
            st.info("Gateway or run not available: offline demo answer.")
            st.write(f"{names[kid]} for {period}: demo text. With a real run this is written by the Auditor from the lineage path and the driver decomposition.")
            return
        citations = (resp.get("metrics") or {}).get("citations") or []
        if not citations:
            return
        st.caption("Each sentence opens to the logged fact id, value, lineage event, SQL, and source tables.")
        for item in citations:
            title = item.get("sentence") or item.get("frame") or "Logged fact"
            with st.expander(title):
                facts = item.get("facts") or []
                if not facts:
                    st.caption("No fact id was declared for this sentence.")
                    continue
                for fact in facts:
                    value = fact.get("value")
                    st.markdown(f"`{fact.get('fact_id')}` = {value if value is not None else 'not logged'}")
                    st.write(f"Lineage event: {fact.get('lineage_event') or 'not logged'}")
                    st.write(f"SQL: {fact.get('sql') or 'not logged'}")
                    tables = fact.get("source_tables") or []
                    st.write("Source tables: " + (", ".join(str(table) for table in tables) if tables else "not logged"))
