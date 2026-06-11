# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

Chameleon is a **Solana smart money signal tracker** that uses the Nansen Smart Money API to detect market states (STEALTH / CHASE / ESCAPE / SLEEP) and queue trades. It runs in paper-trading mode by default; live execution is opt-in via env var.

## Commands

```bash
# Install dependencies
pip install httpx streamlit plotly pandas

# Run the bot (10-min cycles, paper trading)
python chameleon.py

# Run a demo against all 4 mock scenarios without API credits
python demo_run.py

# Launch the live Streamlit dashboard (requires bot running to have log data)
streamlit run dashboard.py

# Inspect a raw Nansen API response for a single token
python debug_response.py
```

**Key environment variables** (all optional except `NANSEN_API_KEY`):

| Variable | Default | Description |
|---|---|---|
| `NANSEN_API_KEY` | — | Required for live mode |
| `USE_MOCK` | `false` | Use `mock_data/` instead of live API |
| `SCAN_TOP_N` | `5` | Tokens to scan per cycle |
| `CYCLE_SECS` | `600` | Seconds between cycles |
| `EXECUTION_ENABLED` | `false` | Enable real on-chain trades |

There is no test suite. Use `USE_MOCK=true python chameleon.py` or `python demo_run.py` to exercise the full pipeline without API credits.

## Architecture

### Signal pipeline (every cycle)

```
scanner.scan()
  → fetches top N Solana tokens by 1h SM netflow from Nansen
  → universe.add_to_watchlist() persists them to cache/universe.json

For each watchlist token:
  nansen_client.fetch_all(token)        # holdings + netflow + dcas
  → strategy.detect_mode(data)          # returns (mode, reason, confidence)
  → risk.can_enter(mode, data)          # gates STEALTH/CHASE entries
  → executor.execute_trade(token, side) # paper-queues or live-executes
  → log_api_usage / log_decision        # appends to logs/*.jsonl
```

After 3 consecutive STEALTH cycles for the same token, `chameleon.py` upgrades it to CHASE automatically (streak logic is in the main loop, not in `strategy.py`).

### Module responsibilities

| File | Role |
|---|---|
| `chameleon.py` | Main loop, mock-vs-live branching, STEALTH streak upgrade, log dispatch |
| `scanner.py` | Single Nansen netflow scan → ranked token list |
| `strategy.py` | Stateless `detect_mode(data) → (mode, reason, confidence)` |
| `nansen_client.py` | HTTP client; raises `SystemExit` on `CREDITS_EXHAUSTED` |
| `executor.py` | Trade dispatch; `EXECUTION_ENABLED=false` → paper-only; `TRADE_SIZE_SOL` constant lives here |
| `risk_manager.py` | Stateful; single `RiskManager` instance per process; all risk constants at module top |
| `universe.py` | JSON-backed watchlist; cooldown/blacklist/streak tracking; persisted to `cache/universe.json` |
| `api_usage_logger.py` | Appends to `logs/api_usage.jsonl`, `logs/decisions.jsonl`, `logs/cycle_summary.jsonl` |
| `dashboard.py` | Reads `logs/*.jsonl` and renders Streamlit UI; stateless reader |

### State that persists across cycles

- `cache/universe.json` — watchlist, cooldowns, blacklist, per-token mode streaks
- `logs/*.jsonl` — append-only evidence ledger
- `RiskManager` — in-memory only; resets on process restart (positions, loss counter, daily halt flag)

## Key Conventions

**Bilingual comments**: Inline comments and some log strings are written in Japanese. This is intentional — keep the style consistent when editing those files.

**`strategy.py` data access**: Always use the module-level `_first(data, key)` and `_sum_field(data, key)` helpers when reading Nansen response dicts. They guard against missing `data` arrays and `None` values. Do not read `data["holdings"]["data"][0][key]` directly.

**Risk constants are hard-coded** in `risk_manager.py` at the top of the module (`INITIAL_CAPITAL_SOL`, `MAX_TRADE_SOL`, `STOP_LOSS_PCT`, `TAKE_PROFIT_PCT`, etc.). Change them there; they are not env-configurable.

**Mock data format**: Files in `mock_data/` use a flattened schema. `chameleon._convert_mock()` translates them into the same `{"holdings": {"data": [...]}, "netflow": {"data": [...]}}` shape that `nansen_client.fetch_all()` returns, so `strategy.detect_mode()` is always called with the same structure regardless of mode.

**CREDITS_EXHAUSTED**: `nansen_client.py` calls `sys.exit()` on this error. The main loop in `chameleon.py` re-raises `SystemExit` rather than swallowing it — don't change this behavior.
