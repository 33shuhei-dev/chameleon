"""
quality_gate.py - 14-point signal quality evaluation engine
Each gate is a pass/fail check yielding 0 or 1 point. Total: 0–14.

Thresholds:
  BUY  (STEALTH / CHASE)  : >= 10 / 14  (71%)
  SELL (ESCAPE)           : >=  8 / 14  (57%)
  HOLD (SLEEP)            : always passes

Design principle: RuntimeがMetaを参照不可 — this module must not import
universe or risk_manager directly; callers pass data in.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

GATE_THRESHOLDS = {
    "BUY":  10,
    "SELL":  8,
    "HOLD":  0,
}


@dataclass
class GateResult:
    gate_id: str
    name:    str
    passed:  bool
    score:   int   # 0 or 1
    detail:  str


@dataclass
class QualityReport:
    total_score:    int
    max_score:      int
    passed:         bool
    action_allowed: bool
    gate_results:   list[GateResult] = field(default_factory=list)
    blocking_gates: list[str]        = field(default_factory=list)

    @property
    def score_pct(self) -> float:
        return round(self.total_score / self.max_score, 3) if self.max_score else 0.0

    def to_dict(self) -> dict:
        return {
            "total_score":    self.total_score,
            "max_score":      self.max_score,
            "score_pct":      self.score_pct,
            "passed":         self.passed,
            "action_allowed": self.action_allowed,
            "blocking_gates": self.blocking_gates,
            "gate_details": {
                r.gate_id: {"name": r.name, "passed": r.passed, "detail": r.detail}
                for r in self.gate_results
            },
        }


def _gate(gate_id: str, name: str, condition: bool, detail: str) -> GateResult:
    return GateResult(gate_id=gate_id, name=name, passed=condition,
                      score=1 if condition else 0, detail=detail)


def evaluate(
    mode:          str,
    confidence:    float,
    data:          dict,
    universe_data: dict | None = None,
    risk_manager=None,
    token_address: str = "",
) -> QualityReport:
    """
    Run all 14 quality gates and return a QualityReport.

    Gates (in order):
      QG-01  Data Completeness         — holdings + netflow arrays present
      QG-02  API Data Validity         — both data arrays non-empty
      QG-03  SM Holder Minimum         — SM holder count >= 1
      QG-04  Flow Direction Clarity    — netflow direction matches mode
      QG-05  Flow Magnitude            — |netflow_1h| > $10
      QG-06  SM Concentration          — share_of_holdings_percent > 0
      QG-07  Trader Activity           — trader_count >= 1
      QG-08  Confidence Threshold      — strategy confidence >= 0.55
      QG-09  Cooldown Compliance       — token not in active cooldown
      QG-10  Blacklist Clear           — token not blacklisted
      QG-11  Risk Capacity             — daily halt not active
      QG-12  Schema Consistency        — all required API fields present
      QG-13  Mode-Signal Alignment     — mode logically consistent with data
      QG-14  Signal Strength           — meets mode-specific strength bar
    """
    holdings = data.get("holdings", {})
    netflow  = data.get("netflow",  {})

    h_items = holdings.get("data", [])
    n_items = netflow.get("data",  [])
    h0 = h_items[0] if h_items else {}
    n0 = n_items[0] if n_items else {}

    sm_holders    = float(h0.get("holders_count",                0) or 0)
    holder_change = float(h0.get("balance_24h_percent_change",   0) or 0)
    share_pct     = float(h0.get("share_of_holdings_percent",    0) or 0)
    netflow_1h    = float(n0.get("net_flow_1h_usd",              0) or 0)
    netflow_24h   = float(n0.get("net_flow_24h_usd",             0) or 0)
    trader_count  = float(n0.get("trader_count",                 0) or 0)

    results: list[GateResult] = []

    # QG-01: Data Completeness
    has_h = bool(holdings) and bool(h_items)
    has_n = bool(netflow)  and bool(n_items)
    results.append(_gate(
        "QG-01", "Data Completeness", has_h and has_n,
        f"holdings={'ok' if has_h else 'missing'}, netflow={'ok' if has_n else 'missing'}",
    ))

    # QG-02: API Data Validity
    valid = bool(h_items) and bool(n_items)
    results.append(_gate(
        "QG-02", "API Data Validity", valid,
        f"h_items={len(h_items)}, n_items={len(n_items)}",
    ))

    # QG-03: SM Holder Minimum
    holder_ok = sm_holders >= 1
    results.append(_gate(
        "QG-03", "SM Holder Minimum", holder_ok,
        f"SM holders={sm_holders:.0f} (min=1)",
    ))

    # QG-04: Flow Direction Clarity (mode-aware)
    if mode in ("STEALTH", "CHASE"):
        dir_ok = netflow_1h > 10
    elif mode == "ESCAPE":
        dir_ok = netflow_1h < -10
    else:
        dir_ok = True
    results.append(_gate(
        "QG-04", "Flow Direction Clarity", dir_ok,
        f"netflow_1h={netflow_1h:+.0f} USD, mode={mode}",
    ))

    # QG-05: Flow Magnitude
    mag_ok = abs(netflow_1h) > 10
    results.append(_gate(
        "QG-05", "Flow Magnitude", mag_ok,
        f"|netflow_1h|={abs(netflow_1h):.0f} USD (min=10)",
    ))

    # QG-06: SM Concentration
    conc_ok = share_pct > 0
    results.append(_gate(
        "QG-06", "SM Concentration", conc_ok,
        f"share_pct={share_pct:.1f}%",
    ))

    # QG-07: Trader Activity
    trader_ok = trader_count >= 1
    results.append(_gate(
        "QG-07", "Trader Activity", trader_ok,
        f"trader_count={trader_count:.0f} (min=1)",
    ))

    # QG-08: Confidence Threshold
    conf_ok = confidence >= 0.55
    results.append(_gate(
        "QG-08", "Confidence Threshold", conf_ok,
        f"confidence={confidence:.2f} (min=0.55)",
    ))

    # QG-09: Cooldown Compliance
    if universe_data and token_address:
        cooldown = universe_data.get("cooldown", {})
        in_cd = token_address in cooldown
        if in_cd:
            try:
                until = datetime.fromisoformat(cooldown[token_address].replace("Z", "+00:00"))
                in_cd = datetime.now(timezone.utc) < until
            except Exception:
                pass
        cooldown_ok = not in_cd
    else:
        cooldown_ok = True
    results.append(_gate(
        "QG-09", "Cooldown Compliance", cooldown_ok,
        "not in cooldown" if cooldown_ok else "token in active cooldown",
    ))

    # QG-10: Blacklist Clear
    if universe_data and token_address:
        bl_ok = token_address not in universe_data.get("blacklist", [])
    else:
        bl_ok = True
    results.append(_gate(
        "QG-10", "Blacklist Clear", bl_ok,
        "not blacklisted" if bl_ok else "token is blacklisted",
    ))

    # QG-11: Risk Capacity
    if risk_manager is not None:
        cap_ok = not risk_manager.daily_halted
        detail = "ok" if cap_ok else "daily halt active"
    else:
        cap_ok = True
        detail = "no risk manager (pass)"
    results.append(_gate("QG-11", "Risk Capacity", cap_ok, detail))

    # QG-12: Schema Consistency
    req_h = {"holders_count", "balance_24h_percent_change", "share_of_holdings_percent"}
    req_n = {"net_flow_1h_usd", "net_flow_24h_usd", "trader_count"}
    h_ok  = req_h.issubset(h0.keys()) if h0 else False
    n_ok  = req_n.issubset(n0.keys()) if n0 else False
    schema_ok = h_ok and n_ok
    results.append(_gate(
        "QG-12", "Schema Consistency", schema_ok,
        f"holdings={'ok' if h_ok else 'fields missing'}, netflow={'ok' if n_ok else 'fields missing'}",
    ))

    # QG-13: Mode-Signal Alignment
    if mode == "STEALTH":
        align_ok = (holder_change >= 0 or trader_count >= 1) and netflow_1h > 0
    elif mode == "CHASE":
        align_ok = netflow_1h > 100
    elif mode == "ESCAPE":
        align_ok = netflow_1h < 0
    else:
        align_ok = True
    results.append(_gate(
        "QG-13", "Mode-Signal Alignment", align_ok,
        f"mode={mode}, netflow_1h={netflow_1h:+.0f}, holder_change={holder_change:+.1f}%",
    ))

    # QG-14: Signal Strength (mode-specific threshold)
    if mode == "STEALTH":
        strength_ok = (sm_holders >= 1 and netflow_1h > 10) or trader_count >= 1
    elif mode == "CHASE":
        strength_ok = netflow_1h > 200 and trader_count >= 2
    elif mode == "ESCAPE":
        strength_ok = netflow_1h < -50
    else:
        strength_ok = True
    results.append(_gate(
        "QG-14", "Signal Strength", strength_ok,
        f"mode={mode} strength: {'pass' if strength_ok else 'below threshold'}",
    ))

    # ── Aggregate ──────────────────────────────────────────────────────────────
    total    = sum(r.score for r in results)
    max_s    = len(results)

    if mode in ("STEALTH", "CHASE"):
        required       = GATE_THRESHOLDS["BUY"]
        action_allowed = total >= required
    elif mode == "ESCAPE":
        required       = GATE_THRESHOLDS["SELL"]
        action_allowed = total >= required
    else:
        action_allowed = True

    blocking = [r.gate_id for r in results if not r.passed and mode != "SLEEP"]

    logger.debug(
        "QualityGate %s score=%d/%d (%s) blocking=%s",
        mode, total, max_s, "PASS" if action_allowed else "FAIL", blocking,
    )

    return QualityReport(
        total_score    = total,
        max_score      = max_s,
        passed         = action_allowed,
        action_allowed = action_allowed,
        gate_results   = results,
        blocking_gates = blocking,
    )
