import streamlit as st

from ..components.kpi_tile import tile
from ..data.loader import Bundle


def render(b: Bundle) -> None:
    st.subheader("Overview")
    cols = st.columns(3)
    for i, d in enumerate(b.kpi_defs):
        t = b.values[(b.values.kpi_id == d["id"]) & (b.values.dimension == "total")]
        with cols[i % 3]:
            tile(d, t)
    st.caption(f"source: {b.source}" + (f" / run {b.run_id}" if b.run_id else " (demo fixtures)"))
