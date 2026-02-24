#!/usr/bin/env python3
"""
Market Maker Ladder Fingerprinting via L2 Orderbook Diffs

Methodology:
    Given a known wallet's fill history (from Polymarket Subgraph), reconstruct
    their resting order strategy by diffing L2 book snapshots around each fill.

    For each fill event:
    1. Find the L2 snapshot immediately before and after the fill timestamp
    2. Diff the book at the fill price — vanishing quantity = the resting order
    3. Classify as maker (passive) or taker (aggressive) based on which side changed
    4. Catalog order sizes to identify distinctive size fingerprints
    5. Reconstruct level spacing to identify ladder structure

    This technique works because Polymarket's CLOB orderbook is transparent:
    L2 snapshots capture the full depth at each price level, and fills create
    observable discontinuities in the book state.

Why this matters:
    Market makers on Polymarket use static ladder strategies — resting limit
    orders at multiple price levels. By fingerprinting their order sizes and
    level spacing, we can:
    - Identify when a specific MM is active in a market
    - Estimate their inventory position from observable fills
    - Understand their aggression triggers (when they cross the spread)
    - Map the competitive landscape of liquidity provision

Data requirements:
    - L2 orderbook snapshots (JSONL.gz, captured via WebSocket)
    - Known wallet fill history (JSON, from Subgraph API)

Note: All analysis uses publicly visible on-chain data.
      No proprietary strategy parameters are included.
"""

import gzip
import json
import os
import numpy as np
from collections import defaultdict, Counter
from datetime import datetime
from bisect import bisect_right


# ── Configuration ─────────────────────────────────────────────────────
L2_DIR = os.environ.get("L2_DATA_DIR", "data/l2")
TRADES_FILE = os.environ.get("TRADES_FILE", "data/trades.json")
MIN_WINDOW_DURATION = 850  # seconds — skip truncated captures
MAX_BOOK_GAP = 5.0  # seconds — max gap between book snapshot and fill


def load_trades(filepath: str) -> dict:
    """Load wallet fill history, grouped by market window slug."""
    with open(filepath) as f:
        all_trades = json.load(f)

    by_slug = defaultdict(list)
    for t in all_trades:
        by_slug[t["slug"]].append(t)

    print(f"Loaded {len(all_trades):,} fills across {len(by_slug):,} windows")
    return dict(by_slug)


def load_l2_events(slug: str) -> list | None:
    """Load L2 orderbook events for a single market window."""
    path = os.path.join(L2_DIR, f"{slug}.jsonl.gz")
    if not os.path.exists(path):
        return None

    events = []
    try:
        with gzip.open(path, "rt") as f:
            for line in f:
                events.append(json.loads(line))
    except EOFError:
        pass  # truncated capture — use what we have

    return events if events else None


def build_book_timeline(events: list, asset: str) -> list:
    """
    Build timeline of full book states for one asset (up/dn).

    Returns list of (timestamp, bids_dict, asks_dict)
    where dicts map {price: size} at each level.
    Only includes 'book' events (full snapshots, not deltas).
    """
    timeline = []
    for ev in events:
        if ev["asset"] != asset or ev["event"] != "book":
            continue
        bids = {round(b[0], 2): b[1] for b in ev.get("bids", [])}
        asks = {round(a[0], 2): a[1] for a in ev.get("asks", [])}
        timeline.append((ev["ts"], bids, asks))
    return timeline


def find_book_around(timeline: list, fill_ts: float):
    """
    Binary search for the book snapshots immediately before and after a fill.

    Returns (before_snapshot, after_snapshot) or (None, None) if no
    snapshots exist within MAX_BOOK_GAP of the fill timestamp.
    """
    timestamps = [t[0] for t in timeline]
    idx = bisect_right(timestamps, fill_ts)

    before = timeline[idx - 1] if idx > 0 else None
    after = timeline[idx] if idx < len(timeline) else None

    # Validate time proximity
    if before and (fill_ts - before[0]) > MAX_BOOK_GAP:
        before = None
    if after and (after[0] - fill_ts) > MAX_BOOK_GAP:
        after = None

    return before, after


def classify_fill(fill_side: str, fill_size: float, fill_price: float,
                  before_bids: dict, before_asks: dict,
                  after_bids: dict, after_asks: dict) -> dict | None:
    """
    Classify a fill as maker or taker by observing which side of the book changed.

    Logic:
        - BUY fill: either consumed asks (taker) or his bid was resting (maker)
        - SELL fill: either consumed bids (taker) or his ask was resting (maker)

    We check both sides and classify based on which side shows vanishing quantity
    that matches the fill size (within 80% tolerance for partial fills).
    """
    # Compute vanished quantity on each side
    ask_before = before_asks.get(fill_price, 0)
    ask_after = after_asks.get(fill_price, 0)
    ask_vanished = ask_before - ask_after

    bid_before = before_bids.get(fill_price, 0)
    bid_after = after_bids.get(fill_price, 0)
    bid_vanished = bid_before - bid_after

    threshold = fill_size * 0.8  # 80% match tolerance

    if fill_side == "BUY":
        if ask_vanished >= threshold:
            return {"type": "taker", "vanished": ask_vanished,
                    "resting_before": ask_before}
        elif bid_vanished >= threshold:
            return {"type": "maker", "vanished": bid_vanished,
                    "resting_before": bid_before}
    else:  # SELL
        if bid_vanished >= threshold:
            return {"type": "taker", "vanished": bid_vanished,
                    "resting_before": bid_before}
        elif ask_vanished >= threshold:
            return {"type": "maker", "vanished": ask_vanished,
                    "resting_before": ask_before}

    return None  # no matching quantity change


