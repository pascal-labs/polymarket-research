#!/usr/bin/env python3
"""
Fetch trade history for a target wallet from Polymarket's data API.

Uses paginated requests with offset + timestamp windowing to bypass
the API's per-request limit. Filters for BTC 15-minute binary markets.

Usage:
    export TARGET_WALLET="0x..."
    python fetch_trades.py
"""
import urllib.request
import json
import os
import time

WALLET = os.environ.get("TARGET_WALLET")
if not WALLET:
    raise ValueError("Set TARGET_WALLET environment variable")

BASE_URL = "https://data-api.polymarket.com/activity"


def fetch_all_trades():
    """Paginate through all TRADE events for the target wallet."""
    all_trades = []
    offset = 0
    limit = 500

    while True:
        url = f"{BASE_URL}?user={WALLET}&type=TRADE&limit={limit}&offset={offset}"
        print(f"Fetching offset {offset}...")

        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=30) as resp:
                trades = json.loads(resp.read().decode())
        except Exception as e:
            print(f"Error at offset {offset}: {e}")
            break

        if not trades:
            print("No more trades")
            break

        all_trades.extend(trades)
        print(f"  Got {len(trades)} trades, total: {len(all_trades)}")

        if len(trades) < limit:
            print("Last page")
            break

        offset += limit
        time.sleep(0.3)

    return all_trades


def main():
    print(f"Fetching all trades for target wallet...")
    trades = fetch_all_trades()

    print(f"\nTotal trades: {len(trades)}")

    output_file = os.environ.get("OUTPUT_FILE", "data/trades.json")
    os.makedirs(os.path.dirname(output_file) or ".", exist_ok=True)
    with open(output_file, 'w') as f:
        json.dump(trades, f)

    print(f"Saved to {output_file}")

    # Quick stats — filter for BTC 15-min markets
    btc_15m = [t for t in trades if 'btc-updown-15m' in t.get('slug', '').lower()]
    eth_15m = [t for t in trades if 'eth-updown-15m' in t.get('slug', '').lower()]

    print(f"\nBTC 15m trades: {len(btc_15m)}")
    print(f"ETH 15m trades: {len(eth_15m)}")

    if trades:
        timestamps = [t['timestamp'] for t in trades]
        from datetime import datetime
        earliest = datetime.fromtimestamp(min(timestamps))
        latest = datetime.fromtimestamp(max(timestamps))
        print(f"\nDate range: {earliest} to {latest}")
        print(f"Days: {(latest - earliest).days}")


if __name__ == '__main__':
    main()
