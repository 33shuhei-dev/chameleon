"""
pl_analyzer.py - 損益計算書アナライザー
初心者でも損益計算書が理解できる財務分析ツール

機能:
  - 複数年の手入力（表形式エディタ）
  - EDINET API連携（企業名で検索して有報からP/Lを自動取得）
  - デモデータ（キーなしで全機能を試せる）
  - 総合スコア（100点満点）＋強み/弱み/課題/改善アクション
  - 複数年トレンド分析・2社比較モード
"""

import os

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import edinet_client
from pl_core import (
    BENCHMARKS, DEMO_COMPANIES, METRIC_EXPLANATIONS, METRIC_LABELS, PERIOD_FIELDS,
    calc_all, compare_companies, generate_analysis, score_company, yoy_change,
)

st.set_page_config(page_title="損益計算書アナライザー", page_icon="📊", layout="wide")

# ── 定数・ヘルパー ─────────────────────────────────────────────────────────────

COL_LABELS = {k: v for k, v in PERIOD_FIELDS}          # field → 日本語列名
LABEL_COLS = {v: k for k, v in PERIOD_FIELDS}          # 日本語列名 → field
DF_COLUMNS = [v for _, v in PERIOD_FIELDS]

DEFAULT_ROWS = {
    "A": [{"label": "2025年3月期", "revenue": 9_500,  "cogs": 5_800, "sga": 2_400, "non_op_income":  80, "non_op_expense": 180, "extra_gain": 0, "extra_loss": 0, "tax": 270},
          {"label": "2026年3月期", "revenue": 10_000, "cogs": 6_000, "sga": 2_500, "non_op_income": 100, "non_op_expense": 150, "extra_gain": 0, "extra_loss": 0, "tax": 300}],
    "B": [{"label": "2025年3月期", "revenue": 7_000,  "cogs": 4_500, "sga": 1_900, "non_op_income":  50, "non_op_expense": 100, "extra_gain": 0, "extra_loss": 0, "tax": 150},
          {"label": "2026年3月期", "revenue": 8_200,  "cogs": 5_200, "sga": 2_100, "non_op_income":  60, "non_op_expense": 110, "extra_gain": 0, "extra_loss": 0, "tax": 220}],
}


def periods_to_df(periods: list[dict]) -> pd.DataFrame:
    rows = [{COL_LABELS[k]: p.get(k) for k, _ in PERIOD_FIELDS} for p in periods]
    return pd.DataFrame(rows, columns=DF_COLUMNS)


def df_to_periods(df: pd.DataFrame) -> list[dict]:
    periods = []
    for _, row in df.iterrows():
        p = {}
        for col in DF_COLUMNS:
            field = LABEL_COLS[col]
            v = row.get(col)
            if field == "label":
                p[field] = str(v) if pd.notna(v) else ""
            else:
                try:
                    p[field] = float(v) if pd.notna(v) else 0.0
                except (TypeError, ValueError):
                    p[field] = 0.0
        if p.get("revenue", 0) > 0:
            periods.append(p)
    return periods


def init_slot(slot: str):
    if f"df_{slot}" not in st.session_state:
        st.session_state[f"df_{slot}"] = periods_to_df(DEFAULT_ROWS[slot])
    st.session_state.setdefault(f"editor_ver_{slot}", 0)
    st.session_state.setdefault(f"name_{slot}", "会社" + slot)
    st.session_state.setdefault(f"industry_{slot}", "製造業")


def apply_pending(slot: str):
    """デモ/EDINET取り込みは widget 生成前に session_state へ反映する必要がある."""
    pending = st.session_state.pop(f"pending_{slot}", None)
    if not pending:
        return
    if "df" in pending:
        st.session_state[f"df_{slot}"] = pending["df"]
        st.session_state[f"editor_ver_{slot}"] += 1  # エディタを作り直して反映
    if "name" in pending:
        st.session_state[f"name_{slot}"] = pending["name"]
    if "industry" in pending:
        st.session_state[f"industry_{slot}"] = pending["industry"]


# ── 入力UI ────────────────────────────────────────────────────────────────────