def analyze_window(slug: str, trades: list, events: list) -> list:
    """
    Process all fills in a single market window, classifying each
    and extracting fingerprint data.
    """
    up_timeline = build_book_timeline(events, "up")
    dn_timeline = build_book_timeline(events, "dn")

    results = []
    for trade in trades:
        asset = "up" if trade["outcome"] == "Up" else "dn"
        timeline = up_timeline if asset == "up" else dn_timeline

        if not timeline:
            continue

        before, after = find_book_around(timeline, trade["timestamp"])
        if before is None or after is None:
            continue

        classification = classify_fill(
            fill_side=trade["side"],
            fill_size=trade["size"],
            fill_price=round(trade["price"], 2),
            before_bids=before[1], before_asks=before[2],
            after_bids=after[1], after_asks=after[2],
        )

        if classification is None:
            continue

        results.append({
            "fill_size": trade["size"],
            "fill_price": round(trade["price"], 2),
            "asset": asset,
            "slug": slug,
            "ts": trade["timestamp"],
            **classification,
        })

    return results


def reconstruct_ladder(fills: list) -> dict:
    """
    From classified maker fills, reconstruct the ladder structure:
    - Price levels used
    - Level spacing (distance between adjacent levels)
    - Order sizes at each level
    """
    maker_fills = [f for f in fills if f["type"] == "maker"]
    if len(maker_fills) < 3:
        return {}

    # Separate by asset
    for asset in ["up", "dn"]:
        asset_fills = [f for f in maker_fills if f["asset"] == asset]
        prices = sorted(set(f["fill_price"] for f in asset_fills))

        if len(prices) < 2:
            continue

        spacing = [round(prices[i + 1] - prices[i], 2)
                    for i in range(len(prices) - 1)]

        sizes_at_level = defaultdict(list)
        for f in asset_fills:
            sizes_at_level[f["fill_price"]].append(f["fill_size"])

        yield {
            "asset": asset,
            "levels": prices,
            "spacing": spacing,
            "mean_spacing": np.mean(spacing),
            "sizes_per_level": {p: np.mean(s) for p, s in sizes_at_level.items()},
        }


def print_fingerprint_summary(all_fills: list):
    """Print summary statistics of the fingerprinting analysis."""
    makers = [f for f in all_fills if f["type"] == "maker"]
    takers = [f for f in all_fills if f["type"] == "taker"]

    print(f"\n{'=' * 70}")
    print("FINGERPRINT SUMMARY")
    print(f"{'=' * 70}")
    print(f"Total classified fills: {len(all_fills):,}")
    print(f"Maker (passive): {len(makers):,} ({len(makers)/len(all_fills)*100:.1f}%)")
    print(f"Taker (aggressive): {len(takers):,} ({len(takers)/len(all_fills)*100:.1f}%)")

    if makers:
        maker_sizes = [f["fill_size"] for f in makers]
        print(f"\nMaker fill sizes:")
        print(f"  Mean: {np.mean(maker_sizes):.1f}")
        print(f"  Median: {np.median(maker_sizes):.1f}")

        # Top size frequencies — the fingerprint
        size_counts = Counter(int(s) for s in maker_sizes)
        print(f"\nMost common fill sizes (fingerprint):")
        for size, count in size_counts.most_common(10):
            pct = count / len(maker_sizes) * 100
            bar = "#" * int(pct)
            print(f"  {size:>6d} shares: {count:>5d} ({pct:.1f}%) {bar}")

    # Vanished-to-fill ratio (1.0 = sole order at that price)
    ratios = [f["vanished"] / max(f["fill_size"], 0.01) for f in all_fills]
    exact = sum(1 for r in ratios if 0.95 <= r <= 1.05)
    print(f"\nVanished/fill ratio:")
    print(f"  Exact match (0.95-1.05): {exact}/{len(ratios)} ({exact/len(ratios)*100:.1f}%)")
    print(f"  Mean ratio: {np.mean(ratios):.2f}")


def main():
    trades_by_slug = load_trades(TRADES_FILE)

    all_fills = []
    processed = 0

    for slug in sorted(trades_by_slug.keys()):
        events = load_l2_events(slug)
        if events is None or len(events) < 100:
            continue

        duration = events[-1]["ts"] - events[0]["ts"]
        if duration < MIN_WINDOW_DURATION:
            continue

        fills = analyze_window(slug, trades_by_slug[slug], events)
        all_fills.extend(fills)
        processed += 1

    print(f"\nProcessed {processed} windows")

    if all_fills:
        print_fingerprint_summary(all_fills)

        # Reconstruct ladders for windows with enough data
        print(f"\n{'=' * 70}")
        print("LADDER RECONSTRUCTION")
        print(f"{'=' * 70}")
        for slug in sorted(set(f["slug"] for f in all_fills))[:10]:
            window_fills = [f for f in all_fills if f["slug"] == slug]
            for ladder in reconstruct_ladder(window_fills):
                epoch = int(slug.split("-")[-1])
                ts_str = datetime.fromtimestamp(epoch).strftime("%H:%M")
                print(f"  {ts_str} {ladder['asset'].upper()}: "
                      f"levels={ladder['levels']} "
                      f"spacing={ladder['spacing']} "
                      f"mean_gap={ladder['mean_spacing']:.3f}")


if __name__ == "__main__":
    main()
