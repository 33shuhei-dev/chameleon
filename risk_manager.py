"""
risk_manager.py - Position and daily risk controls (non-negotiable).
"""

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ── Risk constants ───────────────────────────────────────────────────────────
INITIAL_CAPITAL_SOL = 0.1
MAX_TRADE_SOL       = 0.02
MAX_OPEN_POSITIONS  = 1
MAX_HOLD_HOURS      = 4
STOP_LOSS_PCT       = -8.0
TAKE_PROFIT_PCT     = +15.0
MAX_CONSECUTIVE_LOSSES = 2
MIN_LIQUIDITY_USD   = 500


class RiskManager:
    def __init__(self):
        self.open_positions: list[dict] = []
        self.consecutive_losses: int = 0
        self.daily_halted: bool = False
        self.total_trades_today: int = 0
        self._session_start = datetime.now(timezone.utc)

    # ── Entry gate ───────────────────────────────────────────────────────────

    def can_enter(self, mode: str, data: dict) -> tuple[bool, str]:
        """Return (allowed, reason). Checks all entry filters."""
        if self.daily_halted:
            return False, "daily halt: 2 consecutive losses reached"

        if mode in ("ESCAPE", "SLEEP"):
            return False, f"mode is {mode} - no entry allowed"

        if len(self.open_positions) >= MAX_OPEN_POSITIONS:
            return False, f"max open positions ({MAX_OPEN_POSITIONS}) reached"

        # netflowデータから流動性をチェック（24h絶対値で代替）
        netflow_items = data.get("netflow", {}).get("data", [])
        if isinstance(netflow_items, list) and netflow_items:
            nf_24h = abs(float(netflow_items[0].get("net_flow_24h_usd", 0) or 0))
            if nf_24h < MIN_LIQUIDITY_USD:
                return False, f"low SM flow ${nf_24h:,.0f} (24h) — below min ${MIN_LIQUIDITY_USD:,}"

        return True, "all risk checks passed"

    # ── Position management ──────────────────────────────────────────────────

    def open_position(self, token: str, entry_price: float, size_sol: float):
        pos = {
            "token": token,
            "entry_price": entry_price,
            "size_sol": min(size_sol, MAX_TRADE_SOL),
            "opened_at": datetime.now(timezone.utc).isoformat(),
        }
        self.open_positions.append(pos)
        self.total_trades_today += 1
        logger.info("Position opened: %s @ %.6f, size %.4f SOL", token, entry_price, pos["size_sol"])

    def close_position(self, token: str, exit_price: float, result: str):
        """Mark position closed and update consecutive-loss counter."""
        self.open_positions = [p for p in self.open_positions if p["token"] != token]
        if result == "loss":
            self.consecutive_losses += 1
            logger.warning("Loss recorded. Consecutive losses: %d", self.consecutive_losses)
            if self.consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
                self.daily_halted = True
                logger.warning("DAILY HALT triggered after %d consecutive losses.", self.consecutive_losses)
        else:
            self.consecutive_losses = 0

    # ── Position checks ──────────────────────────────────────────────────────

    def should_exit(self, token: str, current_price: float) -> tuple[bool, str]:
        """Check SL/TP/max-hold for an open position."""
        for pos in self.open_positions:
            if pos["token"] != token:
                continue
            entry = pos["entry_price"]
            if entry == 0:
                continue
            pnl_pct = (current_price - entry) / entry * 100
            opened_at = datetime.fromisoformat(pos["opened_at"])
            hold_hours = (datetime.now(timezone.utc) - opened_at).total_seconds() / 3600

            if pnl_pct <= STOP_LOSS_PCT:
                return True, f"stop loss triggered ({pnl_pct:.1f}%)"
            if pnl_pct >= TAKE_PROFIT_PCT:
                return True, f"take profit triggered ({pnl_pct:.1f}%)"
            if hold_hours >= MAX_HOLD_HOURS:
                return True, f"max hold time reached ({hold_hours:.1f}h)"
        return False, "hold"

    # ── Status ───────────────────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "open_positions": len(self.open_positions),
            "consecutive_losses": self.consecutive_losses,
            "daily_halted": self.daily_halted,
            "total_trades_today": self.total_trades_today,
        }