def render_company_input(slot: str, unit: str) -> dict:
    """1社分の入力UI。{name, industry, periods} を返す."""
    init_slot(slot)
    apply_pending(slot)

    name = st.text_input("会社名", key=f"name_{slot}")
    industry = st.selectbox("業種（ベンチマーク比較用）", list(BENCHMARKS.keys()), key=f"industry_{slot}")

    tab_manual, tab_edinet, tab_demo = st.tabs(["✍️ 手入力", "🌐 EDINETから取得", "🎲 デモデータ"])

    # ── 手入力（表エディタ・行追加で複数年）─────────────────────────────────
    with tab_manual:
        st.caption(f"金額の単位: **{unit}**。行を追加すると複数年のトレンド分析ができます（上が古い期）")
        ver = st.session_state[f"editor_ver_{slot}"]
        col_cfg = {"期間ラベル": st.column_config.TextColumn(required=True)}
        for col in DF_COLUMNS[1:]:
            col_cfg[col] = st.column_config.NumberColumn(format="%.0f", min_value=0 if col not in () else None)
        edited = st.data_editor(
            st.session_state[f"df_{slot}"],
            num_rows="dynamic",
            width="stretch",
            key=f"editor_{slot}_{ver}",
            column_config=col_cfg,
        )
        st.session_state[f"df_{slot}"] = edited

    # ── EDINET取得 ───────────────────────────────────────────────────────────
    with tab_edinet:
        st.caption(
            "金融庁 [EDINET API](https://api.edinet-fsa.go.jp/)（無料・要登録）から"
            "上場企業の有価証券報告書を検索し、P/Lを自動入力します。金額は**百万円**で取り込まれます。"
        )
        api_key = st.text_input(
            "EDINET APIキー", type="password",
            value=os.getenv("EDINET_API_KEY", ""),
            key=f"edinet_key_{slot}",
            help="環境変数 EDINET_API_KEY を設定しておくと自動入力されます",
        )
        search_name = st.text_input("企業名（部分一致）", placeholder="例: トヨタ自動車", key=f"edinet_name_{slot}")
        days = st.slider("遡る期間（日）", 90, 730, 400, step=30, key=f"edinet_days_{slot}",
                         help="有価証券報告書は年1回提出。決算期末から3ヶ月後の提出が多い（3月決算→6月提出）")

        if st.button("🔍 検索", key=f"edinet_search_{slot}", disabled=not (api_key and search_name)):
            bar = st.progress(0.0, text="EDINETの提出書類一覧を検索中…（初回は数分かかります）")
            try:
                hits = edinet_client.search_documents(
                    search_name, api_key, days=days,
                    progress=lambda done, total: bar.progress(done / total, text=f"検索中… {done}/{total}日"),
                )
                bar.empty()
                st.session_state[f"edinet_hits_{slot}"] = hits
                if not hits:
                    st.warning("見つかりませんでした。企業名の表記（法人格の有無など）や遡る期間を変えて再検索してください。")
            except RuntimeError as exc:
                bar.empty()
                st.error(str(exc))
            except Exception as exc:
                bar.empty()
                st.error(f"検索に失敗しました: {exc}（ネットワーク制限のある環境ではEDINETに接続できません。ローカルPCで実行してください）")

        hits = st.session_state.get(f"edinet_hits_{slot}", [])
        if hits:
            options = {
                f"{h['filerName']}｜{h['docTypeName']}｜{h.get('docDescription') or ''}（提出日 {h['submitDate']}）": h
                for h in hits
            }
            sel = st.selectbox("取り込む書類を選択", list(options.keys()), key=f"edinet_sel_{slot}")
            append = st.checkbox("既存の表に追記する（複数年積み上げ用）", key=f"edinet_append_{slot}")
            if st.button("⬇️ この書類からP/Lを取り込む", key=f"edinet_import_{slot}"):
                doc = options[sel]
                try:
                    with st.spinner("財務データを取得・解析中…"):
                        result = edinet_client.fetch_pl(doc["docID"], api_key, doc.get("periodEnd") or "")
                    new_df = periods_to_df(result["periods"])
                    if append:
                        cur = st.session_state[f"df_{slot}"]
                        new_df = pd.concat([cur, new_df], ignore_index=True).drop_duplicates(subset=["期間ラベル"], keep="last")
                    st.session_state[f"pending_{slot}"] = {"df": new_df, "name": doc["filerName"]}
                    scope = "連結" if result["consolidated"] else "単体"
                    st.success(f"{doc['filerName']} の {len(result['periods'])}期分（{scope}・百万円）を取り込みました。単位設定を「百万円」にしてください。")
                    st.rerun()
                except Exception as exc:
                    st.error(f"取り込みに失敗しました: {exc}")

    # ── デモデータ ───────────────────────────────────────────────────────────
    with tab_demo:
        st.caption("APIキーなしで全機能（トレンド分析・スコア・比較）を試せるサンプルです")
        demo_key = st.selectbox("サンプル企業", list(DEMO_COMPANIES.keys()), key=f"demo_sel_{slot}")
        if st.button("📥 読み込む", key=f"demo_load_{slot}"):
            demo = DEMO_COMPANIES[demo_key]
            st.session_state[f"pending_{slot}"] = {
                "df": periods_to_df(demo["periods"]),
                "name": demo_key.split(":")[1].strip() if ":" in demo_key else demo_key,
                "industry": demo["industry"],
            }
            st.rerun()

    return {"name": name, "industry": industry, "periods": df_to_periods(st.session_state[f"df_{slot}"])}


