"""
pl_core.py - 損益計算書アナライザーの計算・スコアリング・診断ロジック
UI（Streamlit）に依存しない純粋ロジック層。
"""

from __future__ import annotations

# ── 業種別ベンチマーク（日本企業概算平均値）───────────────────────────────────
BENCHMARKS = {
    "製造業":          {"gross_margin": 20.0, "operating_margin":  5.0, "ordinary_margin":  5.5, "net_margin": 3.5},
    "IT・ソフトウェア": {"gross_margin": 55.0, "operating_margin": 12.0, "ordinary_margin": 12.5, "net_margin": 8.0},
    "小売業":          {"gross_margin": 28.0, "operating_margin":  3.0, "ordinary_margin":  3.2, "net_margin": 2.0},
    "飲食業":          {"gross_margin": 62.0, "operating_margin":  5.0, "ordinary_margin":  5.0, "net_margin": 3.0},
    "建設業":          {"gross_margin": 15.0, "operating_margin":  3.5, "ordinary_margin":  4.0, "net_margin": 2.5},
    "サービス業":      {"gross_margin": 45.0, "operating_margin":  8.0, "ordinary_margin":  8.5, "net_margin": 5.5},
    "不動産業":        {"gross_margin": 25.0, "operating_margin": 10.0, "ordinary_margin": 10.5, "net_margin": 6.5},
    "医療・ヘルスケア": {"gross_margin": 40.0, "operating_margin":  8.0, "ordinary_margin":  8.5, "net_margin": 5.0},
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

# 期データの入力フィールド（順序はP/Lの並び）
PERIOD_FIELDS = [
    ("label",          "期間ラベル"),
    ("revenue",        "売上高"),
    ("cogs",           "売上原価"),
    ("sga",            "販管費"),
    ("non_op_income",  "営業外収益"),
    ("non_op_expense", "営業外費用"),
    ("extra_gain",     "特別利益"),
    ("extra_loss",     "特別損失"),
    ("tax",            "法人税等"),
]


# ── 基本計算 ──────────────────────────────────────────────────────────────────

def calc_metrics(d: dict) -> dict | None:
    """1期分の入力からP/L各段階と利益率を計算する。売上高0は無効."""
    rev = float(d.get("revenue") or 0)
    if rev <= 0:
        return None
    cogs = float(d.get("cogs") or 0)
    sga  = float(d.get("sga") or 0)
    gross_profit     = rev - cogs
    operating_profit = gross_profit - sga
    ordinary_profit  = operating_profit + float(d.get("non_op_income") or 0) - float(d.get("non_op_expense") or 0)
    pretax_profit    = ordinary_profit + float(d.get("extra_gain") or 0) - float(d.get("extra_loss") or 0)
    net_profit       = pretax_profit - float(d.get("tax") or 0)
    return {
        "label":             d.get("label", ""),
        "revenue":           rev,
        "cogs":              cogs,
        "sga":               sga,
        "gross_profit":      gross_profit,
        "operating_profit":  operating_profit,
        "ordinary_profit":   ordinary_profit,
        "net_profit":        net_profit,
        "gross_margin":      gross_profit     / rev * 100,
        "operating_margin":  operating_profit / rev * 100,
        "ordinary_margin":   ordinary_profit  / rev * 100,
        "net_margin":        net_profit       / rev * 100,
        "cogs_ratio":        cogs             / rev * 100,
        "sga_ratio":         sga              / rev * 100,
    }


def calc_all(periods: list[dict]) -> list[dict]:
    """複数期をまとめて計算（無効な期はスキップ）。古い期→新しい期の順を想定."""
    out = []
    for p in periods:
        m = calc_metrics(p)
        if m:
            out.append(m)
    return out


def yoy_change(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return (current - previous) / abs(previous) * 100


def cagr(first: float, last: float, years: int) -> float | None:
    """年平均成長率。マイナスや0始まりは計算不能としてNone."""
    if first <= 0 or last <= 0 or years <= 0:
        return None
    return ((last / first) ** (1 / years) - 1) * 100


# ── 総合スコア（100点満点）────────────────────────────────────────────────────

def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _linear(v, lo, hi, max_pts):
    """v を [lo, hi] の範囲で 0〜max_pts に線形マップ."""
    if hi == lo:
        return max_pts if v >= hi else 0.0
    return _clamp((v - lo) / (hi - lo), 0, 1) * max_pts


def score_company(metrics_list: list[dict], benchmark: dict) -> dict:
    """
    総合スコア（100点）= 収益性40 + 成長性30 + 安定性30
    1期分しかない場合は成長性を除いた70点満点を100点換算し、その旨をnoteに記す。
    """
    if not metrics_list:
        return {"total": 0, "grade": "-", "breakdown": {}, "note": "データなし"}

    latest = metrics_list[-1]
    n = len(metrics_list)

    # ── 収益性（40点）: 営業利益率25 + 粗利率15。業界平均=7割の得点 ──────────
    om, gm = latest["operating_margin"], latest["gross_margin"]
    bom, bgm = benchmark["operating_margin"], benchmark["gross_margin"]
    pts_om = 0.0 if om <= 0 else _linear(om / bom, 0, 10 / 7, 25)
    pts_gm = 0.0 if gm <= 0 else _linear(gm / bgm, 0, 10 / 7, 15)
    profitability = pts_om + pts_gm

    # ── 成長性（30点）: 売上成長15 + 営業利益成長15（最古期→最新期のCAGR）──
    growth = None
    rev_growth = op_growth = None
    if n >= 2:
        years = n - 1
        rev_growth = cagr(metrics_list[0]["revenue"], latest["revenue"], years)
        if rev_growth is None:
            rev_growth = yoy_change(latest["revenue"], metrics_list[-2]["revenue"])
        op_growth = cagr(metrics_list[0]["operating_profit"], latest["operating_profit"], years)
        if op_growth is None:
            op_growth = yoy_change(latest["operating_profit"], metrics_list[-2]["operating_profit"])
        pts_rev = _linear(rev_growth if rev_growth is not None else 0, -10, 15, 15)
        pts_op  = _linear(op_growth  if op_growth  is not None else 0, -30, 30, 15)
        growth = pts_rev + pts_op

    # ── 安定性（30点）: 全期黒字10 + 営業利益率の変動10 + 経常/純が黒字10 ───
    all_op_positive = all(m["operating_profit"] > 0 for m in metrics_list)
    pts_black = 10.0 if all_op_positive else (5.0 if latest["operating_profit"] > 0 else 0.0)

    if n >= 2:
        oms = [m["operating_margin"] for m in metrics_list]
        mean = sum(oms) / n
        std = (sum((x - mean) ** 2 for x in oms) / n) ** 0.5
        pts_vol = _linear(8 - std, 0, 7, 10)   # 変動1pt以下→満点, 8pt以上→0点
    else:
        pts_vol = 5.0  # 単年は判定不能として中間点

    pts_bottom = (5.0 if latest["ordinary_margin"] > 0 else 0.0) + (5.0 if latest["net_margin"] > 0 else 0.0)
    stability = pts_black + pts_vol + pts_bottom

    # ── 合計 ─────────────────────────────────────────────────────────────────
    note = ""
    if growth is None:
        total = (profitability + stability) / 70 * 100
        note = "成長性は複数年データ入力で評価されます（現在は収益性＋安定性のみで換算）"
        breakdown = {"収益性 (40)": round(profitability, 1), "成長性 (30)": None, "安定性 (30)": round(stability, 1)}
    else:
        total = profitability + growth + stability
        breakdown = {"収益性 (40)": round(profitability, 1), "成長性 (30)": round(growth, 1), "安定性 (30)": round(stability, 1)}

    total = round(_clamp(total, 0, 100), 1)
    grade = ("A+" if total >= 90 else "A" if total >= 80 else "B" if total >= 65
             else "C" if total >= 50 else "D" if total >= 35 else "E")

    return {
        "total": total, "grade": grade, "breakdown": breakdown, "note": note,
        "rev_growth": rev_growth, "op_growth": op_growth,
    }


# ── 診断コメント生成 ──────────────────────────────────────────────────────────

def generate_analysis(metrics_list: list[dict], benchmark: dict) -> dict:
    """強み・弱み・課題＋具体的アクションを生成して返す."""
    strengths, weaknesses, challenges, actions = [], [], [], []
    if not metrics_list:
        return {"strengths": [], "weaknesses": [], "challenges": ["有効なデータがありません"], "actions": []}

    latest = metrics_list[-1]
    n = len(metrics_list)
    gm, om, nm = latest["gross_margin"], latest["operating_margin"], latest["net_margin"]
    bgm, bom, bnm = benchmark["gross_margin"], benchmark["operating_margin"], benchmark["net_margin"]

    # ── 粗利率 ───────────────────────────────────────────────────────────────
    if gm >= bgm * 1.2:
        strengths.append(f"粗利率 {gm:.1f}% が業界平均 {bgm:.1f}% を大きく上回り、高い価格競争力・商品力を持つ")
    elif gm >= bgm:
        strengths.append(f"粗利率 {gm:.1f}% が業界平均 {bgm:.1f}% を上回っている")
    elif gm < bgm * 0.8:
        weaknesses.append(f"粗利率 {gm:.1f}% が業界平均 {bgm:.1f}% を大きく下回る")
        actions.append(
            f"粗利改善: 原価率 {latest['cogs_ratio']:.1f}% の内訳を分解し、"
            "①仕入先の相見積もり ②値上げ・価格改定 ③低採算商品の絞り込み を検討する"
        )
    else:
        weaknesses.append(f"粗利率 {gm:.1f}% が業界平均 {bgm:.1f}% をやや下回っている")

    # ── 営業利益率 ───────────────────────────────────────────────────────────
    if om >= bom * 1.3:
        strengths.append(f"営業利益率 {om:.1f}% が業界平均 {bom:.1f}% を大幅に上回り、コスト管理が優秀")
    elif om >= bom:
        strengths.append(f"営業利益率 {om:.1f}% が業界平均 {bom:.1f}% を上回っている")
    elif om < 0:
        weaknesses.append(f"営業利益が赤字（{om:.1f}%）。本業で利益が出ていない")
        actions.append(
            "営業赤字の解消: 損益分岐点売上高を算出し、「固定費削減で下げる」か"
            "「粗利率改善で必要売上を下げる」かの優先順位を決める"
        )
    else:
        weaknesses.append(f"営業利益率 {om:.1f}% が業界平均 {bom:.1f}% を下回っている")

    # ── コスト構造 ───────────────────────────────────────────────────────────
    if latest["sga_ratio"] > 40 and gm >= bgm:
        challenges.append(
            f"粗利は十分だが販管費比率 {latest['sga_ratio']:.1f}% が高く、利益を圧迫している（典型的な「稼ぐが使いすぎ」型）"
        )
        actions.append("販管費の三大費目（人件費・地代家賃・広告宣伝費）を売上比で過去3年分並べ、増加率が売上成長を超えている費目から着手する")
    elif latest["sga_ratio"] > 40:
        challenges.append(f"販管費比率 {latest['sga_ratio']:.1f}% が高水準")

    if latest["cogs_ratio"] > 80:
        challenges.append(f"売上原価率 {latest['cogs_ratio']:.1f}% が高く、薄利構造になっている")

    # ── 純利益・段差チェック ─────────────────────────────────────────────────
    if nm < 0 <= om:
        weaknesses.append(f"営業黒字なのに最終赤字（純利益率 {nm:.1f}%）。営業外費用・特別損失・税負担のどこで沈んだか要確認")
    elif nm < 0:
        weaknesses.append(f"最終利益が赤字（純利益率 {nm:.1f}%）")
    elif nm >= bnm * 1.5:
        strengths.append(f"純利益率 {nm:.1f}% が業界平均 {bnm:.1f}% の1.5倍超で、高い最終収益力を持つ")

    if latest["ordinary_margin"] < om - 1.0:
        challenges.append(
            f"経常利益率（{latest['ordinary_margin']:.1f}%）が営業利益率（{om:.1f}%）より低く、"
            "支払利息など営業外費用の負担が大きい。借入構成・金利の見直し余地がある"
        )

    # ── トレンド分析（複数年）─────────────────────────────────────────────────
    if n >= 2:
        prev = metrics_list[-2]
        rev_yoy = yoy_change(latest["revenue"], prev["revenue"])
        op_yoy  = yoy_change(latest["operating_profit"], prev["operating_profit"])

        if rev_yoy is not None:
            if rev_yoy >= 10:
                strengths.append(f"売上高が前期比 +{rev_yoy:.1f}% と力強く成長している")
            elif rev_yoy < -5:
                weaknesses.append(f"売上高が前期比 {rev_yoy:.1f}% と減収")
                actions.append("減収要因の分解: 「客数×単価」または「既存顧客×新規顧客」で減収の主因を特定し、対策の優先度を決める")

        if op_yoy is not None and rev_yoy is not None:
            if op_yoy >= 20:
                strengths.append(f"営業利益が前期比 +{op_yoy:.1f}% と大幅増益")
            elif op_yoy < -20:
                challenges.append(f"営業利益が前期比 {op_yoy:.1f}% と大幅減益")
            # 増収減益の検出
            if rev_yoy > 3 and op_yoy < -3:
                challenges.append("「増収減益」パターン: 売上は伸びているのに利益が減っている。値引き販売やコスト増の可能性が高い")
                actions.append("増収減益の典型原因（①値引き・低粗利商品へのシフト ②人件費等の固定費先行 ③原材料高の転嫁遅れ）のどれかを粗利率推移で切り分ける")

        # 利益率の方向性（最古期 vs 最新期）
        om_diff = latest["operating_margin"] - metrics_list[0]["operating_margin"]
        if n >= 3:
            if om_diff >= 2:
                strengths.append(f"営業利益率が {n}期で {om_diff:+.1f}pt 改善傾向にあり、収益構造が良化している")
            elif om_diff <= -2:
                weaknesses.append(f"営業利益率が {n}期で {om_diff:+.1f}pt 悪化傾向にある")

        # 黒字転換・赤字転落
        if prev["operating_profit"] <= 0 < latest["operating_profit"]:
            strengths.append("営業利益が黒字転換した")
        if latest["operating_profit"] <= 0 < prev["operating_profit"]:
            weaknesses.append("営業利益が赤字に転落した")

    # ── デフォルト文 ─────────────────────────────────────────────────────────
    if not strengths:
        strengths.append("業界平均に近い水準で、バランスの取れた財務構造")
    if not weaknesses:
        weaknesses.append("目立った弱みは見当たりません")
    if not challenges:
        challenges.append("現状の収益構造を維持しつつ、さらなる利益率向上を目指したい")
    if not actions:
        actions.append("現状維持でOK。あえて挙げるなら、利益率トップの商品・サービスへの経営資源シフトで上積みを狙う")

    return {"strengths": strengths, "weaknesses": weaknesses, "challenges": challenges, "actions": actions}


# ── 2社比較 ───────────────────────────────────────────────────────────────────

def compare_companies(name_a: str, metrics_a: list[dict], score_a: dict,
                      name_b: str, metrics_b: list[dict], score_b: dict) -> dict:
    """項目別の優劣判定と総評を返す."""
    la, lb = metrics_a[-1], metrics_b[-1]

    rows = []

    def add_row(item, va, vb, fmt="{:.1f}%", higher_is_better=True):
        if va is None or vb is None:
            winner = "—"
        elif abs(va - vb) < 1e-9:
            winner = "引き分け"
        else:
            winner = name_a if (va > vb) == higher_is_better else name_b
        rows.append({
            "項目": item,
            name_a: fmt.format(va) if va is not None else "—",
            name_b: fmt.format(vb) if vb is not None else "—",
            "優勢": winner,
        })

    add_row("粗利率",     la["gross_margin"],     lb["gross_margin"])
    add_row("営業利益率", la["operating_margin"], lb["operating_margin"])
    add_row("経常利益率", la["ordinary_margin"],  lb["ordinary_margin"])
    add_row("純利益率",   la["net_margin"],       lb["net_margin"])
    add_row("売上成長率（年率）", score_a.get("rev_growth"), score_b.get("rev_growth"), fmt="{:+.1f}%")
    add_row("営業利益成長率（年率）", score_a.get("op_growth"), score_b.get("op_growth"), fmt="{:+.1f}%")
    add_row("総合スコア", score_a["total"], score_b["total"], fmt="{:.1f}点")

    wins_a = sum(1 for r in rows if r["優勢"] == name_a)
    wins_b = sum(1 for r in rows if r["優勢"] == name_b)

    if wins_a > wins_b:
        verdict = f"**{name_a}** が {wins_a}勝{wins_b}敗で優勢。"
    elif wins_b > wins_a:
        verdict = f"**{name_b}** が {wins_b}勝{wins_a}敗で優勢。"
    else:
        verdict = f"両社互角（{wins_a}勝{wins_b}敗）。"

    # 特徴づけ: 収益性型か成長型か
    if score_a.get("rev_growth") is not None and score_b.get("rev_growth") is not None:
        if la["operating_margin"] > lb["operating_margin"] and score_a["rev_growth"] < score_b["rev_growth"]:
            verdict += f" {name_a}は「収益性重視型」、{name_b}は「成長重視型」の構造。"
        elif lb["operating_margin"] > la["operating_margin"] and score_b["rev_growth"] < score_a["rev_growth"]:
            verdict += f" {name_b}は「収益性重視型」、{name_a}は「成長重視型」の構造。"

    return {"rows": rows, "verdict": verdict}


# ── デモデータ ────────────────────────────────────────────────────────────────

DEMO_COMPANIES = {
    "デモA: 高収益IT企業（成長鈍化）": {
        "industry": "IT・ソフトウェア",
        "periods": [
            {"label": "2022年3月期", "revenue":  8_000, "cogs": 3_200, "sga": 3_000, "non_op_income":  50, "non_op_expense":  30, "extra_gain":  0, "extra_loss":   0, "tax":  550},
            {"label": "2023年3月期", "revenue":  9_500, "cogs": 3_900, "sga": 3_600, "non_op_income":  60, "non_op_expense":  40, "extra_gain":  0, "extra_loss":   0, "tax":  620},
            {"label": "2024年3月期", "revenue": 10_500, "cogs": 4_400, "sga": 4_100, "non_op_income":  70, "non_op_expense":  40, "extra_gain":  0, "extra_loss": 100, "tax":  590},
            {"label": "2025年3月期", "revenue": 11_000, "cogs": 4_700, "sga": 4_500, "non_op_income":  80, "non_op_expense":  50, "extra_gain":  0, "extra_loss":   0, "tax":  560},
            {"label": "2026年3月期", "revenue": 11_200, "cogs": 4_900, "sga": 4_700, "non_op_income":  80, "non_op_expense":  50, "extra_gain":  0, "extra_loss":   0, "tax":  500},
        ],
    },
    "デモB: 急成長スタートアップ（薄利）": {
        "industry": "IT・ソフトウェア",
        "periods": [
            {"label": "2022年3月期", "revenue":  1_200, "cogs":   700, "sga":   700, "non_op_income":   5, "non_op_expense":  20, "extra_gain":  0, "extra_loss":   0, "tax":    0},
            {"label": "2023年3月期", "revenue":  2_200, "cogs": 1_250, "sga": 1_100, "non_op_income":  10, "non_op_expense":  30, "extra_gain":  0, "extra_loss":   0, "tax":    0},
            {"label": "2024年3月期", "revenue":  3_800, "cogs": 2_100, "sga": 1_600, "non_op_income":  15, "non_op_expense":  40, "extra_gain":  0, "extra_loss":   0, "tax":   20},
            {"label": "2025年3月期", "revenue":  6_200, "cogs": 3_300, "sga": 2_500, "non_op_income":  20, "non_op_expense":  50, "extra_gain":  0, "extra_loss":   0, "tax":  100},
            {"label": "2026年3月期", "revenue":  9_500, "cogs": 4_900, "sga": 3_700, "non_op_income":  30, "non_op_expense":  60, "extra_gain":  0, "extra_loss":   0, "tax":  250},
        ],
    },
    "デモC: 老舗製造業（じり貧型）": {
        "industry": "製造業",
        "periods": [
            {"label": "2022年3月期", "revenue": 20_000, "cogs": 16_200, "sga": 2_800, "non_op_income": 100, "non_op_expense": 200, "extra_gain":   0, "extra_loss":   0, "tax": 280},
            {"label": "2023年3月期", "revenue": 19_200, "cogs": 15_800, "sga": 2_750, "non_op_income": 100, "non_op_expense": 210, "extra_gain":   0, "extra_loss":  50, "tax": 150},
            {"label": "2024年3月期", "revenue": 18_500, "cogs": 15_400, "sga": 2_700, "non_op_income":  90, "non_op_expense": 220, "extra_gain": 200, "extra_loss":   0, "tax": 130},
            {"label": "2025年3月期", "revenue": 17_800, "cogs": 15_000, "sga": 2_650, "non_op_income":  90, "non_op_expense": 230, "extra_gain":   0, "extra_loss": 300, "tax":  40},
            {"label": "2026年3月期", "revenue": 17_200, "cogs": 14_700, "sga": 2_600, "non_op_income":  80, "non_op_expense": 240, "extra_gain":   0, "extra_loss":   0, "tax":  20},
        ],
    },
}
