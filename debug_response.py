"""
debug_response.py - APIの実際のレスポンスを確認する（クレジット節約版）
SOL 1トークンのみ、1回だけ叩く
"""
import json
import os
import httpx

API_KEY  = os.getenv("NANSEN_API_KEY", "")
BASE_URL = "https://api.nansen.ai/api/v1"
TOKEN    = "So11111111111111111111111111111111111111112"  # SOL

headers = {"Content-Type": "application/json", "apikey": API_KEY}

print("=== holdings ===")
r = httpx.post(f"{BASE_URL}/smart-money/holdings", headers=headers, json={
    "chains": ["solana"],
    "filters": {
        "token_address": TOKEN,
        "include_native_tokens": True,
        "include_stablecoins": True,
    },
    "pagination": {"page": 1, "per_page": 3},
    "order_by": [{"field": "holders_count", "direction": "DESC"}],
})
print(json.dumps(r.json(), indent=2)[:2000])

print("\n=== netflow ===")
r = httpx.post(f"{BASE_URL}/smart-money/netflow", headers=headers, json={
    "chains": ["solana"],
    "filters": {
        "token_address": TOKEN,
        "include_native_tokens": True,
        "include_stablecoins": True,
    },
    "pagination": {"page": 1, "per_page": 3},
    "order_by": [{"field": "net_flow_24h_usd", "direction": "DESC"}],
})
print(json.dumps(r.json(), indent=2)[:2000])
