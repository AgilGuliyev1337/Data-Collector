#!/usr/bin/env python3
"""
Data Collector — minimal web interfeys (Streamlit)

Ishletme:
    .venv/bin/streamlit run app.py --server.port 8501

Sorghi yaz, neticeni cedvedelde gor, JSON-i ac.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import streamlit as st
import json

from collector.db.connection import get_connection
from collector.db import repository
from collector.orchestrator import run_query

st.set_page_config(page_title="Data Collector", layout="wide")
st.title("Data Collector")
st.caption("Natural dil ile sorghi sorush - melumatlari bir an ichinde tap.")

# ------------------------------------------------------------------
# Sidebar - ilkin melumatlar
# ------------------------------------------------------------------
with st.sidebar:
    st.header("Parametrler")
    current_year = st.number_input("Il referens", min_value=2000, max_value=2030, value=2025, step=1)

    if st.button("Menbeleri yenile", use_container_width=True):
        conn = get_connection()
        repository.ensure_static_sources(conn)
        conn.commit()
        sources = repository.list_sources(conn)
        conn.close()
        st.success(f"{len(sources)} menbe yuklendi")

# ------------------------------------------------------------------
# Sorghi girişi
# ------------------------------------------------------------------
query_text = st.text_input(
    "Sorush",
    placeholder='məs: "Azerbaijan salary 2020" və ya "ÜDM artımı"',
)

if st.button("Sorghi islet", type="primary", disabled=not query_text):
    conn = get_connection()
    repository.ensure_static_sources(conn)
    conn.commit()

    with st.spinner("Melumat toplanir..."):
        try:
            result = run_query(conn, query_text, current_year=current_year)
            conn.commit()
            st.session_state.result = result
        except Exception as e:
            conn.rollback()
            st.error(f"Sorgu xetasi: {e}")
            conn.close()
            st.stop()

    conn.close()

# ------------------------------------------------------------------
# Netice gostermə
# ------------------------------------------------------------------
r = st.session_state.get("result")

if r is None:
    st.info("Yuxarida sorghunuzu yazib \"Sorghi islet\" dimeesine bashn.")
    st.stop()

# Üst xett: xulasə
col1, col2, col3 = st.columns(3)
col1.metric("Nöqtə", r["metadata"]["total_points"])
col2.metric("Etibarli", r["metadata"]["valid_points"])
col3.metric("Keyfiyyət", r["cross_source_quality"]["quality"].upper())

st.divider()

# Parsed info
st.subheader("Parsed")
st.json(r["parsed"], expanded=False)

# Netice cedveli
if r["results"]:
    st.subheader("Neticeler")
    import pandas as pd

    rows = []
    for item in r["results"]:
        rows.append({
            "Indicator": item.get("indicator_code", ""),
            "Menbe": item.get("source_id", ""),
            "Olkə": item.get("country", ""),
            "Dövr": item.get("period", item.get("year", "")),
            "Deyer": item.get("value", ""),
            "Status": item.get("status", ""),
        })
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    # JSON toggle
    with st.expander("Tam JSON cavab", expanded=False):
        st.json(r, default_closed=True)
else:
    st.info("Hech bir netice tapilmadi. Daha spesifik sorghi sınayın.")