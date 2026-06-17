"""
api_usage_logger.py - API使用・判定・サイクルの証拠ログ
logs/api_usage.jsonl / decisions.jsonl / cycle_summary.jsonl に出力する

v2: quality_score / quality_avg フィールドを追加 (DECISION_LOG v1.1 / CYCLE_SUMMARY v1.1)
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

_api_log      = LOG_DIR / "api_usage.jsonl"
_decision_log = LOG_DIR / "decisions.jsonl"
_summary_log  = LOG_DIR / "cycle_summary.jsonl"

logger = logging.getLogger(__name__)


def _write(path: Path, record: dict):
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.error("logger write error (%s): %s", path.name, exc)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log_api_usage(
    cycle_id:         str,
    endpoint:         str,
    token:            str,
    chain:            str,
    status_code:      int,
    response_summary: dict,
    used_in_decision: bool,
):
    _write(_api_log, {
        "timestamp":        _now(),
        "cycle_id":         cycle_id,
        "endpoint":         endpoint,
        "token":            token,
        "chain":            chain,
        "status_code":      status_code,
        "used_in_decision": used_in_decision,
        "response_summary": response_summary,
        "schema_version":   "1.0.0",
    })


def log_decision(
    cycle_id:      str,
    token:         str,
    chain:         str,
    mode:          str,
    action:        str,
    confidence:    float,
    reason:        str,
    quality_score: int = 0,
):
    _write(_decision_log, {
        "timestamp":     _now(),
        "cycle_id":      cycle_id,
        "token":         token,
        "chain":         chain,
        "mode":          mode,
        "action":        action,
        "confidence":    confidence,
        "reason":        reason,
        "quality_score": quality_score,
        "schema_version": "1.1.0",
    })


def log_cycle_summary(
    cycle_id:      str,
    watchlist_size: int,
    api_calls:     int,
    mode_counts:   dict,
    quality_avg:   float = 0.0,
):
    _write(_summary_log, {
        "timestamp":      _now(),
        "cycle_id":       cycle_id,
        "watchlist_size": watchlist_size,
        "api_calls":      api_calls,
        "mode_counts":    mode_counts,
        "quality_avg":    quality_avg,
        "schema_version": "1.1.0",
    })
