"""
dashboard.py - Chameleon Bot v2 - Live Evidence Dashboard
streamlit run dashboard.py

v2 additions:
  - Quality Gate score distribution
  - Schema Registry health panel
  - Integrity & monitoring metrics
"""

import json
from pathlib import Path

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from json_registry import (
    JSON_REGISTRY,
    MONITORING_METRICS,
    INTEGRITY_CONSTRAINTS,
    LAYER_ARCHITECTURE,
    JsonCategory,
)
from schema_manager import get_manager as get_schema_manager

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

CATEGORY_COLORS = {
    "ARTIFACT":      "#e74c3c",
    "CORE_SCHEMA":   "#3498db",
    "RUNTIME_STATE": "#2ecc71",
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


# ── Header ────────────────────────────────────────────────────────────────────

st.markdown("""
<h1 style='font-size:2.2rem; margin-bottom:0'>🦎 Chameleon v2</h1>
<p style='color:#888; font-size:1rem; margin-top:4px'>
Smart Money Signal Tracker — Powered by Nansen API &nbsp;|&nbsp;
JSON Registry · 14-point Quality Gate · Schema Governance
</p>
""", unsafe_allow_html=True)

st.divider()

# ── Load data ─────────────────────────────────────────────────────────────────

api_records   = load_jsonl(LOG_DIR / "api_usage.jsonl")
decisions     = load_jsonl(LOG_DIR / "decisions.jsonl")
cycle_summary = load_jsonl(LOG_DIR / "cycle_summary.jsonl")

# ── KPI row ───────────────────────────────────────────────────────────────────

total_api   = len(api_records)
total_dec   = len(decisions)
total_cycle = len(cycle_summary)
non_sleep   = sum(1 for d in decisions if d.get("mode") != "SLEEP")

quality_scores = [d.get("quality_score") for d in decisions if d.get("quality_score") is not None]
quality_avg    = round(sum(quality_scores) / len(quality_scores), 1) if quality_scores else None

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Total API Calls",     total_api,   help="Holdings + Netflow calls to Nansen")
k2.metric("Tokens Analyzed",     total_dec)
k3.metric("Cycles Complete",     total_cycle)
k4.metric("Signals (non-SLEEP)", non_sleep)
k5.metric(
    "Quality Gate Avg",
    f"{quality_avg}/14" if quality_avg is not None else "—",
    help="Average 14-point quality gate score across all decisions",
)

st.divider()

# ── Tabs ──────────────────────────────────────────────────────────────────────

tab_signals, tab_quality, tab_registry, tab_arch = st.tabs([
    "📊 Signals & API", "🎯 Quality Gate", "🗂 Schema Registry", "🏗 Architecture",
])

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1: Signals & API (original dashboard content)
# ═══════════════════════════════════════════════════════════════════════════════

with tab_signals:
    st.subheader("API Call Proof")
    st.caption("Live evidence of Nansen API usage — each row is a verified call")

    if api_records:
        df_api = pd.DataFrame(api_records)
        cols = [c for c in ["timestamp", "cycle_id", "endpoint", "token", "status_code", "used_in_decision"] if c in df_api.columns]
        df_api = df_api[cols].copy()
        df_api["token"] = df_api["token"].str[:16]
        if "status_code" in df_api.columns:
            df_api["status"] = df_api["status_code"].apply(
                lambda x: "✅ 200" if x == 200 else f"❌ {x}"
            )
            df_api = df_api.drop(columns=["status_code"])

        if cycle_summary:
            latest_cycle = cycle_summary[-1]["cycle_id"]
            n_latest = sum(1 for r in api_records if r.get("cycle_id") == latest_cycle)
            st.markdown(f"**Latest cycle:** `{latest_cycle}` — **{n_latest} calls**")

        st.dataframe(df_api.tail(30)[::-1], use_container_width=True, height=280)
    else:
        st.info("No API calls recorded yet. Run `python chameleon.py` to start.")

    st.divider()

    col_left, col_right = st.columns([2, 1])

    with col_left:
        st.subheader("Decision Log")
        if decisions:
            df_dec = pd.DataFrame(decisions)
            df_dec["mode_label"] = df_dec["mode"].apply(
                lambda m: f"{'🟣' if m=='STEALTH' else '🟠' if m=='CHASE' else '🔴' if m=='ESCAPE' else '⚫'} {m}"
            )
            df_dec["token"] = df_dec["token"].str[:16]
            df_dec["reason"] = df_dec["reason"].str[:55]
            show = ["timestamp", "token", "mode_label", "action", "confidence", "quality_score", "reason"]
            show = [c for c in show if c in df_dec.columns]
            st.dataframe(df_dec[show].tail(20)[::-1], use_container_width=True, height=340)
        else:
            st.info("No decisions yet.")

    with col_right:
        st.subheader("Mode Distribution")
        if decisions:
            df_dec2  = pd.DataFrame(decisions)
            counts   = df_dec2["mode"].value_counts().reset_index()
            counts.columns = ["mode", "count"]
            fig = px.pie(
                counts, names="mode", values="count",
                color="mode", color_discrete_map=MODE_COLORS, hole=0.45,
            )
            fig.update_traces(textinfo="label+percent")
            fig.update_layout(showlegend=False, margin=dict(t=10, b=10, l=10, r=10), height=300)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No data.")

    st.divider()

    st.subheader("Cycle Summary")
    if cycle_summary:
        df_cyc = pd.DataFrame(cycle_summary)
        fig2   = go.Figure()
        fig2.add_bar(x=df_cyc["cycle_id"], y=df_cyc["api_calls"], marker_color="#3498db", name="API calls")
        for mode, color in MODE_COLORS.items():
            vals = df_cyc["mode_counts"].apply(
                lambda mc: mc.get(mode, 0) if isinstance(mc, dict) else 0
            )
            fig2.add_bar(x=df_cyc["cycle_id"], y=vals, name=mode, marker_color=color)
        fig2.update_layout(
            barmode="group", xaxis_title="Cycle", yaxis_title="Count",
            legend_title="", height=300, margin=dict(t=10, b=40, l=40, r=10),
        )
        st.plotly_chart(fig2, use_container_width=True)
        st.dataframe(df_cyc.tail(10)[::-1], use_container_width=True, height=200)
    else:
        st.info("No cycle data yet.")

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2: Quality Gate Analysis
# ═══════════════════════════════════════════════════════════════════════════════

with tab_quality:
    st.subheader("14-Point Quality Gate")
    st.caption(
        "Each signal is evaluated across 14 gates (0–14 points). "
        "BUY requires ≥ 10/14 · SELL requires ≥ 8/14 · SLEEP always passes."
    )

    gate_descriptions = {
        "QG-01": "Data Completeness — holdings + netflow arrays present",
        "QG-02": "API Data Validity — both data arrays non-empty",
        "QG-03": "SM Holder Minimum — SM holder count ≥ 1",
        "QG-04": "Flow Direction Clarity — netflow matches mode direction",
        "QG-05": "Flow Magnitude — |netflow_1h| > $10",
        "QG-06": "SM Concentration — share_of_holdings > 0%",
        "QG-07": "Trader Activity — trader_count ≥ 1",
        "QG-08": "Confidence Threshold — strategy confidence ≥ 0.55",
        "QG-09": "Cooldown Compliance — token not in active cooldown",
        "QG-10": "Blacklist Clear — token not blacklisted",
        "QG-11": "Risk Capacity — daily halt not active",
        "QG-12": "Schema Consistency — all required API fields present",
        "QG-13": "Mode-Signal Alignment — mode logically consistent with data",
        "QG-14": "Signal Strength — meets mode-specific strength threshold",
    }

    # Gate reference table
    with st.expander("Gate Reference (click to expand)", expanded=False):
        gate_df = pd.DataFrame([
            {"Gate": k, "Description": v, "Weight": "1 pt"}
            for k, v in gate_descriptions.items()
        ])
        st.dataframe(gate_df, use_container_width=True, hide_index=True)

    st.divider()

    if quality_scores:
        col_a, col_b = st.columns(2)

        with col_a:
            st.markdown("**Score Distribution**")
            fig_hist = px.histogram(
                x=quality_scores, nbins=15,
                labels={"x": "Quality Score (0–14)", "count": "Decisions"},
                color_discrete_sequence=["#3498db"],
            )
            fig_hist.add_vline(x=10, line_dash="dash", line_color="#e74c3c",
                               annotation_text="BUY min (10)", annotation_position="top right")
            fig_hist.add_vline(x=8,  line_dash="dash", line_color="#e67e22",
                               annotation_text="SELL min (8)", annotation_position="top left")
            fig_hist.update_layout(height=300, margin=dict(t=30, b=40, l=40, r=10))
            st.plotly_chart(fig_hist, use_container_width=True)

        with col_b:
            st.markdown("**Score by Mode**")
            if decisions:
                df_qm = pd.DataFrame([
                    {"mode": d.get("mode", "?"), "quality_score": d.get("quality_score", 0)}
                    for d in decisions if d.get("quality_score") is not None
                ])
                fig_box = px.box(
                    df_qm, x="mode", y="quality_score",
                    color="mode", color_discrete_map=MODE_COLORS,
                    labels={"quality_score": "Quality Score", "mode": "Mode"},
                )
                fig_box.add_hline(y=10, line_dash="dash", line_color="#e74c3c")
                fig_box.add_hline(y=8,  line_dash="dash", line_color="#e67e22")
                fig_box.update_layout(height=300, margin=dict(t=10, b=40, l=40, r=10),
                                      showlegend=False)
                st.plotly_chart(fig_box, use_container_width=True)

        # Recent gate details
        st.markdown("**Recent Gate Details**")
        recent_with_gates = [d for d in decisions[-20:] if d.get("gate_details")]
        if recent_with_gates:
            latest = recent_with_gates[-1]
            gd = latest.get("gate_details", {})
            gate_rows = gd.get("gate_details", {})
            if gate_rows:
                rows = []
                for gid, info in gate_rows.items():
                    rows.append({
                        "Gate":    gid,
                        "Name":    info.get("name", ""),
                        "Result":  "✅" if info.get("passed") else "❌",
                        "Detail":  info.get("detail", ""),
                    })
                df_gates = pd.DataFrame(rows)
                token_short = latest.get("token", "")[:16]
                mode_label  = latest.get("mode", "")
                score       = gd.get("total_score", "?")
                st.caption(f"Showing gates for last analyzed token: `{token_short}` | mode={mode_label} | score={score}/14")
                st.dataframe(df_gates, use_container_width=True, hide_index=True, height=420)
        else:
            st.info("No gate details yet — run the bot to see quality evaluations.")

        # Quality trend
        if cycle_summary:
            df_cs    = pd.DataFrame(cycle_summary)
            has_qavg = "quality_avg" in df_cs.columns
            if has_qavg:
                st.markdown("**Quality Average per Cycle**")
                fig_trend = px.line(
                    df_cs, x="cycle_id", y="quality_avg",
                    labels={"quality_avg": "Avg Quality Score", "cycle_id": "Cycle"},
                    markers=True,
                )
                fig_trend.add_hline(y=10, line_dash="dash", line_color="#e74c3c",
                                    annotation_text="BUY min")
                fig_trend.update_layout(height=250, margin=dict(t=10, b=40, l=40, r=10))
                st.plotly_chart(fig_trend, use_container_width=True)
    else:
        st.info("No quality gate data yet. Run `python chameleon.py` to generate decisions.")

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 3: Schema Registry
# ═══════════════════════════════════════════════════════════════════════════════

with tab_registry:
    sm = get_schema_manager()

    st.subheader("JSON Schema Registry")
    st.caption(
        f"{len(JSON_REGISTRY)} JSON types registered · "
        f"ARTIFACT (immutable) · CORE_SCHEMA (versioned) · RUNTIME_STATE (volatile)"
    )

    # Registry status table
    status = sm.get_registry_status()
    rows   = []
    for jt, info in status.items():
        cat = info["category"]
        rows.append({
            "Type":        jt,
            "Category":    cat,
            "Version":     info["version"] or "—",
            "Path":        info["path"],
            "Exists":      "✅" if info["exists"] is True else ("—" if info["exists"] is None else "❌"),
            "Size (B)":    info["size_bytes"] if info["size_bytes"] is not None else "—",
            "Immutable":   "🔒" if info["immutable"] else "",
            "Description": info["description"][:60],
        })

    df_reg = pd.DataFrame(rows)
    st.dataframe(df_reg, use_container_width=True, hide_index=True, height=380)

    # Category breakdown
    col_c1, col_c2 = st.columns(2)

    with col_c1:
        st.markdown("**Category Distribution**")
        cat_counts = df_reg["Category"].value_counts().reset_index()
        cat_counts.columns = ["Category", "Count"]
        fig_cat = px.pie(
            cat_counts, names="Category", values="Count",
            color="Category",
            color_discrete_map=CATEGORY_COLORS,
            hole=0.4,
        )
        fig_cat.update_traces(textinfo="label+value")
        fig_cat.update_layout(showlegend=False, height=260, margin=dict(t=10, b=10, l=10, r=10))
        st.plotly_chart(fig_cat, use_container_width=True)

    with col_c2:
        st.markdown("**Schema Violations**")
        vc = sm.violation_count
        if vc == 0:
            st.success(f"0 violations detected")
        else:
            st.error(f"{vc} violation(s) detected")
            violations_df = pd.DataFrame(sm.violations)
            st.dataframe(violations_df, use_container_width=True, height=200)

    # Integrity constraints reference
    st.divider()
    st.markdown("**Integrity Constraints**")
    ic_rows = [
        {
            "ID":          c["id"],
            "Description": c["description"],
            "Severity":    c["severity"],
            "Scope":       ", ".join(c.get("json_types", [])),
        }
        for c in INTEGRITY_CONSTRAINTS
    ]
    st.dataframe(pd.DataFrame(ic_rows), use_container_width=True, hide_index=True)

    # Monitoring metrics reference
    st.divider()
    st.markdown("**Monitoring Metrics**")
    metric_rows = [
        {
            "Metric":      k,
            "Description": v["description"],
            "Target":      v["target"],
            "Source":      v["source"],
        }
        for k, v in MONITORING_METRICS.items()
    ]
    st.dataframe(pd.DataFrame(metric_rows), use_container_width=True, hide_index=True)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 4: Architecture
# ═══════════════════════════════════════════════════════════════════════════════

with tab_arch:
    st.subheader("Layer Architecture")
    st.caption(
        "レイヤー逆参照禁止: 上位レイヤーは下位レイヤーの入力スキーマを直接参照禁止"
    )

    for layer_id in sorted(LAYER_ARCHITECTURE.keys()):
        components = LAYER_ARCHITECTURE[layer_id]
        arrow      = "↓" if layer_id < max(LAYER_ARCHITECTURE.keys()) else ""
        label      = {
            0: "Layer 0 — Source",
            1: "Layer 1 — Runtime State",
            2: "Layer 2 — Signal Detection",
            3: "Layer 3 — Decision",
            4: "Layer 4 — Audit Log (ARTIFACT)",
            5: "Layer 5 — Dashboard (read-only)",
        }.get(layer_id, f"Layer {layer_id}")

        with st.container():
            col_l, col_r = st.columns([1, 3])
            col_l.markdown(f"**{label}**")
            col_r.markdown(" · ".join(f"`{c}`" for c in components))
        if arrow:
            st.markdown(f"<p style='text-align:center; color:#888; font-size:1.4rem'>{arrow}</p>",
                        unsafe_allow_html=True)

    st.divider()
    st.markdown("**Version Strategy**")
    vrow = [
        {"Category": "ARTIFACT",      "Strategy": "Timestamp", "Example": "logs/*.jsonl",      "Rule": "Append-only, never overwrite"},
        {"Category": "CORE_SCHEMA",   "Strategy": "SemVer",    "Example": "cache/universe.json","Rule": "Major bump on breaking change"},
        {"Category": "RUNTIME_STATE", "Strategy": "Timestamp", "Example": "Nansen API response","Rule": "Overwrite each cycle, no retention"},
    ]
    st.dataframe(pd.DataFrame(vrow), use_container_width=True, hide_index=True)

    st.divider()
    st.markdown("**JSON Registry Summary**")
    summary_rows = []
    for jt, schema in JSON_REGISTRY.items():
        summary_rows.append({
            "Type":            jt,
            "Category":        schema.category.value,
            "Version":         schema.version or "—",
            "Generated by":    ", ".join(schema.generated_by) or "—",
            "Read by":         ", ".join(schema.read_modules) or "—",
            "Depends on":      ", ".join(schema.dependencies) or "—",
        })
    st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True, height=350)

# ── Footer ────────────────────────────────────────────────────────────────────

st.divider()
st.markdown("""
<p style='color:#666; font-size:0.85rem; text-align:center'>
Chameleon v2 &nbsp;|&nbsp; Smart Money on Solana &nbsp;|&nbsp;
Data: <a href='https://nansen.ai' target='_blank'>Nansen API</a> &nbsp;|&nbsp;
JSON Registry · 14-pt Quality Gate · Schema Governance
</p>
""", unsafe_allow_html=True)
