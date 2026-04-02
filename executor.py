"""
executor.py - Trade execution via nansen-cli subprocess.
Toggle execution ON/OFF with EXECUTION_ENABLED flag.
"""

import json
import logging
import subprocess

logger = logging.getLogger(__name__)

EXECUTION_ENABLED = False          # set True to enable live trades
NANSEN_CLI        = "nansen"       # CLI binary name on PATH
TRADE_SIZE_SOL    = 0.02


def _run_cli(args: list[str]) -> dict:
    """Run nansen-cli with args, return parsed JSON output."""
    cmd = [NANSEN_CLI] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"CLI exited {result.returncode}: {result.stderr.strip()}")
        return json.loads(result.stdout)
    except FileNotFoundError:
        raise RuntimeError(f"nansen-cli not found - is '{NANSEN_CLI}' on your PATH?")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"CLI returned non-JSON output: {exc}")


def get_quote(token: str, side: str, amount_sol: float) -> dict:
    """Fetch a trade quote from nansen-cli."""
    return _run_cli([
        "trade", "quote",
        "--token", token,
        "--side", side,
        "--amount", str(amount_sol),
        "--output", "json",
    ])


def execute_trade(token: str, side: str, amount_sol: float = TRADE_SIZE_SOL) -> dict:
    """
    Get a quote then execute it.
    Returns a result dict with keys: success, tx_hash, details, error.
    """
    result = {"token": token, "side": side, "amount_sol": amount_sol,
               "success": False, "tx_hash": None, "details": {}, "error": None}

    if not EXECUTION_ENABLED:
        result["success"] = True
        result["tx_hash"] = "MOCK_TX_DISABLED"
        result["details"] = {"note": "execution disabled - paper trade only"}
        logger.info("[PAPER] %s %s %.4f SOL - execution disabled", side.upper(), token, amount_sol)
        return result

    try:
        quote = get_quote(token, side, amount_sol)
        logger.info("Quote received for %s %s: %s", side, token, quote)

        exec_result = _run_cli([
            "trade", "execute",
            "--quote-id", quote["quote_id"],
            "--output", "json",
        ])

        result["success"] = True
        result["tx_hash"] = exec_result.get("tx_hash")
        result["details"] = exec_result
        logger.info("Trade executed: %s %s tx=%s", side, token, result["tx_hash"])

    except RuntimeError as exc:
        error_msg = str(exc)
        result["error"] = error_msg
        logger.error("Trade execution failed for %s: %s", token, error_msg)
        if "CREDITS_EXHAUSTED" in error_msg:
            raise SystemExit("CREDITS_EXHAUSTED - stopping immediately.")

    return result
