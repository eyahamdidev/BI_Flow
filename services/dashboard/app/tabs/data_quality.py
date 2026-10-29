import pandas as pd
import streamlit as st

from ..components.charts import bars
from ..data.loader import Bundle


def render(b: Bundle) -> None:
    st.subheader("Data quality (before / after cleaning)")
    q = b.quality or {}
    if not q.get("before") or not q.get("after"):
        st.info("No quality score yet.")
        return
    c1, c2 = st.columns(2)
    c1.metric("Overall before cleaning", f"{q['before']['overall']:.1f}")
    c2.metric("Overall after cleaning", f"{q['after']['overall']:.1f}", f"{q['after']['overall'] - q['before']['overall']:+.1f}")
    dims = [k for k in q["before"] if k != "overall" and k in q["after"]]
    st.plotly_chart(bars(dims, [q["after"][k] - q["before"][k] for k in dims], "Change after cleaning, by dimension (points)", b.source),
                    use_container_width=True)
    st.dataframe(pd.DataFrame({"dimension": dims, "before": [q["before"][k] for k in dims], "after": [q["after"][k] for k in dims]}),
                 hide_index=True, use_container_width=True)
    if q.get("tables_after"):
        with st.expander("Per table (after cleaning)"):
            st.dataframe(pd.DataFrame(q["tables_after"]).T, use_container_width=True)
    if b.profile_diff_md:
        with st.expander("Profile before → after (cleaning evidence)"):
            st.markdown(b.profile_diff_md)
