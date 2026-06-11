"""
pl_analyzer.py - 損益計算書アナライザー
初心者でも損益計算書が理解できる財務分析ツール
"""

import streamlit as st
import plotly.graph_objects as go
import pandas as pd

# ── 業種別ベンチマーク（日本企業概算平均値）───────────────────────────────────
BENCHMARKS = {
    "製造業":        {"gross_margin": 20.0, "operating_margin":  5.0, "ordinary_margin":  5.5, "net_margin": 3.5},
    "IT・ソフトウェア": {"gross_margin": 55.0, "operating_margin": 12.0, "ordinary_margin": 12.5, "net_margin": 8.0},
    "小売業":        {"gross_margin": 28.0, "operating_margin":  3.0, "ordinary_margin":  3.2, "net_margin": 2.0},
    "飲食業":        {"gross_margin": 62.0, "operating_margin":  5.0, "ordinary_margin":  5.0, "net_margin": 3.0},
    "建設業":        {"gross_margin": 15.0, "operating_margin":  3.5, "ordinary_margin":  4.0, "net_margin": 2.5},
    "サービス業":    {"gross_margin": 45.0, "operating_margin":  8.0, "ordinary_margin":  8.5, "net_margin": 5.5},
    "不動産業":      {"gross_margin": 25.0, "operating_margin": 10.0, "ordinary_margin": 10.5, "net_margin": 6.5},
    "医療・ヘルスケア": {"gross_margin": 40.0, "operating_margin": 8.0, "ordinary_margin": 8.5, "net_margin": 5.0},
}

METRIC_LABELS = {
    "gross_margin":     "売上総利益率（粗利率）",
    "operating_margin": "営業利益率",
    "ordinary_margin":  "経常利益率",
    "net_margin":       "純利益率",
}

METRIC_EXPLANATIONS = {
    "gross_margin": (
        "**売上高から仕入れ・製造コストを引いた後に残る利益の割合**です。"
        "商品・サービス自体の収益力を示します。"
        "この率が高いほど「原価に対して高く売れている」ことを意味します。"
    ),
    "operating_margin": (
        "**本業での儲けの割合**です。粗利からさらに人件費・広告費・家賃などを引いた後の利益率。"
        "企業の稼ぐ力の核心であり、最も重要な指標のひとつです。"
    ),
    "ordinary_margin": (
        "**本業＋金利収支など通常の事業活動全体での利益率**です。"
        "借入金の多い会社は金融費用が大きいため、営業利益率より低くなります。"
    ),
    "net_margin": (
        "**税金・特別損益まで含めた最終的な手取り利益の割合**です。"
        "資産売却や災害損失など一時的な要因の影響を受けるため、"
        "単年だけで判断せず複数年で見ることが重要です。"
    ),
}


# ── 計算ロジック ──────────────────────────────────────────────────────────────

def calc_metrics(d: dict) -> dict:
    rev = d["revenue"]
    if rev == 0:
        return {}
    gross_profit     = rev - d["cogs"]
    operating_profit = gross_profit - d["sga"]
    ordinary_profit  = operating_profit + d["non_op_income"] - d["non_op_expense"]
    pretax_profit    = ordinary_profit + d["extra_gain"] - d["extra_loss"]
    net_profit       = pretax_profit - d["tax"]
    return {
        "revenue":           rev,
        "gross_profit":      gross_profit,
        "operating_profit":  operating_profit,
        "ordinary_profit":   ordinary_profit,
        "net_profit":        net_profit,
        "gross_margin":      gross_profit    / rev * 100,
        "operating_margin":  operating_profit / rev * 100,
        "ordinary_margin":   ordinary_profit  / rev * 100,
        "net_margin":        net_profit       / rev * 100,
        "cogs_ratio":        d["cogs"]        / rev * 100,
        "sga_ratio":         d["sga"]         / rev * 100,
    }


