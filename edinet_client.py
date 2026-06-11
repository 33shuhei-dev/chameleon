"""
edinet_client.py - 金融庁 EDINET API v2 クライアント

企業名で有価証券報告書を検索し、損益計算書（P/L）の数値を自動抽出する。

利用には EDINET API のAPIキー（無料）が必要:
  https://api.edinet-fsa.go.jp/ から利用登録 → 環境変数 EDINET_API_KEY に設定

注意: EDINET APIには「企業名検索」エンドポイントが存在しないため、
日付ごとの提出書類一覧を遡って取得し、提出者名でフィルタする方式をとる。
日次一覧は cache/edinet/ にディスクキャッシュされ、2回目以降の検索は高速。
"""

from __future__ import annotations

import csv
import io
import json
import os
import zipfile
from datetime import date, timedelta
from pathlib import Path

import httpx

API_BASE  = "https://api.edinet-fsa.go.jp/api/v2"
CACHE_DIR = Path("cache/edinet")

# docTypeCode: 120=有価証券報告書, 140=四半期報告書, 160=半期報告書
DOC_TYPE_NAMES = {"120": "有価証券報告書", "140": "四半期報告書", "160": "半期報告書"}

# ── P/L要素の優先順位リスト（日本基準 → IFRS の順に試す）──────────────────────
ELEMENT_PRIORITY = {
    "revenue": [
        "NetSales", "OperatingRevenue1", "OperatingRevenue", "OperatingRevenues",
        "Revenue", "Revenues", "NetSalesOfCompletedConstructionContracts",
        "NetSalesIFRS", "RevenueIFRS", "RevenuesIFRS", "OperatingRevenuesIFRS", "SalesIFRS",
    ],
    "cogs":           ["CostOfSales", "CostOfSalesIFRS"],
    "sga":            ["SellingGeneralAndAdministrativeExpenses", "SellingGeneralAndAdministrativeExpensesIFRS"],
    "gross":          ["GrossProfit", "GrossProfitIFRS"],
    "operating":      ["OperatingIncome", "OperatingProfitLossIFRS", "OperatingIncomeIFRS"],
    "non_op_income":  ["NonOperatingIncome"],
    "non_op_expense": ["NonOperatingExpenses"],
    "ordinary":       ["OrdinaryIncome", "OrdinaryProfitLoss"],
    "extra_gain":     ["ExtraordinaryIncome"],
    "extra_loss":     ["ExtraordinaryLoss", "ExtraordinaryLosses"],
    "tax":            ["IncomeTaxes", "IncomeTaxExpenseIFRS"],
    "net":            [
        "ProfitLoss", "ProfitLossAttributableToOwnersOfParent",
        "ProfitLossIFRS", "ProfitLossAttributableToOwnersOfParentIFRS",
    ],
}


def get_api_key() -> str | None:
    return os.getenv("EDINET_API_KEY") or None


# ── 日次書類一覧（ディスクキャッシュ付き）──────────────────────────────────────

