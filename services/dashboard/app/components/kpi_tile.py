from __future__ import annotations

import pandas as pd
import streamlit as st


def fmt(v: float | None, unit: str) -> str:
    if v is None:
        return "n/a"
    if unit == "ratio":
        return f"{v * 100:.1f}%"
    if unit in ("BRL",):
        return f"R$ {v:,.0f}"
    return f"{v:,.2f}" if abs(v) < 100 else f"{v:,.0f}"


def tile(defn: dict, total: pd.DataFrame) -> None:
    s = total.sort_values("period")
    if len(s) < 2:
        return
    cur, prev = float(s["value"].iloc[-1]), float(s["value"].iloc[-2])
    delta = (cur - prev) / prev * 100 if prev else 0.0
    good_up = defn.get("direction") != "lower_is_better"
    st.metric(defn["name"], fmt(cur, defn.get("unit", "")), f"{delta:+.1f}% vs prev", delta_color="normal" if good_up else "inverse")
    st.line_chart(s.set_index("period")["value"], height=60)
