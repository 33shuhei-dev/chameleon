"""
universe.py - トークンユニバース管理
watchlist / cooldown / blacklist の3層でトークンを管理する

cache/universe.json に状態を保存・読み込みする
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

CACHE_PATH = Path("cache/universe.json")

# cooldown: 売買後に再エントリーしない時間（時間）
COOLDOWN_HOURS = 4

# watchlistの上限
WATCHLIST_MAX = 20


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hours_since(iso_str: str) -> float:
    try:
        dt = datetime.fromisoformat(iso_str)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600
    except Exception:
        return 9999.0


def load() -> dict:
    """universe.json を読み込む。なければ初期状態を返す。"""
    if CACHE_PATH.exists():
        try:
            with open(CACHE_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            logger.error("universe load error: %s", exc)

    return {
        "watchlist":  {},   # token_address -> メタ情報
        "cooldown":   {},   # token_address -> 最終売買時刻
        "blacklist":  [],   # token_address のリスト
        "updated_at": _now_iso(),
    }


def save(universe: dict):
    """universe.json に保存する。"""
    CACHE_PATH.parent.mkdir(exist_ok=True)
    universe["updated_at"] = _now_iso()
    try:
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(universe, f, indent=2, ensure_ascii=False)
    except Exception as exc:
        logger.error("universe save error: %s", exc)


def add_to_watchlist(universe: dict, token: dict):
    """
    スキャン結果のトークンをwatchlistに追加する。
    token: {"token_address": ..., "token_symbol": ..., "score": ..., ...}
    """
    addr = token.get("token_address", "")
    if not addr:
        return

    # blacklistは追加しない
    if addr in universe["blacklist"]:
        return

    # cooldown中は追加しない
    if is_in_cooldown(universe, addr):
        return

    # 上限チェック
    if len(universe["watchlist"]) >= WATCHLIST_MAX and addr not in universe["watchlist"]:
        # スコアが低い既存トークンを1件削除して入れ替え
        existing = universe["watchlist"]
        lowest = min(existing, key=lambda a: existing[a].get("score", 0))
        if token.get("score", 0) > existing[lowest].get("score", 0):
            del universe["watchlist"][lowest]
        else:
            return

    # watchlistに追加（既存なら更新）
    prev = universe["watchlist"].get(addr, {})
    prev_streak = prev.get("mode_streak", {})

    universe["watchlist"][addr] = {
        "token_symbol":               token.get("token_symbol", ""),
        "score":                      token.get("score", 0.0),
        "holders_count":              token.get("holders_count", 0),
        "balance_24h_percent_change": token.get("balance_24h_percent_change", 0.0),
        "market_cap_usd":             token.get("market_cap_usd", 0),
        "added_at":                   prev.get("added_at", _now_iso()),
        "last_seen":                  _now_iso(),
        "last_mode":                  prev.get("last_mode", "SLEEP"),
        "mode_streak":                prev_streak,  # {"STEALTH": 2, "CHASE": 0, ...}
    }


def update_mode(universe: dict, token_address: str, mode: str):
    """
    判定モードを記録し、mode_streakを更新する。
    STEALTH が3回連続 → CHASE 移行シグナルとして使える。
    """
    if token_address not in universe["watchlist"]:
        return

    entry = universe["watchlist"][token_address]
    entry["last_mode"] = mode

    streak = entry.get("mode_streak", {})
    # 同じモードならカウントアップ、違うモードはリセット
    for m in ["STEALTH", "CHASE", "ESCAPE", "SLEEP"]:
        if m == mode:
            streak[m] = streak.get(m, 0) + 1
        else:
            streak[m] = 0

    entry["mode_streak"] = streak


def get_streak(universe: dict, token_address: str, mode: str) -> int:
    """指定モードの連続回数を返す。"""
    entry = universe["watchlist"].get(token_address, {})
    return entry.get("mode_streak", {}).get(mode, 0)


def add_to_cooldown(universe: dict, token_address: str):
    """売買後にcooldownに入れる。"""
    universe["cooldown"][token_address] = _now_iso()
    logger.info("Cooldown set: %s", token_address)


def is_in_cooldown(universe: dict, token_address: str) -> bool:
    """cooldown中かどうか確認する。"""
    ts = universe["cooldown"].get(token_address)
    if not ts:
        return False
    return _hours_since(ts) < COOLDOWN_HOURS


def add_to_blacklist(universe: dict, token_address: str):
    """blacklistに追加し、watchlistから削除する。"""
    if token_address not in universe["blacklist"]:
        universe["blacklist"].append(token_address)
    universe["watchlist"].pop(token_address, None)
    logger.warning("Blacklisted: %s", token_address)


def get_watchlist_addresses(universe: dict) -> list[str]:
    """watchlist内のアドレス一覧を返す。"""
    return list(universe["watchlist"].keys())


def cleanup_stale(universe: dict, max_hours: int = 24):
    """last_seenが古いトークンをwatchlistから削除する。"""
    stale = [
        addr for addr, info in universe["watchlist"].items()
        if _hours_since(info.get("last_seen", _now_iso())) > max_hours
    ]
    for addr in stale:
        del universe["watchlist"][addr]
        logger.info("Removed stale token: %s", addr)
