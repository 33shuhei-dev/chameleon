"""
nansen_client.py - Nansen REST API client (https://api.nansen.ai/api/v1/)
Auth: apikey header
"""

import logging
import os

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.nansen.ai/api/v1"
API_KEY  = os.getenv("NANSEN_API_KEY", "")
TIMEOUT  = 30


def _headers() -> dict:
    return {
        "Content-Type": "application/json",
        "apikey": API_KEY,
    }


def _post(endpoint: str, body: dict) -> dict | None:
    url = f"{BASE_URL}{endpoint}"
    try:
        response = httpx.post(url, headers=_headers(), json=body, timeout=TIMEOUT)

        if response.status_code == 402:
            raise SystemExit("CREDITS_EXHAUSTED - stopping immediately.")
        if response.status_code == 401:
            logger.error("Auth error - check your API key")
            return None
        if response.status_code != 200:
            logger.error("API error %d: %s", response.status_code, response.text[:300])
            return None

        return response.json()

    except SystemExit:
        raise
    except httpx.TimeoutException:
        logger.error("Timeout: %s", endpoint)
        return None
    except httpx.RequestError as exc:
        logger.error("Request error: %s", exc)
        return None
    except Exception as exc:
        logger.error("Unexpected error: %s", exc)
        return None


def _post_with_retry(endpoint: str, body: dict) -> dict | None:
    result = _post(endpoint, body)
    if result is None:
        logger.warning("Retrying: %s", endpoint)
        result = _post(endpoint, body)
    return result


# ── Endpoints ────────────────────────────────────────────────────────────────

def get_holdings(token_address: str, chain: str = "solana") -> dict | None:
    """SM holder count and concentration."""
    return _post_with_retry(
        "/smart-money/holdings",
        {
            "chains": [chain],
            "filters": {
                "token_address": token_address,
                "include_native_tokens": True,
                "include_stablecoins": True,
            },
            "pagination": {"page": 1, "per_page": 20},
            "order_by": [{"field": "holders_count", "direction": "DESC"}],
        },
    )


def get_netflow(token_address: str, chain: str = "solana") -> dict | None:
    """Smart money net inflow / outflow data."""
    return _post_with_retry(
        "/smart-money/netflow",
        {
            "chains": [chain],
            "filters": {
                "token_address": token_address,
                "include_native_tokens": True,
                "include_stablecoins": True,
            },
            "pagination": {"page": 1, "per_page": 20},
            "order_by": [{"field": "net_flow_24h_usd", "direction": "DESC"}],
        },
    )


def get_dcas(token_address: str) -> dict | None:
    """Jupiter DCA activity for a Solana token (Solana-only, no chains field)."""
    return _post_with_retry(
        "/smart-money/dcas",
        {
            "filters": {"token_address": token_address},
            "pagination": {"page": 1, "per_page": 20},
            "order_by": [{"field": "dca_created_at", "direction": "DESC"}],
        },
    )


def fetch_all(token_address: str, chain: str = "solana") -> dict | None:
    """Fetch all data for a token. Returns None if any endpoint fails."""
    if not API_KEY:
        logger.error("NANSEN_API_KEY is not set")
        return None

    holdings = get_holdings(token_address, chain)
    netflow  = get_netflow(token_address, chain)

    if any(v is None for v in [holdings, netflow]):
        logger.error("Data fetch failed for: %s", token_address)
        return None

    return {
        "token":    token_address,
        "holdings": holdings,
        "netflow":  netflow,
        "dcas":     {"data": []},  # not used
    }