# ── グラフ部品 ────────────────────────────────────────────────────────────────

def fig_waterfall(m: dict, unit: str) -> go.Figure:
    non_op_net = m["ordinary_profit"] - m["operating_profit"]
    other_net  = m["net_profit"] - m["ordinary_profit"]
    fig = go.Figure(go.Waterfall(
        orientation="v",
        measure=["absolute", "relative", "total", "relative", "total", "relative", "total", "relative", "total"],
        x=["売上高", "売上原価", "売上総利益", "販管費", "営業利益", "営業外収支", "経常利益", "特別・税", "純利益"],
        y=[m["revenue"], -m["cogs"], m["gross_profit"], -m["sga"], m["operating_profit"],
           non_op_net, m["ordinary_profit"], other_net, m["net_profit"]],
        connector={"line": {"color": "rgb(80,80,80)"}},
        decreasing={"marker": {"color": "#EF4444"}},
        increasing={"marker": {"color": "#3B82F6"}},
        totals={"marker": {"color": "#10B981"}},
        texttemplate="%{y:,.0f}",
        textposition="outside",
    ))
    fig.update_layout(height=400, margin=dict(t=20, b=20), yaxis_title=unit, showlegend=False,
                      plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
    return fig


def fig_trend(metrics_list: list[dict], unit: str) -> go.Figure:
    labels = [m["label"] or f"{i+1}期目" for i, m in enumerate(metrics_list)]
    fig = go.Figure()
    fig.add_trace(go.Bar(name="売上高", x=labels, y=[m["revenue"] for m in metrics_list],
                         marker_color="#BFDBFE", yaxis="y"))
    fig.add_trace(go.Bar(name="営業利益", x=labels, y=[m["operating_profit"] for m in metrics_list],
                         marker_color="#3B82F6", yaxis="y"))
    fig.add_trace(go.Scatter(name="営業利益率", x=labels, y=[m["operating_margin"] for m in metrics_list],
                             mode="lines+markers+text", yaxis="y2", line=dict(color="#F59E0B", width=3),
                             text=[f"{m['operating_margin']:.1f}%" for m in metrics_list], textposition="top center"))
    fig.add_trace(go.Scatter(name="純利益率", x=labels, y=[m["net_margin"] for m in metrics_list],
                             mode="lines+markers", yaxis="y2", line=dict(color="#10B981", width=2, dash="dot")))
    fig.update_layout(
        height=400, margin=dict(t=30, b=20), barmode="group",
        yaxis=dict(title=unit), yaxis2=dict(title="%", overlaying="y", side="right", zeroline=True),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def fig_benchmark(m: dict, benchmark: dict, name: str, industry: str) -> go.Figure:
    keys = list(METRIC_LABELS.keys())
    fig = go.Figure()
    fig.add_trace(go.Bar(name=name or "当社", x=[METRIC_LABELS[k] for k in keys], y=[m[k] for k in keys],
                         marker_color="#3B82F6", text=[f"{m[k]:.1f}%" for k in keys], textposition="outside"))
    fig.add_trace(go.Bar(name=f"業界平均（{industry}）", x=[METRIC_LABELS[k] for k in keys], y=[benchmark[k] for k in keys],
                         marker_color="#D1D5DB", text=[f"{benchmark[k]:.1f}%" for k in keys], textposition="outside"))
    fig.update_layout(barmode="group", height=400, margin=dict(t=20, b=20), yaxis_title="%",
                      legend=dict(orientation="h", yanchor="bottom", y=1.02),
                      plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
    fig.update_xaxes(tickangle=-20)
    return fig


def fig_score_gauge(score: dict) -> go.Figure:
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=score["total"],
        number={"suffix": f" 点（{score['grade']}）", "font": {"size": 36}},
        gauge={
            "axis": {"range": [0, 100]},
            "bar": {"color": "#3B82F6"},
            "steps": [
                {"range": [0, 35],  "color": "#FEE2E2"},
                {"range": [35, 50], "color": "#FEF3C7"},
                {"range": [50, 65], "color": "#FEF9C3"},
                {"range": [65, 80], "color": "#D1FAE5"},
                {"range": [80, 100], "color": "#A7F3D0"},
            ],
        },
    ))
    fig.update_layout(height=230, margin=dict(t=30, b=10, l=30, r=30), paper_bgcolor="rgba(0,0,0,0)")
    return fig


def fig_radar(name_a, m_a, name_b, m_b, benchmark) -> go.Figure:
    keys = list(METRIC_LABELS.keys())
    cats = [METRIC_LABELS[k] for k in keys]
    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(r=[m_a[k] for k in keys], theta=cats, fill="toself", name=name_a,
                                  line=dict(color="#3B82F6")))
    fig.add_trace(go.Scatterpolar(r=[m_b[k] for k in keys], theta=cats, fill="toself", name=name_b,
                                  line=dict(color="#F59E0B")))
    fig.add_trace(go.Scatterpolar(r=[benchmark[k] for k in keys], theta=cats, name="業界平均",
                                  line=dict(color="#9CA3AF", dash="dot")))
    fig.update_layout(height=420, margin=dict(t=40, b=20),
                      legend=dict(orientation="h", yanchor="bottom", y=1.05),
                      paper_bgcolor="rgba(0,0,0,0)")
    return fig


