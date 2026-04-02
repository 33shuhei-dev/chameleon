"""
chameleon.py - Main loop (10-minute cycle).

This is not a trading bot.
This is a market-state interpreter powered by Smart Money.
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

import nansen_client
import strategy
import executor
import scanner
import universe
from risk_manager import RiskManager
from api_usage_logger import log_api_usage, log_decision, log_cycle_summary

# ── Config ───────────────────────────────────────────────────────────────────
USE_MOCK   = os.getenv("USE_MOCK", "false").lower() == "true"
CYCLE_SECS = int(os.getenv("CYCLE_SECS", "600"))   # 10分
LOG_DIR    = Path("logs")

LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "chameleon.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("chameleon")

risk = RiskManager()


# ── Mock helpers ──────────────────────────────────────────────────────────────

def _load_mock(token: str) -> dict | None:
    for scenario in ["stealth", "chase", "escape", "sleep"]:
        path = Path("mock_data") / f"{scenario}.json"
        if path.exists():
            with open(path) as f:
                data = json.load(f)
            if data.get("token") == token:
                return _convert_mock(data)
    return None


def _convert_mock(raw: dict) -> dict:
    h  = raw.get("holdings", {})
    n  = raw.get("netflow", raw.get("inflows", {}))
    d  = raw.get("dex_trades", {})
    p  = raw.get("price", {})
    fi = raw.get("flow_intelligence", {})
    return {
        "token": raw.get("token", ""),
        "holdings": {"data": [{
            "holders_count":              h.get("sm_holder_count_now", 0),
            "balance_24h_percent_change": h.get("sm_holder_change_pct", 0.0),
            "share_of_holdings_percent":  h.get("concentration_score", 0.5) * 100,
        }]},
        "netflow": {"data": [{
            "net_flow_1h_usd":  n.get("netflow_1h", 0),
            "net_flow_24h_usd": n.get("netflow_6h", 0) * 4,
            "net_flow_7d_usd":  0,
            "trader_count":     d.get("tx_count_1h", 0),
        }]},
        "dcas": {"data": []},
    }


# ── Log helpers ───────────────────────────────────────────────────────────────

def _save_log(entry: dict):
    ts   = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    name = f"{ts}_{entry['token'][:12]}_{entry['mode']}.json"
    with open(LOG_DIR / name, "w", encoding="utf-8") as f:
        json.dump(entry, f, indent=2, ensure_ascii=False)


def _print_decision(entry: dict):
    symbol = entry.get("symbol", entry["token"][:12])
    print(
        f"\nMODE={entry['mode']}\n"
        f"TOKEN={symbol}\n"
        f"ACTION={entry['action']}\n"
        f"REASON={entry['reason']}\n"
        f"CONFIDENCE={entry['confidence']}"
    )


# ── Core decision ─────────────────────────────────────────────────────────────

def process_token(token_address: str, symbol: str = "") -> dict:
    log_entry = {
        "timestamp":  datetime.now(timezone.utc).isoformat(),
        "token":      token_address,
        "symbol":     symbol,
        "mode":       "SLEEP",
        "action":     "NO ACTION",
        "reason":     "",
        "confidence": 0.0,
        "result":     "",
    }

    try:
        if USE_MOCK:
            data = _load_mock(token_address)
            if data is None:
                log_entry["reason"] = "no mock data found"
                return log_entry
        else:
            data = nansen_client.fetch_all(token_address)
            if data is None:
                log_entry["reason"] = "data fetch failed"
                return log_entry

        mode, reason, confidence = strategy.detect_mode(data)
        log_entry["mode"]       = mode
        log_entry["reason"]     = reason
        log_entry["confidence"] = confidence

        if mode in ("STEALTH", "CHASE"):
            allowed, gate_reason = risk.can_enter(mode, data)
            if allowed:
                log_entry["action"] = "BUY"
                trade = executor.execute_trade(token_address, "buy")
                log_entry["result"] = "executed" if trade["success"] else f"failed: {trade['error']}"
                if trade["success"]:
                    risk.open_position(token_address, 0.0, executor.TRADE_SIZE_SOL)
            else:
                log_entry["action"] = "BLOCKED"
                log_entry["result"] = gate_reason

        elif mode == "ESCAPE":
            log_entry["action"] = "SELL"
            holding = any(p["token"] == token_address for p in risk.open_positions)
            if holding:
                trade = executor.execute_trade(token_address, "sell")
                log_entry["result"] = "executed" if trade["success"] else f"failed: {trade['error']}"
                risk.close_position(token_address, 0.0, "exit")
            else:
                log_entry["action"] = "SELL (no position)"
                log_entry["result"] = "no open position to close"

        else:
            log_entry["action"] = "NO ACTION"
            log_entry["result"] = "waiting"

    except SystemExit:
        raise
    except Exception as exc:
        logger.error("process_token(%s) error: %s", symbol or token_address, exc)
        log_entry["reason"] = f"error: {exc}"
        log_entry["result"] = "error"

    return log_entry


# ── Main loop ─────────────────────────────────────────────────────────────────

def main():
    logger.info("=" * 60)
    logger.info("CHAMELEON BOT - starting (USE_MOCK=%s, CYCLE=%ds)", USE_MOCK, CYCLE_SECS)
    logger.info("This is not a trading bot.")
    logger.info("This is a market-state interpreter powered by Smart Money.")
    logger.info("=" * 60)

    uni = universe.load()

    while True:
        if risk.daily_halted:
            logger.warning("Daily halt active - skipping cycle.")
            time.sleep(CYCLE_SECS)
            continue

        cycle_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        api_calls_this_cycle = 0
        mode_counts = {"STEALTH": 0, "CHASE": 0, "ESCAPE": 0, "SLEEP": 0}

        # ── Step1: スキャンしてwatchlistを更新 ──────────────────────────
        if not USE_MOCK:
            logger.info("Scanning top tokens from Nansen...")
            top_tokens = scanner.scan()
            api_calls_this_cycle += 1  # scanner は1回のAPIコール
            for token_info in top_tokens:
                universe.add_to_watchlist(uni, token_info)
            universe.cleanup_stale(uni)
            universe.save(uni)
            logger.info("Watchlist size: %d tokens", len(uni["watchlist"]))

        # ── Step2: watchlist内のトークンを分析 ──────────────────────────
        if USE_MOCK:
            # モード時は固定アドレスで動作確認
            targets = [
                ("SHADOW9",  "SHADOW9"),
                ("ROCKETFI", "ROCKETFI"),
                ("FLATLINE", "FLATLINE"),
            ]
        else:
            targets = [
                (addr, info.get("token_symbol", addr[:8]))
                for addr, info in uni["watchlist"].items()
            ]

        if not targets:
            logger.info("No tokens to analyze this cycle.")
        else:
            for token_address, symbol in targets:
                entry = process_token(token_address, symbol)

                # universe の mode_streak を更新
                if not USE_MOCK:
                    universe.update_mode(uni, token_address, entry["mode"])

                    # STEALTH 3回連続 → CHASE 昇格
                    if entry["mode"] == "STEALTH":
                        streak = universe.get_streak(uni, token_address, "STEALTH")
                        if streak >= 3:
                            logger.info(
                                "%-10s STEALTH streak=%d → upgrading to CHASE",
                                symbol[:10], streak,
                            )
                            entry["mode"]   = "CHASE"
                            entry["action"] = "BUY (streak upgrade)"
                            entry["reason"] += f" | STEALTH streak={streak}"

                _print_decision(entry)
                _save_log(entry)
                logger.info(
                    "%-10s MODE=%-7s ACTION=%-20s CONFIDENCE=%.2f",
                    symbol[:10], entry["mode"], entry["action"], entry["confidence"],
                )

                # 証拠ログ
                if not USE_MOCK:
                    api_calls_this_cycle += 2  # holdings + netflow
                    log_api_usage(
                        cycle_id=cycle_id,
                        endpoint="smart-money/holdings",
                        token=token_address,
                        chain="solana",
                        status_code=200 if entry["reason"] != "data fetch failed" else 500,
                        response_summary={"source": "nansen", "symbol": symbol},
                        used_in_decision=True,
                    )
                    log_api_usage(
                        cycle_id=cycle_id,
                        endpoint="smart-money/netflow",
                        token=token_address,
                        chain="solana",
                        status_code=200 if entry["reason"] != "data fetch failed" else 500,
                        response_summary={"source": "nansen", "symbol": symbol},
                        used_in_decision=True,
                    )
                    log_decision(
                        cycle_id=cycle_id,
                        token=token_address,
                        chain="solana",
                        mode=entry["mode"],
                        action=entry["action"],
                        confidence=entry["confidence"],
                        reason=entry["reason"],
                    )
                    mode_counts[entry["mode"]] = mode_counts.get(entry["mode"], 0) + 1

            if not USE_MOCK:
                universe.save(uni)

        if not USE_MOCK:
            log_cycle_summary(
                cycle_id=cycle_id,
                watchlist_size=len(uni.get("watchlist", {})),
                api_calls=api_calls_this_cycle,
                mode_counts=mode_counts,
            )

        logger.info("Cycle complete. Sleeping %ds.", CYCLE_SECS)
        time.sleep(CYCLE_SECS)


if __name__ == "__main__":
    main()
