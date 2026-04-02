"""
dashboard.py - Chameleon Bot - Live Evidence Dashboard
streamlit run dashboard.py
"""

import json
from pathlib import Path

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

st.set_page_config(
    page_title="Chameleon | Smart Money Tracker",
    page_icon="🦎",
    layout="wide",
)

LOG_DIR = Path("logs")

MODE_COLORS = {
    "STEALTH": "#9b59b6",
    "CHASE":   "#e67e22",
    "ESCAPE":  "#e74c3c",
    "SLEEP":   "#95a5a6",
}


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except Exception:
                pass
    return records


# ── Header ───────────────────────────────────────────────────────────────────

st.markdown("""
<h1 style='font-size:2.2rem; margin-bottom:0'>🦎 Chameleon</h1>
<p style='color:#888; font-size:1rem; margin-top:4px'>
Smart Money Signal Tracker — Powered by Nansen API
</p>
""", unsafe_allow_html=True)

st.divider()

# ── Load data ─────────────────────────────────────────────────────────────────

api_records   = load_jsonl(LOG_DIR / "api_usage.jsonl")
decisions     = load_jsonl(LOG_DIR / "decisions.jsonl")
cycle_summary = load_jsonl(LOG_DIR / "cycle_summary.jsonl")

# ── KPI row ──────────────────────────────────────────────────────────────────

total_api   = len(api_records)
total_dec   = len(decisions)
total_cycle = len(cycle_summary)

non_sleep = sum(1 for d in decisions if d.get("mode") != "SLEEP")

k1, k2, k3, k4 = st.columns(4)
k1.metric("Total API Calls", total_api, help="Holdings + Netflow calls to Nansen")
k2.metric("Tokens Analyzed", total_dec)
k3.metric("Cycles Complete", total_cycle)
k4.metric("Signals (non-SLEEP)", non_sleep)

st.divider()

# ── API call proof ────────────────────────────────────────────────────────────

st.subheader("API Call Proof")
st.caption("Live evidence of Nansen API usage — each row is a verified call")

if api_records:
    df_api = pd.DataFrame(api_records)
    df_api = df_api[["timestamp", "cycle_id", "endpoint", "token", "status_code", "used_in_decision"]].copy()
    df_api["token"] = df_api["token"].str[:16]
    df_api["status"] = df_api["status_code"].apply(
        lambda x: "✅ 200" if x == 200 else f"❌ {x}"
    )
    df_api = df_api.drop(columns=["status_code"])

    # highlight the latest cycle
    if cycle_summary:
        latest_cycle = cycle_summary[-1]["cycle_id"]
        st.markdown(f"**Latest cycle:** `{latest_cycle}` — "
                    f"**{sum(1 for r in api_records if r.get('cycle_id') == latest_cycle)} calls**")

    st.dataframe(df_api.tail(30)[::-1], use_container_width=True, height=280)
else:
    st.info("No API calls recorded yet. Run `python chameleon.py` to start.")

st.divider()

# ── Decision log ─────────────────────────────────────────────────────────────

col_left, col_right = st.columns([2, 1])

with col_left:
    st.subheader("Decision Log")
    if decisions:
        df_dec = pd.DataFrame(decisions)
        df_dec["mode_label"] = df_dec["mode"].apply(
            lambda m: f"{'🟣' if m=='STEALTH' else '🟠' if m=='CHASE' else '🔴' if m=='ESCAPE' else '⚫'} {m}"
        )
        show_cols = ["timestamp", "token", "mode_label", "action", "confidence", "reason"]
        df_dec["token"] = df_dec["token"].str[:16]
        df_dec["reason"] = df_dec["reason"].str[:60]
        st.dataframe(df_dec[show_cols].tail(20)[::-1], use_container_width=True, height=320)
    else:
        st.info("No decisions yet.")

with col_right:
    st.subheader("Mode Distribution")
    if decisions:
        df_dec2 = pd.DataFrame(decisions)
        counts = df_dec2["mode"].value_counts().reset_index()
        counts.columns = ["mode", "count"]
        colors = [MODE_COLORS.get(m, "#888") for m in counts["mode"]]
        fig = px.pie(
            counts, names="mode", values="count",
            color="mode",
            color_discrete_map=MODE_COLORS,
            hole=0.45,
        )
        fig.update_traces(textinfo="label+percent")
        fig.update_layout(
            showlegend=False,
            margin=dict(t=10, b=10, l=10, r=10),
            height=300,
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No data.")

st.divider()

# ── Cycle summary ─────────────────────────────────────────────────────────────

st.subheader("Cycle Summary")
if cycle_summary:
    df_cyc = pd.DataFrame(cycle_summary)

    # bar chart of api_calls per cycle
    fig2 = go.Figure()
    fig2.add_bar(
        x=df_cyc["cycle_id"],
        y=df_cyc["api_calls"],
        marker_color="#3498db",
        name="API calls",
    )
    # overlay mode counts
    for mode, color in MODE_COLORS.items():
        vals = df_cyc["mode_counts"].apply(lambda mc: mc.get(mode, 0) if isinstance(mc, dict) else 0)
        fig2.add_bar(x=df_cyc["cycle_id"], y=vals, name=mode, marker_color=color)

    fig2.update_layout(
        barmode="group",
        xaxis_title="Cycle",
        yaxis_title="Count",
        legend_title="",
        height=300,
        margin=dict(t=10, b=40, l=40, r=10),
    )
    st.plotly_chart(fig2, use_container_width=True)

    st.dataframe(df_cyc.tail(10)[::-1], use_container_width=True, height=200)
else:
    st.info("No cycle data yet.")

st.divider()

# ── Footer ────────────────────────────────────────────────────────────────────

st.markdown("""
<p style='color:#666; font-size:0.85rem; text-align:center'>
Chameleon Bot &nbsp;|&nbsp; Smart Money on Solana &nbsp;|&nbsp;
Data: <a href='https://nansen.ai' target='_blank'>Nansen API</a>
</p>
""", unsafe_allow_html=True)
