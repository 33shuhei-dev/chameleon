# 🦎 Chameleon — Smart Money Signal Tracker

Real-time Solana trading signal bot powered by **Nansen Smart Money API**.

Detects when smart money wallets are quietly accumulating, momentum chasing, or exiting — before the crowd notices.

---

## How It Works

```
Nansen API (netflow + holdings)
        ↓
  Scanner — top 5 tokens by 1h SM activity
        ↓
  Strategy — STEALTH / CHASE / ESCAPE / SLEEP
        ↓
  Executor — paper trade (real trade: opt-in)
        ↓
  Evidence Logs + Live Dashboard
```

### Signal Modes

| Mode | Meaning | Action |
|------|---------|--------|
| 🟣 STEALTH | SM quietly accumulating | BUY |
| 🟠 CHASE | SM activity spiking | BUY |
| 🔴 ESCAPE | SM exiting, large outflow | SELL |
| ⚫ SLEEP | No clear signal | Wait |

---

## API Evidence

Every run writes verified Nansen API call records to:

```
logs/api_usage.jsonl    — per-call proof (holdings + netflow)
logs/decisions.jsonl    — per-token mode/action/confidence
logs/cycle_summary.jsonl — per-cycle aggregates
```

Example `api_usage.jsonl` entry:
```json
{"timestamp":"2026-04-03T06:29:41Z","cycle_id":"20260403_062941","endpoint":"smart-money/holdings","token":"JUPyiwrYJFsk...","chain":"solana","status_code":200,"used_in_decision":true}
```

---

## Quick Start

```bash
# Install dependencies
pip install httpx streamlit plotly pandas

# Set API key
export NANSEN_API_KEY=your_key_here

# Run bot (paper trade mode)
python chameleon.py

# View live dashboard
streamlit run dashboard.py
```

---

## Project Structure

```
chameleon.py        — main loop (10-min cycles)
scanner.py          — Nansen netflow scan, top 5 tokens
strategy.py         — STEALTH/CHASE/ESCAPE/SLEEP detection
nansen_client.py    — Nansen REST API client
executor.py         — trade execution (paper/live)
risk_manager.py     — position sizing, daily halt
universe.py         — watchlist + mode streak tracking
api_usage_logger.py — structured evidence logging
dashboard.py        — Streamlit live dashboard
```

---

## Dashboard

```bash
streamlit run dashboard.py
```

Shows:
- Total API calls (proof of Nansen usage)
- Token-level decision log with mode/confidence/reason
- Mode distribution pie chart
- Per-cycle API call count + mode breakdown

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `NANSEN_API_KEY` | — | Required |
| `USE_MOCK` | `false` | Use mock data instead of live API |
| `SCAN_TOP_N` | `5` | Tokens to scan per cycle |
| `CYCLE_SECS` | `600` | Seconds between cycles |
| `EXECUTION_ENABLED` | `false` | Enable real trades |
