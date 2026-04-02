"""
scanner.py - Solanaトークンのユニバーススキャン

取得元: /smart-money/netflow
ソート: net_flow_1h_usd DESC
= 直近1時間でSMが最も動かしたトークンを上位に取得する
"""

import logging
import os

import httpx

logger = logging.getLogger(__name__)

BASE_URL   = "https://api.nansen.ai/api/v1"
API_KEY    = os.getenv("NANSEN_API_KEY", "")
TIMEOUT    = 30
SCAN_TOP_N = int(os.getenv("SCAN_TOP_N", "5"))


def _headers() -> dict:
    return {
        "Content-Type": "application/json",
        "apikey": API_KEY,
    }


def fetch_top_tokens(n: int = SCAN_TOP_N) -> list[dict]:
    """
    直近1時間のSMネットフローが大きい上位Nトークンを取得する。
    = SMが今まさに動いてるトークンを拾う
    """
    try:
        response = httpx.post(
            f"{BASE_URL}/smart-money/netflow",
            headers=_headers(),
            json={
                "chains": ["solana"],
                "filters": {
                    "include_native_tokens": False,
                    "include_stablecoins":   False,
                },
                "pagination": {"page": 1, "per_page": n},
                "order_by": [{"field": "net_flow_1h_usd", "direction": "DESC"}],
            },
            timeout=TIMEOUT,
        )

        if response.status_code == 402:
            raise SystemExit("CREDITS_EXHAUSTED - stopping immediately.")

        if response.status_code != 200:
            logger.error("scan error %d: %s", response.status_code, response.text[:200])
            return []

        items = response.json().get("data", [])
        logger.info("Scanned %d tokens from Nansen (netflow 1h DESC)", len(items))
        return items

    except SystemExit:
        raise
    except Exception as exc:
        logger.error("fetch_top_tokens error: %s", exc)
        return []


def score_token(item: dict) -> float:
    """
    netflowデータからスコアをつける（0.0〜1.0）

    ウェイト:
    - net_flow_1h_usd  : 50%  直近の動き（最重要）
    - net_flow_24h_usd : 20%  24hトレンド方向
    - trader_count     : 20%  SM参加人数（多いほど信頼性高）
    - token_age_days   : 10%  若いほど上昇余地あり（逆数）
    """
    score = 0.0

    nf_1h      = float(item.get("net_flow_1h_usd",  0) or 0)
    nf_24h     = float(item.get("net_flow_24h_usd", 0) or 0)
    traders    = int(item.get("trader_count",   0) or 0)
    age_days   = int(item.get("token_age_days", 9999) or 9999)

    # 1h netflow スコア（$50,000 で満点）
    if nf_1h > 0:
        score += min(nf_1h / 50_000, 1.0) * 0.5

    # 24h netflow 方向ボーナス（1hと同方向なら加点）
    if nf_1h > 0 and nf_24h > 0:
        score += 0.2

    # SMトレーダー数スコア（50人で満点）
    score += min(traders / 50, 1.0) * 0.2

    # トークン年齢スコア（若いほど高、365日以内で満点）
    if age_days < 365:
        score += (1 - age_days / 365) * 0.1

    return round(min(score, 1.0), 3)


def scan(n: int = SCAN_TOP_N) -> list[dict]:
    """
    スキャン実行。スコア付きトークンリストを返す。
    """
    items = fetch_top_tokens(n)
    if not items:
        return []

    results = []
    for item in items:
        score = score_token(item)
        results.append({
            "token_address":              item.get("token_address", ""),
            "token_symbol":               item.get("token_symbol", ""),
            "holders_count":              item.get("trader_count", 0),
            "balance_24h_percent_change": 0.0,
            "net_flow_1h_usd":            item.get("net_flow_1h_usd", 0),
            "net_flow_24h_usd":           item.get("net_flow_24h_usd", 0),
            "trader_count":               item.get("trader_count", 0),
            "token_age_days":             item.get("token_age_days", 0),
            "market_cap_usd":             item.get("market_cap_usd", 0),
            "score":                      score,
        })

    results.sort(key=lambda x: x["score"], reverse=True)

    if results:
        top = results[0]
        logger.info(
            "Top token: %s | 1h netflow=$%+.0f | traders=%d | score=%.3f",
            top["token_symbol"],
            top["net_flow_1h_usd"],
            top["trader_count"],
            top["score"],
        )
    return results