def yoy_change(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return (current - previous) / abs(previous) * 100


def generate_analysis(metrics: dict, benchmark: dict, yoy: dict | None) -> dict:
    """強み・弱み・課題のリストを生成して返す"""
    strengths, weaknesses, challenges = [], [], []

    gm  = metrics["gross_margin"]
    om  = metrics["operating_margin"]
    nm  = metrics["net_margin"]
    bgm = benchmark["gross_margin"]
    bom = benchmark["operating_margin"]
    bnm = benchmark["net_margin"]

    # 粗利率
    if gm >= bgm * 1.2:
        strengths.append(f"粗利率 {gm:.1f}% が業界平均 {bgm:.1f}% を大きく上回り、高い価格競争力・商品力を持つ")
    elif gm >= bgm:
        strengths.append(f"粗利率 {gm:.1f}% が業界平均 {bgm:.1f}% を上回っている")
    elif gm < bgm * 0.8:
        weaknesses.append(f"粗利率 {gm:.1f}% が業界平均 {bgm:.1f}% を大きく下回る。原価低減や価格戦略の見直しが必要")
    else:
        weaknesses.append(f"粗利率 {gm:.1f}% が業界平均 {bgm:.1f}% をやや下回っている")

    # 営業利益率
    if om >= bom * 1.3:
        strengths.append(f"営業利益率 {om:.1f}% が業界平均 {bom:.1f}% を大幅に上回り、コスト管理が優秀")
    elif om >= bom:
        strengths.append(f"営業利益率 {om:.1f}% が業界平均 {bom:.1f}% を上回っている")
    elif om < 0:
        weaknesses.append(f"営業利益が赤字（{om:.1f}%）。本業で利益が出ておらず、早急な対策が必要")
        challenges.append("本業の収益化: 営業赤字の解消に向けた収益構造の抜本的見直しが急務")
    else:
        weaknesses.append(f"営業利益率 {om:.1f}% が業界平均 {bom:.1f}% を下回っている")

    # 販管費負担
    if metrics["sga_ratio"] > 40:
        challenges.append(
            f"販管費比率 {metrics['sga_ratio']:.1f}% が高水準。人件費・広告費などの固定費構造を見直す余地がある"
        )

    # 原価率
    if metrics["cogs_ratio"] > 80:
        challenges.append(
            f"売上原価率 {metrics['cogs_ratio']:.1f}% が高い。調達コスト削減や製造効率化で粗利改善が期待できる"
        )

    # 純利益率
    if nm < 0:
        weaknesses.append(f"最終利益が赤字（純利益率 {nm:.1f}%）。特別損失や税負担の内訳確認を推奨")
    elif nm >= bnm * 1.5:
        strengths.append(f"純利益率 {nm:.1f}% が業界平均 {bnm:.1f}% の1.5倍超で、高い最終収益力を持つ")

    # 前年比
    if yoy:
        rev_yoy = yoy.get("revenue")
        op_yoy  = yoy.get("operating_profit")
        if rev_yoy is not None:
            if rev_yoy >= 10:
                strengths.append(f"売上高が前年比 +{rev_yoy:.1f}% と力強く成長している")
            elif rev_yoy < -5:
                weaknesses.append(f"売上高が前年比 {rev_yoy:.1f}% と減収。需要・競合環境の分析が必要")
        if op_yoy is not None:
            if op_yoy >= 20:
                strengths.append(f"営業利益が前年比 +{op_yoy:.1f}% と大幅増益")
            elif op_yoy < -20:
                challenges.append(f"営業利益が前年比 {op_yoy:.1f}% と大幅減益。収益回復策の策定が課題")

    if not strengths:
        strengths.append("業界平均に近い水準で、バランスの取れた財務構造")
    if not weaknesses:
        weaknesses.append("目立った弱みは見当たりません")
    if not challenges:
        challenges.append("現状の収益構造を維持しつつ、さらなる利益率向上を目指したい")

    return {"strengths": strengths, "weaknesses": weaknesses, "challenges": challenges}


# ── Streamlit アプリ ──────────────────────────────────────────────────────────

st.set_page_config(page_title="損益計算書アナライザー", page_icon="📊", layout="wide")

st.title("📊 損益計算書アナライザー")
st.caption("会社の数字を入力するだけで、財務状況を初心者にもわかりやすく解析します")

# サイドバー
with st.sidebar:
    st.header("📝 数値を入力")

    company_name = st.text_input("会社名（任意）", placeholder="例: 株式会社サンプル")
    fiscal_year  = st.text_input("決算期（任意）",  placeholder="例: 2024年3月期")
    industry     = st.selectbox("業種", list(BENCHMARKS.keys()))
    unit         = st.selectbox("金額の単位", ["百万円", "千円", "億円", "円"])

    st.divider()
    st.subheader("当期")
    revenue       = st.number_input("売上高 *",              min_value=0, value=10_000, step=100)
    cogs          = st.number_input("売上原価 *",             min_value=0, value=6_000,  step=100)
    sga           = st.number_input("販売費及び一般管理費 *",  min_value=0, value=2_500,  step=100)
    non_op_income = st.number_input("営業外収益",              min_value=0, value=100,    step=10)
    non_op_exp    = st.number_input("営業外費用",              min_value=0, value=150,    step=10)
    extra_gain    = st.number_input("特別利益",                min_value=0, value=0,      step=10)
    extra_loss    = st.number_input("特別損失",                min_value=0, value=0,      step=10)
    tax           = st.number_input("法人税等",                min_value=0, value=300,    step=50)

    st.divider()
    compare = st.checkbox("前期と比較する")
    prev_data = None
    if compare:
        st.subheader("前期")
        prev_revenue       = st.number_input("売上高（前期）",            min_value=0, value=9_500, step=100)
        prev_cogs          = st.number_input("売上原価（前期）",           min_value=0, value=5_800, step=100)
        prev_sga           = st.number_input("販売費及び一般管理費（前期）", min_value=0, value=2_400, step=100)
        prev_non_op_income = st.number_input("営業外収益（前期）",          min_value=0, value=80,    step=10)
        prev_non_op_exp    = st.number_input("営業外費用（前期）",          min_value=0, value=180,   step=10)
        prev_extra_gain    = st.number_input("特別利益（前期）",            min_value=0, value=0,     step=10)
        prev_extra_loss    = st.number_input("特別損失（前期）",            min_value=0, value=0,     step=10)
        prev_tax           = st.number_input("法人税等（前期）",            min_value=0, value=270,   step=50)
        prev_data = dict(
            revenue=prev_revenue, cogs=prev_cogs, sga=prev_sga,
            non_op_income=prev_non_op_income, non_op_expense=prev_non_op_exp,
            extra_gain=prev_extra_gain, extra_loss=prev_extra_loss, tax=prev_tax,
        )

# 計算
current_input = dict(
    revenue=revenue, cogs=cogs, sga=sga,
    non_op_income=non_op_income, non_op_expense=non_op_exp,
    extra_gain=extra_gain, extra_loss=extra_loss, tax=tax,
)
metrics   = calc_metrics(current_input)
benchmark = BENCHMARKS[industry]

yoy          = None
prev_metrics = None
if compare and prev_data:
    prev_metrics = calc_metrics(prev_data)
    yoy = {
        "revenue":           yoy_change(metrics["revenue"],          prev_metrics["revenue"]),
        "gross_profit":      yoy_change(metrics["gross_profit"],     prev_metrics["gross_profit"]),
        "operating_profit":  yoy_change(metrics["operating_profit"], prev_metrics["operating_profit"]),
        "net_profit":        yoy_change(metrics["net_profit"],       prev_metrics["net_profit"]),
    }

analysis = generate_analysis(metrics, benchmark, yoy)

# ヘッダー
header = " | ".join(filter(None, [company_name, fiscal_year, industry]))
if header:
    st.subheader(header)

# ── KPI カード ────────────────────────────────────────────────────────────────
st.subheader("📌 主要指標")
c1, c2, c3, c4 = st.columns(4)

def _delta(yoy_dict, key):
    if not yoy_dict or yoy_dict.get(key) is None:
        return None
    v = yoy_dict[key]
    return f"{v:+.1f}% (前期比)"

with c1:
    st.metric("売上総利益率（粗利率）", f"{metrics['gross_margin']:.1f}%",
              delta=_delta(yoy, "gross_profit"))
    st.caption(f"業界平均: {benchmark['gross_margin']:.1f}%")
with c2:
    st.metric("営業利益率", f"{metrics['operating_margin']:.1f}%",
              delta=_delta(yoy, "operating_profit"))
    st.caption(f"業界平均: {benchmark['operating_margin']:.1f}%")
with c3:
    st.metric("経常利益率", f"{metrics['ordinary_margin']:.1f}%")
    st.caption(f"業界平均: {benchmark['ordinary_margin']:.1f}%")
with c4:
    st.metric("純利益率", f"{metrics['net_margin']:.1f}%",
              delta=_delta(yoy, "net_profit"))
    st.caption(f"業界平均: {benchmark['net_margin']:.1f}%")

st.divider()

# ── グラフ ────────────────────────────────────────────────────────────────────
col_l, col_r = st.columns([3, 2])

with col_l:
    st.subheader("📉 損益の構造（ウォーターフォール）")

    non_op_net = metrics["ordinary_profit"]  - metrics["operating_profit"]
    other_net  = metrics["net_profit"]        - metrics["ordinary_profit"]

    fig_wf = go.Figure(go.Waterfall(
        orientation="v",
        measure=["absolute", "relative", "total", "relative", "total", "relative", "total", "relative", "total"],
        x=["売上高", "売上原価", "売上総利益", "販管費", "営業利益", "営業外収支", "経常利益", "特別・税", "純利益"],
        y=[
            metrics["revenue"],
            -cogs,
            metrics["gross_profit"],
            -sga,
            metrics["operating_profit"],
            non_op_net,
            metrics["ordinary_profit"],
            other_net,
            metrics["net_profit"],
        ],
        connector={"line": {"color": "rgb(80,80,80)"}},
        decreasing={"marker": {"color": "#EF4444"}},
        increasing={"marker": {"color": "#3B82F6"}},
        totals={"marker": {"color": "#10B981"}},
        texttemplate="%{y:,.0f}",
        textposition="outside",
    ))
    fig_wf.update_layout(
        height=420, margin=dict(t=20, b=20), yaxis_title=unit,
        showlegend=False,
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig_wf, use_container_width=True)

with col_r:
    st.subheader("📊 利益率の業界比較")

    keys = ["gross_margin", "operating_margin", "ordinary_margin", "net_margin"]
    label_name = company_name or "当社"
    fig_bar = go.Figure()
    fig_bar.add_trace(go.Bar(
        name=label_name,
        x=[METRIC_LABELS[k] for k in keys],
        y=[metrics[k] for k in keys],
        marker_color="#3B82F6",
        text=[f"{metrics[k]:.1f}%" for k in keys],
        textposition="outside",
    ))
    fig_bar.add_trace(go.Bar(
        name=f"業界平均（{industry}）",
        x=[METRIC_LABELS[k] for k in keys],
        y=[benchmark[k] for k in keys],
        marker_color="#D1D5DB",
        text=[f"{benchmark[k]:.1f}%" for k in keys],
        textposition="outside",
    ))
    fig_bar.update_layout(
        barmode="group", height=420, margin=dict(t=20, b=20), yaxis_title="%",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    )
    fig_bar.update_xaxes(tickangle=-20)
    st.plotly_chart(fig_bar, use_container_width=True)

# 前期比較グラフ
if compare and prev_metrics:
    st.subheader("📈 前期比較")
    items = ["売上高", "売上総利益", "営業利益", "純利益"]
    cur_vals  = [metrics["revenue"],      metrics["gross_profit"],      metrics["operating_profit"],      metrics["net_profit"]]
    prev_vals = [prev_metrics["revenue"], prev_metrics["gross_profit"], prev_metrics["operating_profit"], prev_metrics["net_profit"]]

    fig_yoy = go.Figure()
    fig_yoy.add_trace(go.Bar(name="前期", x=items, y=prev_vals, marker_color="#D1D5DB",
                             text=[f"{v:,.0f}" for v in prev_vals], textposition="outside"))
    fig_yoy.add_trace(go.Bar(name="当期", x=items, y=cur_vals, marker_color="#3B82F6",
                             text=[f"{v:,.0f}" for v in cur_vals], textposition="outside"))
    fig_yoy.update_layout(
        barmode="group", height=360, margin=dict(t=20, b=20), yaxis_title=unit,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig_yoy, use_container_width=True)

st.divider()

# ── AI 解析レポート ────────────────────────────────────────────────────────────
st.subheader("🔍 解析レポート")
cs, cw, cc = st.columns(3)

with cs:
    st.markdown("### 💪 強み")
    for s in analysis["strengths"]:
        st.success(f"✅ {s}")
with cw:
    st.markdown("### ⚠️ 弱み")
    for w in analysis["weaknesses"]:
        st.warning(f"⚠️ {w}")
with cc:
    st.markdown("### 🎯 課題・改善ポイント")
    for c in analysis["challenges"]:
        st.error(f"🎯 {c}")

st.divider()

# ── 損益計算書の構造（数値付き）──────────────────────────────────────────────
st.subheader("🧾 損益計算書（計算結果）")

pl_rows = [
    ("売上高",              metrics["revenue"],           False),
    ("　売上原価",           -cogs,                        False),
    ("売上総利益（粗利）",   metrics["gross_profit"],      True),
    ("　販売費及び一般管理費", -sga,                         False),
    ("営業利益",             metrics["operating_profit"],  True),
    ("　営業外収益",          non_op_income,                False),
    ("　営業外費用",          -non_op_exp,                  False),
    ("経常利益",             metrics["ordinary_profit"],   True),
    ("　特別利益",            extra_gain,                   False),
    ("　特別損失",            -extra_loss,                  False),
    ("　法人税等",            -tax,                         False),
    ("純利益（最終利益）",   metrics["net_profit"],        True),
]

pl_df = pd.DataFrame(pl_rows, columns=["項目", f"金額（{unit}）", "合計行"])

def _style_row(row):
    if row["合計行"]:
        return ["font-weight: bold; background-color: #EFF6FF"] * 3
    return [""] * 3

styled = (
    pl_df.drop(columns=["合計行"])
    .style.apply(_style_row, axis=1, subset=None)
    .format({f"金額（{unit}）": "{:,.0f}"})
)
st.dataframe(styled, use_container_width=True, hide_index=True)

st.divider()

# ── 各指標の初心者向け解説 ────────────────────────────────────────────────────
st.subheader("📚 各指標の意味（初心者向け）")

for key in ["gross_margin", "operating_margin", "ordinary_margin", "net_margin"]:
    val  = metrics[key]
    bval = benchmark[key]
    diff = val - bval
    sign = "＋" if diff >= 0 else ""
    with st.expander(f"{METRIC_LABELS[key]}：**{val:.1f}%**　（業界平均より {sign}{diff:.1f}%pt）"):
        st.markdown(METRIC_EXPLANATIONS[key])

        gauge = go.Figure(go.Indicator(
            mode="gauge+number+delta",
            value=val,
            delta={"reference": bval, "suffix": "%pt vs 業界平均"},
            title={"text": METRIC_LABELS[key]},
            number={"suffix": "%"},
            gauge={
                "axis": {"range": [min(0, val - 10, bval - 5), max(val + 10, bval + 5)]},
                "bar":  {"color": "#3B82F6"},
                "steps": [
                    {"range": [min(0, val - 10, bval - 5), bval], "color": "#FEF3C7"},
                    {"range": [bval, max(val + 10, bval + 5)],    "color": "#D1FAE5"},
                ],
                "threshold": {"line": {"color": "#EF4444", "width": 4}, "thickness": 0.75, "value": bval},
            },
        ))
        gauge.update_layout(height=200, margin=dict(t=30, b=0, l=30, r=30),
                            paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(gauge, use_container_width=True)

# ── 損益計算書の基礎知識 ──────────────────────────────────────────────────────
with st.expander("📖 損益計算書とは？（基礎知識）"):
    st.markdown(f"""
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

    今回の分析では **{industry}** の業界平均と比較しています。
    業種が異なると利益率の水準も大きく異なるため、同業他社との比較が重要です。
    """)