# ── 分析表示 ──────────────────────────────────────────────────────────────────

def render_kpis(metrics_list: list[dict], benchmark: dict):
    latest = metrics_list[-1]
    prev = metrics_list[-2] if len(metrics_list) >= 2 else None
    cols = st.columns(4)
    for col, key in zip(cols, METRIC_LABELS.keys()):
        with col:
            delta = None
            if prev:
                d = latest[key] - prev[key]
                delta = f"{d:+.1f}pt (前期比)"
            st.metric(METRIC_LABELS[key], f"{latest[key]:.1f}%", delta=delta)
            st.caption(f"業界平均: {benchmark[key]:.1f}%")


def render_report(analysis: dict):
    cs, cw = st.columns(2)
    with cs:
        st.markdown("#### 💪 強み")
        for s in analysis["strengths"]:
            st.success(f"✅ {s}")
    with cw:
        st.markdown("#### ⚠️ 弱み")
        for w in analysis["weaknesses"]:
            st.warning(f"⚠️ {w}")
    st.markdown("#### 🎯 課題")
    for c in analysis["challenges"]:
        st.error(f"🎯 {c}")
    st.markdown("#### 🛠️ 改善アクションの提案")
    for a in analysis["actions"]:
        st.info(f"💡 {a}")


def render_pl_table(m: dict, unit: str):
    rows = [
        ("売上高",               m["revenue"],          True),
        ("　売上原価",            -m["cogs"],            False),
        ("売上総利益（粗利）",    m["gross_profit"],     True),
        ("　販売費及び一般管理費", -m["sga"],             False),
        ("営業利益",              m["operating_profit"], True),
        ("経常利益",              m["ordinary_profit"],  True),
        ("純利益（最終利益）",    m["net_profit"],       True),
    ]
    df = pd.DataFrame([(r[0], r[1]) for r in rows], columns=["項目", f"金額（{unit}）"])
    bold = [r[2] for r in rows]
    styled = (df.style
              .apply(lambda row: ["font-weight: bold; background-color: #EFF6FF" if bold[row.name] else ""] * 2, axis=1)
              .format({f"金額（{unit}）": "{:,.0f}"}))
    st.dataframe(styled, width="stretch", hide_index=True)