def _fetch_daily_list(day: date, api_key: str) -> list[dict]:
    """指定日の提出書類一覧を返す。cache/edinet/YYYY-MM-DD.json にキャッシュ."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = CACHE_DIR / f"{day.isoformat()}.json"
    if cache_file.exists():
        with open(cache_file, encoding="utf-8") as f:
            return json.load(f)

    resp = httpx.get(
        f"{API_BASE}/documents.json",
        params={"date": day.isoformat(), "type": 2, "Subscription-Key": api_key},
        timeout=30,
    )
    resp.raise_for_status()
    results = resp.json().get("results", []) or []

    # 必要なフィールドだけ保存してキャッシュを軽くする
    slim = [
        {
            "docID":          r.get("docID"),
            "filerName":      r.get("filerName"),
            "docTypeCode":    r.get("docTypeCode"),
            "docDescription": r.get("docDescription"),
            "periodEnd":      r.get("periodEnd"),
            "secCode":        r.get("secCode"),
            "submitDateTime": r.get("submitDateTime"),
        }
        for r in results
        if r.get("docTypeCode") in DOC_TYPE_NAMES
    ]
    # 当日分は提出が続く可能性があるためキャッシュしない
    if day < date.today():
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(slim, f, ensure_ascii=False)
    return slim


def search_documents(
    company_name: str,
    api_key: str,
    days: int = 400,
    doc_types: tuple[str, ...] = ("120",),
    progress=None,
) -> list[dict]:
    """
    企業名（部分一致）で提出書類を検索する。今日から days 日分を遡る。
    progress: callable(done, total) — UI側のプログレスバー更新用
    """
    name = company_name.strip()
    if not name or not api_key:
        return []

    hits = []
    today = date.today()
    scan_days = [today - timedelta(days=i) for i in range(days)]
    scan_days = [d for d in scan_days if d.weekday() < 5]  # 土日は提出なし

    for i, day in enumerate(scan_days):
        try:
            for doc in _fetch_daily_list(day, api_key):
                if doc["docTypeCode"] in doc_types and name in (doc["filerName"] or ""):
                    doc["submitDate"] = day.isoformat()
                    doc["docTypeName"] = DOC_TYPE_NAMES.get(doc["docTypeCode"], doc["docTypeCode"])
                    hits.append(doc)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403):
                raise RuntimeError("EDINET APIキーが無効です。https://api.edinet-fsa.go.jp/ で取得したキーを確認してください。") from exc
            # 個別日の失敗はスキップして続行
        except httpx.HTTPError:
            pass
        if progress:
            progress(i + 1, len(scan_days))

    # 新しい提出順
    hits.sort(key=lambda d: d["submitDate"], reverse=True)
    return hits


# ── 財務諸表CSVの取得とP/L抽出 ────────────────────────────────────────────────

def _download_csv_zip(doc_id: str, api_key: str) -> bytes:
    resp = httpx.get(
        f"{API_BASE}/documents/{doc_id}",
        params={"type": 5, "Subscription-Key": api_key},  # type=5: CSV形式
        timeout=60,
    )
    resp.raise_for_status()
    if "application/json" in resp.headers.get("content-type", ""):
        raise RuntimeError(f"CSVを取得できませんでした: {resp.json()}")
    return resp.content


def _parse_csv_rows(zip_bytes: bytes) -> list[dict]:
    """zip内の報告書CSV（タブ区切り・UTF-16）を行のリストに変換."""
    rows = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for info in zf.infolist():
            fname = Path(info.filename).name
            # jpcrp = 企業内容開示府令の本表。監査報告書(jpaud)等は除外
            if not fname.startswith("jpcrp") or not fname.endswith(".csv"):
                continue
            with zf.open(info) as f:
                text = f.read().decode("utf-16", errors="replace")
            reader = csv.DictReader(io.StringIO(text), delimiter="\t")
            for row in reader:
                rows.append({
                    "element": (row.get("要素ID") or "").split(":")[-1],
                    "context": row.get("コンテキストID") or "",
                    "value":   row.get("値") or "",
                })
    return rows


def _pick(values: dict, field: str, contexts: list[str]) -> float | None:
    """優先順位リストとコンテキスト順に従って値を探す."""
    for elem in ELEMENT_PRIORITY[field]:
        for ctx in contexts:
            v = values.get((elem, ctx))
            if v is not None:
                return v
    return None


def _extract_period(values: dict, duration: str, consolidated: bool) -> dict | None:
    """1期分（duration = 'CurrentYearDuration' 等）のP/L入力値を組み立てる."""
    suffix = "" if consolidated else "_NonConsolidatedMember"
    ctxs = [duration + suffix]

    revenue = _pick(values, "revenue", ctxs)
    if revenue is None or revenue <= 0:
        return None

    cogs      = _pick(values, "cogs", ctxs)
    sga       = _pick(values, "sga", ctxs)
    gross     = _pick(values, "gross", ctxs)
    operating = _pick(values, "operating", ctxs)
    nop_inc   = _pick(values, "non_op_income", ctxs)
    nop_exp   = _pick(values, "non_op_expense", ctxs)
    ordinary  = _pick(values, "ordinary", ctxs)
    eg        = _pick(values, "extra_gain", ctxs) or 0.0
    el        = _pick(values, "extra_loss", ctxs) or 0.0
    tax       = _pick(values, "tax", ctxs)
    net       = _pick(values, "net", ctxs)

    # ── 欠損値の導出（IFRS企業は経常・特別の区分がない等）─────────────────────
    if cogs is None:
        if gross is not None:
            cogs = revenue - gross
        elif operating is not None and sga is not None:
            cogs = revenue - operating - sga
        else:
            cogs = 0.0
    if sga is None:
        if gross is not None and operating is not None:
            sga = gross - operating
        elif operating is not None:
            sga = revenue - cogs - operating
        else:
            sga = 0.0
    calc_operating = revenue - cogs - sga

    if nop_inc is None or nop_exp is None:
        if ordinary is not None:
            diff = ordinary - calc_operating
            nop_inc, nop_exp = (diff, 0.0) if diff >= 0 else (0.0, -diff)
        else:
            # IFRS: 経常の概念がないため営業利益=経常利益とみなす
            nop_inc, nop_exp = 0.0, 0.0
            ordinary = calc_operating
    if ordinary is None:
        ordinary = calc_operating + nop_inc - nop_exp

    if tax is None:
        if net is not None:
            tax = (ordinary + eg - el) - net
        else:
            tax = 0.0

    return {
        "revenue": revenue, "cogs": cogs, "sga": sga,
        "non_op_income": nop_inc, "non_op_expense": nop_exp,
        "extra_gain": eg, "extra_loss": el, "tax": tax,
    }


def fetch_pl(doc_id: str, api_key: str, period_end: str = "") -> dict:
    """
    書類ID（docID）からP/L数値を抽出する。
    有報には当期と前期の両方が含まれるため、最大2期分を返す。

    戻り値: {"periods": [前期, 当期], "consolidated": bool, "unit": "百万円"}
    金額は百万円に丸めて返す。
    """
    rows = _parse_csv_rows(_download_csv_zip(doc_id, api_key))

    values: dict[tuple[str, str], float] = {}
    for r in rows:
        try:
            values[(r["element"], r["context"])] = float(r["value"])
        except (ValueError, TypeError):
            continue

    # 連結があれば連結を優先、なければ単体
    consolidated = _pick(values, "revenue", ["CurrentYearDuration"]) is not None

    periods = []
    year = int(period_end[:4]) if period_end[:4].isdigit() else None
    for duration, offset in [("Prior1YearDuration", -1), ("CurrentYearDuration", 0)]:
        p = _extract_period(values, duration, consolidated)
        if p:
            # 円 → 百万円
            p = {k: round(v / 1_000_000, 1) for k, v in p.items()}
            p["label"] = f"{year + offset}年{int(period_end[5:7])}月期" if year else duration
            periods.append(p)

    if not periods:
        raise RuntimeError("この書類からP/L数値を抽出できませんでした（対応していない会計基準・様式の可能性があります）")

    return {"periods": periods, "consolidated": consolidated, "unit": "百万円"}
