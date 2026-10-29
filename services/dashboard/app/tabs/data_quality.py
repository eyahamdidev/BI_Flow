import streamlit as st

from ..components.charts import bars
from ..data.loader import Bundle


def render(b: Bundle) -> None:
    st.subheader("Data quality (before / after cleaning)")
    q = b.quality or {}
    if not q:
        st.info("No quality score yet.")
        return
    c1, c2 = st.columns(2)
    c1.metric("Overall before", f"{q['before']['overall']:.1f}")
    c2.metric("Overall after", f"{q['after']['overall']:.1f}", f"{q['after']['overall'] - q['before']['overall']:+.1f}")
    dims = [k for k in q["before"] if k != "overall"]
    st.plotly_chart(bars(dims, [q["after"][k] for k in dims], "After cleaning, by dimension", b.source), use_container_width=True)