def render_company_analysis(name: str, industry: str, periods: list[dict], unit: str, compact: bool = False):
    metrics_list = calc_all(periods)
    if not metrics_list:
        st.warning(f"{name}: 売上高が入力された期がありません。")
        return None, None
    benchmark = BENCHMARKS[industry]
    score = score_company(metrics_list, benchmark)
    analysis = generate_analysis(metrics_list, benchmark)
    latest = metrics_list[-1]

    # 総合スコア
    g1, g2 = st.columns([1, 1])
    with g1:
        st.plotly_chart(fig_score_gauge(score), width="stretch", key=f"gauge_{name}_{compact}")
    with g2:
        st.markdown("##### スコア内訳")
        for k, v in score["breakdown"].items():
            st.markdown(f"- {k}: **{'—' if v is None else f'{v:.1f}点'}**")
        if score["note"]:
            st.caption(f"※ {score['note']}")

    render_kpis(metrics_list, benchmark)
    st.divider()

    if compact:
        # 比較モードでは要約のみ
        st.plotly_chart(fig_trend(metrics_list, unit) if len(metrics_list) >= 2 else fig_waterfall(latest, unit),
                        width="stretch", key=f"main_{name}_{compact}")
        render_report(analysis)
        return metrics_list, score

    # ── 単独モードのフル表示 ─────────────────────────────────────────────────
    col_l, col_r = st.columns([3, 2])
    with col_l:
        st.subheader(f"📉 損益の構造（{latest['label'] or '最新期'}）")
        st.plotly_chart(fig_waterfall(latest, unit), width="stretch")
    with col_r:
        st.subheader("📊 利益率の業界比較")
        st.plotly_chart(fig_benchmark(latest, benchmark, name, industry), width="stretch")

    if len(metrics_list) >= 2:
        st.subheader(f"📈 業績トレンド（{len(metrics_list)}期）")
        st.plotly_chart(fig_trend(metrics_list, unit), width="stretch")
        rg, og = score.get("rev_growth"), score.get("op_growth")
        notes = []
        if rg is not None:
            notes.append(f"売上の年平均成長率 **{rg:+.1f}%**")
        if og is not None:
            notes.append(f"営業利益の年平均成長率 **{og:+.1f}%**")
        if notes:
            st.caption("、".join(notes))

    st.divider()
    st.subheader("🔍 解析レポート")
    render_report(analysis)

    st.divider()
    t1, t2 = st.columns([1, 1])
    with t1:
        st.subheader("🧾 損益計算書（最新期）")
        render_pl_table(latest, unit)
    with t2:
        st.subheader("📚 各指標の意味（初心者向け）")
        for key in METRIC_LABELS:
            val, bval = latest[key], benchmark[key]
            diff = val - bval
            with st.expander(f"{METRIC_LABELS[key]}：**{val:.1f}%**（業界平均より {'＋' if diff >= 0 else ''}{diff:.1f}pt）"):
                st.markdown(METRIC_EXPLANATIONS[key])

    return metrics_list, score


# ── メイン ────────────────────────────────────────────────────────────────────

