import streamlit as st

from ..data.loader import Bundle
from ..theme import SEVERITY


def render(b: Bundle) -> None:
    st.subheader("Insights and actions")
    if not b.insights:
        st.info("No insights yet. Run the pipeline first.")
    for i in b.insights:
        color = SEVERITY.get(i.get("severity", "info"), "#999")
        with st.container(border=True):
            st.markdown(f"<span style='color:{color};font-weight:700'>{i['severity'].upper()}</span> · {i['type']} · `{i['kpi_id']}` · {i.get('period') or ''}", unsafe_allow_html=True)
            st.write(i.get("narrative", ""))
            with st.expander("facts and trace"):
                st.json({"facts": i.get("facts"), "rule_id": i.get("rule_id"), "source": i.get("source")})
