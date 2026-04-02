"""
strategy.py - Market state detection (STEALTH / CHASE / ESCAPE / SLEEP)
Nansen REST API response fields (verified from docs):
  holdings: holders_count, balance_24h_percent_change, share_of_holdings_percent
  netflow:  net_flow_1h_usd, net_flow_24h_usd, net_flow_7d_usd, trader_count
"""

import logging

logger = logging.getLogger(__name__)


def _first(data: dict, key: str, default=0):
    """Get a value from the first item in the data array."""
    try:
        items = data.get("data", [])
        if isinstance(items, list) and items:
            return items[0].get(key, default) or default
    except Exception:
        pass
    return default


def _sum_field(data: dict, key: str) -> float:
    """Sum a field across all items in the data array."""
    try:
        items = data.get("data", [])
        if isinstance(items, list):
            return sum(float(item.get(key, 0) or 0) for item in items)
    except Exception:
        pass
    return 0.0


def detect_mode(data: dict) -> tuple[str, str, float]:
    """
    Analyse Nansen data and return (mode, reason, confidence).
    mode: STEALTH | CHASE | ESCAPE | SLEEP
    """
    try:
        holdings = data.get("holdings", {})
        netflow  = data.get("netflow",  {})

        # ── holdingsから取得 ──────────────────────────────────────────────
        sm_holder_count  = _first(holdings, "holders_count", 0)
        sm_holder_change = _first(holdings, "balance_24h_percent_change", 0.0)
        share_pct        = _first(holdings, "share_of_holdings_percent", 0.0)
        concentration    = min(1.0, float(share_pct) / 100) if share_pct else 0.0

        # ── netflowから取得 ───────────────────────────────────────────────
        netflow_1h  = _sum_field(netflow, "net_flow_1h_usd")
        netflow_24h = _sum_field(netflow, "net_flow_24h_usd")
        trader_count = _first(netflow, "trader_count", 0)

        # 方向を判定（小型トークン対応で閾値を下げる）
        if netflow_1h > 10:
            direction = "positive"
        elif netflow_1h < -10:
            direction = "negative"
        else:
            direction = "neutral"

        # 大口売り：1h netflowが大きくマイナス
        avg_1h = netflow_24h / 24 if netflow_24h else 0
        large_sells = 1 if (netflow_1h < -100 and netflow_1h < avg_1h * 2) else 0

        # ── ESCAPE（最優先） ──────────────────────────────────────────────
        if (
            direction == "negative"
            and large_sells >= 1
            and sm_holder_change < 0
        ):
            reasons = [
                f"netflow negative ({netflow_1h:+.0f} USD/1h)",
                "large outflow detected",
                f"SM holders declining ({sm_holder_change:+.1f}%)",
            ]
            confidence = min(0.95, 0.6 + abs(sm_holder_change) / 100 + 0.1)
            return "ESCAPE", ", ".join(reasons), round(confidence, 2)

        # ── CHASE（モメンタム・STEALTHより優先） ────────────────────────
        nf_spike = netflow_1h > 500 and (avg_1h == 0 or netflow_1h > abs(avg_1h) * 1.5)

        if nf_spike and trader_count >= 2:
            reasons = [
                f"netflow spike ({netflow_1h:+.0f} USD/1h)",
                f"{trader_count} active SM traders",
            ]
            confidence = min(0.88, 0.60 + min(trader_count, 20) * 0.01)
            return "CHASE", ", ".join(reasons), round(confidence, 2)

        # ── STEALTH（早期蓄積） ───────────────────────────────────────────
        # sm_holder_changeが取れない場合はtrader_count>=1を代替シグナルとして使う
        holder_signal = sm_holder_change >= 0.5 or trader_count >= 1

        if (
            holder_signal
            and direction == "positive"
            and sm_holder_count >= 1
        ):
            reasons = [
                f"SM holders +{sm_holder_change:.1f}% (24h)" if sm_holder_change >= 1.0
                else f"{trader_count} active SM traders (proxy)",
                f"netflow positive ({netflow_1h:+.0f} USD/1h)",
                f"{sm_holder_count} SM wallets holding",
            ]
            confidence = min(0.92, 0.55 + max(sm_holder_change, trader_count * 0.5) / 50 + concentration * 0.2)
            return "STEALTH", ", ".join(reasons), round(confidence, 2)

        # ── SLEEP（デフォルト） ───────────────────────────────────────────
        reasons = []
        if sm_holder_count < 2:
            reasons.append(f"low SM activity ({sm_holder_count} holders)")
        if abs(netflow_1h) <= 100:
            reasons.append(f"netflow near zero ({netflow_1h:+.0f})")
        if trader_count < 2:
            reasons.append(f"few SM traders ({trader_count})")
        if not reasons:
            reasons = ["no clear signal"]

        confidence = round(min(0.85, 0.50 + concentration * 0.2), 2)
        return "SLEEP", ", ".join(reasons), confidence

    except Exception as exc:
        logger.error("detect_mode error: %s", exc)
        return "SLEEP", f"detection error: {exc}", 0.0