st.title("📊 損益計算書アナライザー")
st.caption("数値を入力 or EDINETから自動取得 → 財務状況を初心者にもわかりやすく解析します")

with st.sidebar:
    st.header("⚙️ 設定")
    mode = st.radio("分析モード", ["単独分析", "2社比較"], horizontal=True)
    unit = st.selectbox("金額の単位", ["百万円", "千円", "億円", "円"],
                        help="EDINETから取り込んだ場合は百万円です")
    st.divider()
    st.markdown(
        "**データ入力は本画面上部で行います**\n\n"
        "- ✍️ 手入力: 表に直接入力（行追加で複数年）\n"
        "- 🌐 EDINET: 企業名で有報を検索して自動入力\n"
        "- 🎲 デモ: サンプル企業ですぐ試す"
    )

if mode == "単独分析":
    with st.expander("📝 データ入力", expanded=True):
        company = render_company_input("A", unit)
    st.divider()
    header = " | ".join(filter(None, [company["name"], company["industry"]]))
    st.subheader(header or "分析結果")
    render_company_analysis(company["name"], company["industry"], company["periods"], unit)

else:
    in_a, in_b = st.columns(2)
    with in_a, st.expander("📝 会社A のデータ入力", expanded=True):
        company_a = render_company_input("A", unit)
    with in_b, st.expander("📝 会社B のデータ入力", expanded=True):
        company_b = render_company_input("B", unit)

    st.divider()
    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader(f"🅰️ {company_a['name']}（{company_a['industry']}）")
        ma, sa = render_company_analysis(company_a["name"], company_a["industry"], company_a["periods"], unit, compact=True)
    with col_b:
        st.subheader(f"🅱️ {company_b['name']}（{company_b['industry']}）")
        mb, sb = render_company_analysis(company_b["name"], company_b["industry"], company_b["periods"], unit, compact=True)

    if ma and mb:
        st.divider()
        st.subheader("⚔️ 直接対決")
        comp = compare_companies(company_a["name"], ma, sa, company_b["name"], mb, sb)
        st.markdown(comp["verdict"])

        c_l, c_r = st.columns([3, 2])
        with c_l:
            st.dataframe(pd.DataFrame(comp["rows"]), width="stretch", hide_index=True)
            st.caption("※ 利益率は最新期の値。成長率は入力期間の年平均（複数年入力時のみ）")
        with c_r:
            bench = BENCHMARKS[company_a["industry"]]
            st.plotly_chart(fig_radar(company_a["name"], ma[-1], company_b["name"], mb[-1], bench),
                            width="stretch")

# ── 基礎知識 ──────────────────────────────────────────────────────────────────
st.divider()
with st.expander("📖 損益計算書とは？（基礎知識）"):
    st.markdown("""
    損益計算書（P/L: Profit & Loss Statement）は、**ある期間に会社がいくら稼ぎ、いくら使ったか**を示す財務諸表です。

    ```
    売上高                        ← 商品・サービスの販売総額
      ー 売上原価                  ← 仕入れ・製造にかかったコスト
    ＝ 売上総利益（粗利）          ← 商品自体の儲け

      ー 販売費及び一般管理費       ← 人件費・広告費・家賃など
    ＝ 営業利益                   ← 本業での儲け  ★最重要★

      ＋ 営業外収益（利息・配当等）
      ー 営業外費用（支払利息等）
    ＝ 経常利益                   ← 通常の事業活動全体の儲け

      ＋ 特別利益（資産売却益など一時的）
      ー 特別損失（災害損失など一時的）
      ー 法人税等
    ＝ 純利益（最終利益）          ← 最終的な手取り
    ```

    **最も注目すべき指標は「営業利益率」**です。本業の稼ぐ力を純粋に示しており、会社の実力がわかります。
    業種が異なると利益率の水準も大きく異なるため、同業他社との比較が重要です。

    **総合スコアの見方**: 収益性（40点）＝業界平均との利益率比較 ／ 成長性（30点）＝売上・営業利益の年平均成長率 ／
    安定性（30点）＝黒字の継続性と利益率のブレ。複数年入力すると全項目が評価されます。
    """)
