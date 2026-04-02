"""
demo_run.py - Execute 10 decisions using mock_data/.

Reproduces all 4 market states:
  STEALTH  → BUY
  CHASE    → BUY
  ESCAPE   → SELL
  SLEEP    → NO ACTION

Run:  python demo_run.py
Logs written to logs/
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

import strategy
import executor
from risk_manager import RiskManager

# ── Setup ─────────────────────────────────────────────────────────────────────
LOG_DIR  = Path("logs")
MOCK_DIR = Path("mock_data")
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "demo_run.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("demo_run")

# ── 10-decision scenario sequence ────────────────────────────────────────────
# Covers all 4 modes multiple times, including sequential state transitions.
DEMO_SEQUENCE = [
    ("stealth", "SHADOW9"),    # 1  STEALTH  -> BUY SHADOW9
    ("escape",  "SHADOW9"),    # 2  ESCAPE   -> SELL SHADOW9 (close)
    ("chase",   "ROCKETFI"),   # 3  CHASE    -> BUY ROCKETFI
    ("sleep",   "FLATLINE"),   # 4  SLEEP    -> NO ACTION
    ("escape",  "ROCKETFI"),   # 5  ESCAPE   -> SELL ROCKETFI (close)
    ("stealth", "SHADOW9"),    # 6  STEALTH  -> BUY SHADOW9
    ("chase",   "ROCKETFI"),   # 7  CHASE    -> BLOCKED (SHADOW9 still open)
    ("sleep",   "FLATLINE"),   # 8  SLEEP    -> NO ACTION
    ("escape",  "SHADOW9"),    # 9  ESCAPE   -> SELL SHADOW9 (close)
    ("sleep",   "FLATLINE"),   # 10 SLEEP    -> NO ACTION
]


def _convert_mock(raw: dict) -> dict:
    """旧モック形式を REST API レスポンス形式に変換する。"""
    h  = raw.get("holdings", {})
    n  = raw.get("netflow", raw.get("inflows", {}))
    d  = raw.get("dex_trades", {})
    p  = raw.get("price", {})
    fi = raw.get("flow_intelligence", {})
    return {
        "token": raw.get("token", ""),
        "holdings": {"data": {
            "holderCount":         h.get("sm_holder_count_now", 0),
            "holderCountChange6h": h.get("sm_holder_change_pct", 0.0),
            "concentrationScore":  fi.get("dispersion_score", 0.5) * -1 + 1,
            "top10HoldersPct":     h.get("concentration_score", 0.5),
        }},
        "inflows": {"data": {
            "netflow1h":         n.get("netflow_1h", 0),
            "netflow6h":         n.get("netflow_6h", 0),
            "avgNetflow1h":      n.get("avg_netflow_1h_recent", 1),
            "direction":         n.get("netflow_direction", "neutral"),
            "largeSellCount1h":  d.get("large_sells", 0),
            "volume1hUsd":       d.get("volume_1h_usd", 0),
            "liquidityUsd":      p.get("liquidity_usd", 0),
            "priceChange6hPct":  p.get("price_change_6h_pct", 0.0),
        }},
        "dcas": {"data": {
            "dcaCount1h":     d.get("tx_count_1h", 0),
            "dcaCountPrev1h": d.get("tx_count_prev_1h", 1),
        }},
    }


def load_scenario(scenario: str) -> dict | None:
    path = MOCK_DIR / f"{scenario}.json"
    if not path.exists():
        logger.error("Mock file not found: %s", path)
        return None
    with open(path) as f:
        return _convert_mock(json.load(f))


def save_log(entry: dict):
    ts   = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    name = f"{ts}_{entry['token']}_{entry['mode']}.json"
    path = LOG_DIR / name
    with open(path, "w") as f:
        json.dump(entry, f, indent=2)
    return path


def print_decision(n: int, entry: dict):
    print(f"\n{'─' * 50}")
    print(f"Decision #{n}")
    print(f"MODE={entry['mode']}")
    print(f"TOKEN={entry['token']}")
    print(f"ACTION={entry['action']}")
    print(f"REASON={entry['reason']}")
    print(f"CONFIDENCE={entry['confidence']}")
    if entry.get("result"):
        print(f"RESULT={entry['result']}")


def run_demo():
    print("\n" + "=" * 60)
    print("CHAMELEON BOT - DEMO RUN")
    print("10 decisions across all 4 market states")
    print("=" * 60)

    risk = RiskManager()
    results = []

    for idx, (scenario, token) in enumerate(DEMO_SEQUENCE, start=1):
        data = load_scenario(scenario)
        if data is None:
            logger.warning("Skipping decision %d - no data", idx)
            continue

        # Override token in nested data to match the scenario token key
        data["token"] = token

        mode, reason, confidence = strategy.detect_mode(data)

        log_entry = {
            "timestamp":  datetime.now(timezone.utc).isoformat(),
            "token":      token,
            "mode":       mode,
            "action":     "NO ACTION",
            "reason":     reason,
            "confidence": confidence,
            "result":     "",
        }

        # ── Determine action ──────────────────────────────────────────────
        if mode in ("STEALTH", "CHASE"):
            allowed, gate_reason = risk.can_enter(mode, data)
            if allowed:
                log_entry["action"] = "BUY"
                trade = executor.execute_trade(token, "buy")
                log_entry["result"] = "paper trade: BUY queued" if trade["success"] else f"blocked: {trade['error']}"
                if trade["success"]:
                    price = data.get("price", {}).get("price_usd", 0.0)
                    risk.open_position(token, price, executor.TRADE_SIZE_SOL)
            else:
                log_entry["action"] = "BLOCKED"
                log_entry["result"] = gate_reason

        elif mode == "ESCAPE":
            log_entry["action"] = "SELL"
            holding = any(p["token"] == token for p in risk.open_positions)
            if holding:
                trade = executor.execute_trade(token, "sell")
                log_entry["result"] = "paper trade: SELL queued" if trade["success"] else f"failed: {trade['error']}"
                price = data.get("price", {}).get("price_usd", 0.0)
                risk.close_position(token, price, "exit")
            else:
                log_entry["action"] = "SELL (no position)"
                log_entry["result"] = "no open position to close"

        else:  # SLEEP
            log_entry["action"] = "NO ACTION"
            log_entry["result"] = "waiting for signal"

        print_decision(idx, log_entry)
        log_path = save_log(log_entry)
        logger.info("Logged → %s", log_path.name)
        results.append(log_entry)

    # ── Summary ───────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("DEMO COMPLETE - SUMMARY")
    print("=" * 60)
    mode_counts: dict[str, int] = {}
    for r in results:
        mode_counts[r["mode"]] = mode_counts.get(r["mode"], 0) + 1

    for mode, count in sorted(mode_counts.items()):
        print(f"  {mode:<8} : {count} decision(s)")

    print(f"\nTotal decisions : {len(results)}")
    print(f"Logs saved to   : {LOG_DIR.resolve()}")
    print()
    print("This is not a trading bot.")
    print("This is a market-state interpreter powered by Smart Money.")
    print("=" * 60)

    modes_seen = set(mode_counts.keys())
    required   = {"STEALTH", "CHASE", "ESCAPE", "SLEEP"}
    if required.issubset(modes_seen):
        print("\nAll 4 market states reproduced.")
    else:
        missing = required - modes_seen
        print(f"\nWARNING: missing modes in demo output: {missing}")

    return results


if __name__ == "__main__":
    run_demo()
